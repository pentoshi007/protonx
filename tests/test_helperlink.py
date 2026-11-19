import errno
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "helper"))

import protonx_helper as daemon
import helper_linux
from protonxlib import helper as client
from protonxlib import service
from protonxlib.errors import TunnelError


def legacy_respond(connection):
    """The 1.1.1 helper: it answers without reading the request first."""
    with connection:
        connection.sendall(json.dumps({"ok": False, "error": "permission denied"}).encode() + b"\n")


def serve_once(responder):
    server, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    thread = threading.Thread(target=responder, args=(server,), daemon=True)
    thread.start()
    return peer, thread


def exchange(peer, payload, timeout=30):
    try:
        peer.settimeout(timeout)
        peer.sendall(payload)
        data = b""
        while not data.endswith(b"\n"):
            chunk = peer.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode())
    finally:
        peer.close()


class ResponderTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            mock.patch.object(daemon.system, "may_control", return_value=False),
            mock.patch.object(daemon.system, "peer_uid", return_value=501),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_old_helper_loses_its_reply_when_the_request_is_still_queued(self):
        peer, thread = serve_once(legacy_respond)
        with self.assertRaises(OSError):
            exchange(peer, b"{" + b"x" * 400000 + b"}\n")
        thread.join(5)

    def test_denied_request_still_gets_a_readable_answer(self):
        peer, thread = serve_once(daemon._respond)
        reply = exchange(peer, b'{"command": "up"}\n')
        thread.join(5)
        self.assertEqual(reply, {"ok": False, "error": "permission denied"})

    def test_oversized_request_is_answered_instead_of_reset(self):
        peer, thread = serve_once(daemon._respond)
        reply = exchange(peer, b"{" + b"x" * 400000 + b"}\n")
        thread.join(5)
        self.assertEqual(reply["error"], "request too large")

    def test_unexpected_failure_is_still_answered(self):
        peer, thread = serve_once(daemon._respond)
        with mock.patch.object(daemon.system, "may_control", return_value=True), mock.patch.object(
            daemon, "dispatch", side_effect=RuntimeError("boom")
        ):
            reply = exchange(peer, b'{"command": "status"}\n')
        thread.join(5)
        self.assertIn("unexpected failure", reply["error"])

    def test_unreadable_payload_is_reported(self):
        peer, thread = serve_once(daemon._respond)
        with mock.patch.object(daemon.system, "may_control", return_value=True):
            reply = exchange(peer, b"not json\n")
        thread.join(5)
        self.assertIn("unreadable request", reply["error"])

    def test_a_failing_credential_check_is_still_answered(self):
        peer, thread = serve_once(daemon._respond)
        with mock.patch.object(daemon.system, "peer_uid", side_effect=NameError("SO_PEERCRED")):
            reply = exchange(peer, b'{"command": "status"}\n')
        thread.join(5)
        self.assertIn("unexpected failure", reply["error"])

    def test_authorised_request_reaches_dispatch(self):
        peer, thread = serve_once(daemon._respond)
        with mock.patch.object(daemon.system, "may_control", return_value=True), mock.patch.object(
            daemon, "dispatch", return_value={"ok": True, "up": False}
        ) as dispatch:
            reply = exchange(peer, b'{"command": "status"}\n')
        thread.join(5)
        self.assertEqual(reply, {"ok": True, "up": False})
        dispatch.assert_called_once_with({"command": "status"})


class LinuxPeerCredTests(unittest.TestCase):
    """1.1.1 raised NameError here, which reset every Linux request."""

    class FakeConnection:
        def __init__(self, payload):
            self.payload = payload
            self.seen = None

        def getsockopt(self, level, option, size):
            self.seen = (level, option, size)
            return self.payload

    def test_uid_comes_from_so_peercred(self):
        peer = self.FakeConnection(struct.pack("3i", 4242, 1000, 1000))
        self.assertEqual(helper_linux.peer_uid(peer), 1000)
        self.assertEqual(peer.seen[0], socket.SOL_SOCKET)
        self.assertEqual(peer.seen[1], getattr(socket, "SO_PEERCRED", 17))

    def test_the_credential_constant_is_defined(self):
        self.assertTrue(hasattr(helper_linux, "SO_PEERCRED"))

    def test_short_credentials_are_ignored(self):
        self.assertIsNone(helper_linux.peer_uid(self.FakeConnection(b"\x00")))

    def test_socket_error_is_ignored(self):
        class Broken:
            def getsockopt(self, *args):
                raise OSError("nope")

        self.assertIsNone(helper_linux.peer_uid(Broken()))

    @unittest.skipUnless(sys.platform.startswith("linux"), "SO_PEERCRED is Linux only")
    def test_real_socket_reports_the_caller_uid(self):
        server, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.assertEqual(helper_linux.peer_uid(server), os.getuid())
        finally:
            server.close()
            peer.close()


class ClientTransportTests(unittest.TestCase):
    def call(self, request=None):
        with mock.patch.object(client, "available", return_value=True):
            return client.call(request or {"command": "status"})

    def test_transient_reset_is_retried(self):
        drops = [client._Dropped("reset", errno.ECONNRESET), {"ok": True, "up": True}]
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "_exchange", side_effect=drops
        ) as exchange, mock.patch.object(client.time, "sleep") as sleep:
            self.assertTrue(client.call({"command": "status"})["up"])
        self.assertEqual(exchange.call_count, 2)
        sleep.assert_called_once()

    def test_persistent_reset_explains_itself(self):
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "_exchange", side_effect=client._Dropped("reset", errno.ECONNRESET)
        ), mock.patch.object(client.time, "sleep"), mock.patch.object(
            client, "permission_hint", return_value=None
        ), mock.patch.object(client.system, "IS_LINUX", True):
            with self.assertRaises(TunnelError) as caught:
                client.call({"command": "up"})
        message = str(caught.exception)
        self.assertIn("dropped the connection", message)
        self.assertIn("restart protonx-helper", message)

    def test_refused_connection_is_reported_as_not_listening(self):
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "_exchange", side_effect=client._Dropped("refused", errno.ECONNREFUSED)
        ), mock.patch.object(client.time, "sleep"):
            with self.assertRaises(TunnelError) as caught:
                client.call({"command": "status"})
        self.assertIn("not listening", str(caught.exception))

    def test_application_error_is_not_retried(self):
        reply = {"ok": False, "error": "wg-quick up failed: no such device"}
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "_exchange", return_value=reply
        ) as exchange:
            with self.assertRaises(TunnelError) as caught:
                client.call({"command": "up"})
        self.assertEqual(exchange.call_count, 1)
        self.assertIn("no such device", str(caught.exception))

    def test_permission_reply_uses_the_group_hint(self):
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "_exchange", return_value={"ok": False, "error": "permission denied"}
        ):
            with self.assertRaises(TunnelError) as caught:
                client.call({"command": "up"})
        self.assertIn("protonx", str(caught.exception))

    def test_missing_socket_says_the_helper_is_not_running(self):
        with mock.patch.object(client, "available", return_value=False):
            with self.assertRaises(TunnelError) as caught:
                client.call({"command": "status"})
        self.assertIn("not running", str(caught.exception))

    def test_up_reports_the_tunnel_when_only_the_reply_was_lost(self):
        report = {"ok": True, "up": True, "server": {"server": "MX-FREE#11"}}
        with mock.patch.object(client, "call", side_effect=[TunnelError("dropped"), report]):
            self.assertTrue(client.up({}, {"server": "MX-FREE#11"})["up"])

    def test_up_does_not_hide_a_failed_connect(self):
        other = {"ok": True, "up": True, "server": {"server": "NL-FREE#1"}}
        with mock.patch.object(client, "call", side_effect=[TunnelError("failed"), other]):
            with self.assertRaises(TunnelError):
                client.up({}, {"server": "MX-FREE#11"})

    def test_up_fails_when_nothing_is_up(self):
        down = {"ok": True, "up": False, "server": None}
        with mock.patch.object(client, "call", side_effect=[TunnelError("failed"), down]):
            with self.assertRaises(TunnelError):
                client.up({}, {"server": "MX-FREE#11"})


class GroupTests(unittest.TestCase):
    GROUP = mock.Mock(gr_gid=1001)

    def problem(self, uid=1000, groups=(1000,), group=None, lookup=None):
        with mock.patch.object(client.system, "IS_LINUX", True), mock.patch.object(
            client.os, "geteuid", return_value=uid
        ), mock.patch.object(client.grp, "getgrnam", return_value=group or self.GROUP), mock.patch.object(
            client.pwd, "getpwuid", return_value=mock.Mock(pw_name="ubuntu")
        ), mock.patch.object(client.os, "getgrouplist", return_value=list(groups)):
            return client.group_problem()

    def test_member_is_accepted(self):
        self.assertIsNone(self.problem(groups=(1000, 1001)))

    def test_root_is_never_blocked(self):
        self.assertIsNone(self.problem(uid=0, groups=(0,)))

    def test_missing_membership_is_named(self):
        self.assertIn("ubuntu", self.problem())

    def test_missing_membership_explains_the_fix(self):
        with mock.patch.object(client, "group_problem", return_value="user ubuntu is not in the protonx group"):
            hint = client.permission_hint()
        self.assertIn("usermod -aG protonx", hint)
        self.assertIn("newgrp protonx", hint)

    def test_missing_group_is_reported(self):
        with mock.patch.object(client.system, "IS_LINUX", True), mock.patch.object(
            client.os, "geteuid", return_value=1000
        ), mock.patch.object(client.grp, "getgrnam", side_effect=KeyError("protonx")):
            self.assertIn("reinstall", client.group_problem())

    def test_doctor_fails_when_the_group_is_missing(self):
        with mock.patch.object(client, "available", return_value=True), mock.patch.object(
            client, "group_problem", return_value="user ubuntu is not in the protonx group"
        ):
            name, value, ok = service._tunnel_check()
        self.assertEqual(name, "helper")
        self.assertFalse(ok)
        self.assertIn("protonx", value)


class SocketRoundTripTests(unittest.TestCase):
    """Both halves of the protocol against a real Unix socket."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "helper.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(4)
        self.stop = threading.Event()
        for patcher in (
            mock.patch.object(client, "SOCKET_PATH", self.path),
            mock.patch.object(daemon.system, "peer_uid", return_value=0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        threading.Thread(target=self.serve, daemon=True).start()
        self.addCleanup(self.server.close)
        self.addCleanup(self.stop.set)

    def serve(self):
        while not self.stop.is_set():
            self.server.settimeout(0.2)
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=daemon._respond, args=(connection,), daemon=True).start()

    def test_status_round_trips(self):
        with mock.patch.object(daemon.system, "may_control", return_value=True), mock.patch.object(
            daemon, "dispatch", return_value={"ok": True, "up": True, "server": {"server": "MX-FREE#11"}}
        ):
            self.assertEqual(client.status()["server"]["server"], "MX-FREE#11")

    def test_denied_user_gets_the_hint_not_a_reset(self):
        with mock.patch.object(daemon.system, "may_control", return_value=False):
            with self.assertRaises(TunnelError) as caught:
                client.up({"private_key": "x"}, {"server": "MX-FREE#11"})
        self.assertIn("refused this user", str(caught.exception))

    def test_oversized_connect_gets_an_error_instead_of_a_reset(self):
        with mock.patch.object(daemon.system, "may_control", return_value=True), mock.patch.object(
            daemon, "dispatch", return_value={"ok": True, "up": False}
        ):
            with self.assertRaises(TunnelError) as caught:
                client.up({"private_key": "x" * 400000}, {"server": "MX-FREE#11"})
        self.assertIn("too large", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
