import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch
from urllib.error import URLError

from protonxlib import api, cli, identity, service
from protonxlib.errors import NO_TRAFFIC, ApiError, SessionExpired, SessionMissing, TunnelError
from protonxlib.logicals import parse
from tests.test_cli import FIXTURE


def fingerprint_conflict():
    return ApiError(409, 2500, "ClientPublicKey fingerprint conflict, please regenerate a new key")


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.pool = parse(FIXTURE)
        self.target = self.pool[0]
        self.keys = identity.derive(bytes(32))
        self.replacement = identity.derive(bytes(range(32)))
        self.client = Mock(spec=api.Client)
        self.create = self.enterContext(patch.object(identity, "create", return_value=self.replacement))
        self.save = self.enterContext(patch.object(identity, "save", side_effect=lambda keys: keys))
        self.enterContext(patch.object(identity, "load_or_create", return_value=self.keys))
        self.up = self.enterContext(patch.object(service.wireguard, "up", return_value={"up": True}))
        self.save_target = self.enterContext(patch.object(service.state, "save"))

    def test_app_cached_connect_still_registers_the_saved_key(self):
        session = {"userId": "test-session"}
        self.enterContext(patch.object(service.auth, "load_session", return_value=session))
        make_client = self.enterContext(patch.object(service.auth, "make_client", return_value=self.client))
        self.enterContext(patch.object(service.catalog, "cached", return_value=(self.pool, 1)))
        fetch = self.enterContext(patch.object(service.catalog, "live"))
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = cli.main(["connect", "--offline", "--country", "NL", "--server", self.target.name, "--json"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue())["registration"], "registered")
        make_client.assert_called_once_with(session, persist=True)
        fetch.assert_not_called()
        self.client.register_key.assert_called_once_with(self.keys.ed25519_pub_b64)
        self.assertEqual(self.up.call_args.args[0]["private_key"], self.keys.x25519_priv_b64)
        self.create.assert_not_called()

    def test_conflicting_key_is_replaced_only_after_proton_accepts_it(self):
        def register(public_key):
            self.up.assert_not_called()
            self.save.assert_not_called()
            if public_key == self.keys.ed25519_pub_b64:
                raise fingerprint_conflict()

        self.client.register_key.side_effect = register
        report = service.connect(self.target, self.client, service.ConnectOptions())
        self.assertEqual(self.client.register_key.call_args_list, [
            call(self.keys.ed25519_pub_b64), call(self.replacement.ed25519_pub_b64),
        ])
        self.create.assert_called_once_with()
        self.save.assert_called_once_with(self.replacement)
        self.up.assert_called_once()
        self.assertEqual(self.up.call_args.args[0]["private_key"], self.replacement.x25519_priv_b64)
        self.assertEqual(report["identity"], self.replacement.x25519_pub_b64[:16])
        self.assertEqual(report["registration"], "registered")

    def test_second_conflict_leaves_identity_and_tunnel_untouched(self):
        self.client.register_key.side_effect = [fingerprint_conflict(), fingerprint_conflict()]
        with self.assertRaisesRegex(ApiError, "fingerprint conflict"):
            service.connect(self.target, self.client, service.ConnectOptions())
        self.assertEqual(self.client.register_key.call_count, 2)
        self.create.assert_called_once_with()
        self.save.assert_not_called()
        self.up.assert_not_called()
        self.save_target.assert_not_called()

    def test_other_registration_errors_stop_without_rotating_the_key(self):
        errors = (ApiError(409, 2501, "other conflict"), SessionExpired("expired"), URLError("offline"))
        for error in errors:
            with self.subTest(error=error):
                self.client.register_key.reset_mock()
                for operation in (self.create, self.save, self.up, self.save_target):
                    operation.reset_mock()
                self.client.register_key.side_effect = error
                with self.assertRaises(type(error)) as raised:
                    service.connect(self.target, self.client, service.ConnectOptions())
                self.assertIs(raised.exception, error)
                self.client.register_key.assert_called_once_with(self.keys.ed25519_pub_b64)
                self.create.assert_not_called()
                self.save.assert_not_called()
                self.up.assert_not_called()
                self.save_target.assert_not_called()

    def test_cached_connect_requires_sign_in_but_cached_preview_does_not(self):
        load_session = self.enterContext(patch.object(service.auth, "load_session", side_effect=SessionMissing("Sign in")))
        self.enterContext(patch.object(service.catalog, "cached", return_value=(self.pool, 1)))
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = ["connect", "--offline", "--country", "NL", "--json"]
            self.assertEqual(cli.main(args + ["--dry-run"]), 0)
            load_session.assert_not_called()
            self.assertEqual(cli.main(args), 2)
        self.assertTrue(json.loads(stdout.getvalue())["dry_run"])
        self.assertEqual(json.loads(stderr.getvalue())["kind"], "session")
        self.up.assert_not_called()
        self.save_target.assert_not_called()

    def test_service_refuses_a_real_connection_without_a_client(self):
        with self.assertRaises(SessionMissing):
            service.connect(self.target, None, service.ConnectOptions())
        self.up.assert_not_called()

    def test_a_dead_tunnel_rotates_the_key_and_connects_again(self):
        dead = TunnelError(NO_TRAFFIC + " (api.proton.me:443 failed: timed out)")
        self.up.side_effect = [dead, {"up": True, "interface": "utun9", "address": "10.2.0.2"}]
        report = service.connect(self.target, self.client, service.ConnectOptions())
        self.assertEqual(self.client.register_key.call_args_list, [
            call(self.keys.ed25519_pub_b64), call(self.replacement.ed25519_pub_b64),
        ])
        self.assertEqual(self.up.call_args.args[0]["private_key"], self.replacement.x25519_priv_b64)
        self.assertEqual(report["identity"], self.replacement.x25519_pub_b64[:16])
        self.assertEqual(report["interface"], "utun9")
        self.assertEqual(self.save_target.call_count, 1)

    def test_a_dead_tunnel_after_rotation_is_reported_not_saved(self):
        self.up.side_effect = TunnelError(NO_TRAFFIC + " (api.proton.me:443 failed: timed out)")
        with self.assertRaisesRegex(TunnelError, "not carrying traffic"):
            service.connect(self.target, self.client, service.ConnectOptions())
        self.assertEqual(self.up.call_count, 2)
        self.save_target.assert_not_called()


class IdentityReplacementTests(unittest.TestCase):
    def test_failed_replacement_keeps_the_previous_private_identity(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            with patch.object(identity, "IDENTITY_PATH", str(path)), patch.object(identity.cache, "CONFIG_DIR", directory):
                original = identity.derive(bytes(32))
                identity.save(original)
                with patch.object(identity.os, "replace", side_effect=OSError("replace failed")):
                    with self.assertRaisesRegex(OSError, "replace failed"):
                        identity.save(identity.derive(bytes(range(32))))
                self.assertEqual(identity.load().x25519_pub_b64, original.x25519_pub_b64)
                self.assertEqual(list(path.parent.iterdir()), [path])
