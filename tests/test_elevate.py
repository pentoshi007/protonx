import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from protonxlib import elevate, service, system, tunnel_windows
from protonxlib.errors import TunnelError

SETTINGS = {
    "private_key": base64.b64encode(bytes(range(32))).decode(),
    "address": "10.2.0.2/32",
    "peer_public_key": base64.b64encode(bytes(range(32, 64))).decode(),
    "allowed_ips": "0.0.0.0/0",
    "endpoint_host": "nl-1.protonvpn.net",
    "endpoint_port": 51820,
    "dns": "10.2.0.1",
    "mtu": 1420,
    "keepalive": 25,
}


class PrivilegedDispatchTests(unittest.TestCase):
    def test_elevated_process_runs_the_operation_directly(self):
        with mock.patch.object(system, "is_admin", return_value=True), mock.patch.object(
            elevate, "run"
        ) as launcher, mock.patch.object(tunnel_windows, "run_local", return_value={"up": True}) as local:
            self.assertEqual(tunnel_windows._privileged("up", {"x": 1}), {"up": True})
        local.assert_called_once_with("up", {"x": 1})
        launcher.assert_not_called()

    def test_unprivileged_process_raises_the_uac_prompt(self):
        with mock.patch.object(system, "is_admin", return_value=False), mock.patch.object(
            elevate, "run", return_value={"up": True}
        ) as launcher:
            self.assertEqual(tunnel_windows._privileged("down"), {"up": True})
        launcher.assert_called_once_with("down", None)

    def test_up_elevates_with_the_validated_settings(self):
        with mock.patch.object(system, "is_admin", return_value=False), mock.patch.object(
            tunnel_windows, "_executable", return_value="wireguard.exe"
        ), mock.patch.object(elevate, "run", return_value={"up": True}) as launcher:
            self.assertEqual(tunnel_windows.up(SETTINGS), {"up": True})
        launcher.assert_called_once_with("up", SETTINGS)

    def test_up_rejects_a_bad_config_before_asking_for_permission(self):
        with mock.patch.object(system, "is_admin", return_value=False), mock.patch.object(
            tunnel_windows, "_executable", return_value="wireguard.exe"
        ), mock.patch.object(elevate, "run") as launcher:
            with self.assertRaises(TunnelError):
                tunnel_windows.up(dict(SETTINGS, endpoint_port="51820"))
        launcher.assert_not_called()

    def test_disconnect_without_a_tunnel_does_not_prompt(self):
        with mock.patch.object(tunnel_windows, "_service_state", return_value=None), mock.patch.object(
            tunnel_windows, "CONFIG_PATH", "/nonexistent/protonx.conf"
        ), mock.patch.object(elevate, "run") as launcher:
            report = tunnel_windows.down()
        self.assertFalse(report["up"])
        launcher.assert_not_called()

    def test_disconnect_with_a_tunnel_elevates(self):
        with mock.patch.object(system, "is_admin", return_value=False), mock.patch.object(
            tunnel_windows, "_service_state", return_value="RUNNING"
        ), mock.patch.object(elevate, "run", return_value={"up": False}) as launcher:
            tunnel_windows.down()
        launcher.assert_called_once_with("down", None)


class RunLocalTests(unittest.TestCase):
    def test_dispatch_maps_each_operation(self):
        calls = []
        patches = {
            "_up": lambda payload: calls.append(("up", payload)) or {"operation": "up"},
            "_down": lambda: calls.append(("down", None)) or {"operation": "down"},
            "_repair": lambda: calls.append(("repair", None)) or {"operation": "repair"},
        }
        with mock.patch.object(system, "is_admin", return_value=True):
            for name, replacement in patches.items():
                with mock.patch.object(tunnel_windows, name, replacement):
                    self.assertEqual(tunnel_windows.run_local(name[1:], {"k": 1})["operation"], name[1:])
        self.assertEqual([entry[0] for entry in calls], ["up", "down", "repair"])

    def test_unknown_operation_is_rejected(self):
        with mock.patch.object(system, "is_admin", return_value=True):
            with self.assertRaises(TunnelError):
                tunnel_windows.run_local("delete-everything")

    def test_unprivileged_run_local_refuses(self):
        with mock.patch.object(system, "is_admin", return_value=False):
            with self.assertRaises(TunnelError) as caught:
                tunnel_windows.run_local("up", SETTINGS)
        self.assertIn("Administrator", str(caught.exception))


class TransportTests(unittest.TestCase):
    def launcher(self, reply, code=0):
        seen = {}

        def fake(args, timeout=0):
            seen["args"] = args
            with open(args[2]) as handle:
                seen["request"] = json.load(handle)
            seen["workdir"] = os.path.dirname(args[2])
            if reply is not None:
                with open(args[3], "w") as handle:
                    json.dump(reply, handle)
            return code

        fake.seen = seen
        return fake

    def test_result_round_trips_through_the_elevated_child(self):
        reply = {"ok": True, "result": {"up": True, "interface": "protonx"}}
        fake = self.launcher(reply)
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(elevate, "_launch", fake):
            self.assertEqual(elevate.run("up", SETTINGS), reply["result"])
        self.assertEqual(fake.seen["request"], {"operation": "up", "payload": SETTINGS})
        self.assertEqual(fake.seen["args"][1], elevate.CHILD)

    def test_child_error_becomes_a_tunnel_error(self):
        fake = self.launcher({"ok": False, "error": "wg-quick up failed: no such device"})
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(elevate, "_launch", fake):
            with self.assertRaises(TunnelError) as caught:
                elevate.run("up", SETTINGS)
        self.assertIn("no such device", str(caught.exception))

    def test_missing_reply_names_the_exit_code(self):
        fake = self.launcher(None, code=7)
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(elevate, "_launch", fake):
            with self.assertRaises(TunnelError) as caught:
                elevate.run("up", SETTINGS)
        self.assertIn("7", str(caught.exception))

    def test_work_files_are_removed_even_on_failure(self):
        fake = self.launcher({"ok": False, "error": "nope"})
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(elevate, "_launch", fake):
            with self.assertRaises(TunnelError):
                elevate.run("up", SETTINGS)
        self.assertFalse(os.path.exists(fake.seen["workdir"]))

    def test_declining_the_prompt_is_reported_clearly(self):
        self.assertEqual(elevate._start_error(1223), elevate.DECLINED)
        self.assertIn("Administrator", elevate._start_error(5))
        self.assertIn("error 5", elevate._start_error(5))


class ElevatedChildProcessTests(unittest.TestCase):
    def run_child(self, request):
        workdir = tempfile.mkdtemp()
        request_path = os.path.join(workdir, "request.json")
        reply_path = os.path.join(workdir, "reply.json")
        with open(request_path, "w") as handle:
            json.dump(request, handle)
        result = subprocess.run(
            [sys.executable, elevate.CHILD, request_path, reply_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = None
        if os.path.exists(reply_path):
            with open(reply_path) as handle:
                payload = json.load(handle)
        return result, payload

    def test_child_always_writes_a_reply(self):
        result, payload = self.run_child({"operation": "up", "payload": SETTINGS})
        self.assertEqual(result.returncode, 1)
        self.assertIsNotNone(payload, "the elevated child has to answer the parent")
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["error"])

    def test_child_reports_an_unknown_operation(self):
        result, payload = self.run_child({"operation": "nonsense", "payload": None})
        self.assertEqual(result.returncode, 1)
        self.assertIn("nonsense", payload["error"])


class ElevationAvailabilityTests(unittest.TestCase):
    def test_available_only_on_windows(self):
        with mock.patch.object(system, "IS_WINDOWS", False):
            self.assertFalse(elevate.available())

    def test_doctor_reports_the_prompt_instead_of_failing(self):
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(
            system, "is_admin", return_value=False
        ), mock.patch.object(elevate, "available", return_value=True):
            name, value, ok = service._tunnel_check()
        self.assertEqual(name, "admin")
        self.assertTrue(ok)
        self.assertIn("permission", value)

    def test_doctor_fails_when_the_elevation_helper_is_missing(self):
        with mock.patch.object(system, "IS_WINDOWS", True), mock.patch.object(
            system, "is_admin", return_value=False
        ), mock.patch.object(elevate, "available", return_value=False):
            _, value, ok = service._tunnel_check()
        self.assertFalse(ok)
        self.assertIn("reinstall", value)


if __name__ == "__main__":
    unittest.main()
