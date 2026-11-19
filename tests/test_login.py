import base64
import unittest
from unittest import mock

from protonxlib import login, srp
from protonxlib.errors import ProtonxError, SessionMissing

PROOFS = srp.Proofs(b"\x11" * 256, b"client-proof", b"server-proof", b"shared-secret")
SIGNED = "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nAAAA\n-----BEGIN PGP SIGNATURE-----\nsig\n-----END PGP SIGNATURE-----"


class MemoryKeychain:
    def __init__(self):
        self.items = {}

    def write_json(self, service, account, payload):
        self.items[(service, account)] = dict(payload)

    def read_json(self, service, account):
        try:
            return dict(self.items[(service, account)])
        except KeyError as error:
            raise SessionMissing(f"missing {account}") from error

    def delete(self, service, account):
        self.items.pop((service, account), None)


def _carrier():
    return {"Code": 1000, "UID": "anon-uid", "AccessToken": "anon-token"}


def _info():
    return {
        "Version": 4,
        "Salt": base64.b64encode(b"\x02" * 16).decode(),
        "Modulus": SIGNED,
        "ServerEphemeral": base64.b64encode(b"\x03" * 256).decode(),
        "SRPSession": "srp-session-id",
    }


def _result(two_factor=False, proof=None):
    return {
        "UID": "user-uid",
        "AccessToken": "access-token",
        "RefreshToken": "refresh-token",
        "Scope": "full vpn self",
        "ServerProof": base64.b64encode(proof or PROOFS.expected_server_proof).decode(),
        "TwoFactor": {"Enabled": 1 if two_factor else 0},
    }


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryKeychain()
        self.patches = [
            mock.patch.object(login.keychain, "write_json", self.store.write_json),
            mock.patch.object(login.keychain, "read_json", self.store.read_json),
            mock.patch.object(login.keychain, "delete", self.store.delete),
            mock.patch.object(login.srp, "cleartext_modulus", return_value=b"\x04" * 256),
            mock.patch.object(login.srp, "generate_proofs", return_value=PROOFS),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(lambda: [patcher.stop() for patcher in self.patches])

    def test_sign_in_stores_a_working_session(self):
        with mock.patch.object(login.api, "auth_post", side_effect=[_carrier(), _info(), _result()]) as call:
            outcome = login.sign_in("someone", "secret")

        self.assertEqual(outcome["status"], "signed-in")
        stored = login.current()
        self.assertEqual(stored["userId"], "user-uid")
        self.assertEqual(stored["accessToken"], "access-token")
        self.assertEqual(stored["scopes"], ["full", "vpn", "self"])
        self.assertEqual(stored["username"], "someone")

        auth_body = call.call_args_list[2].args[1]
        self.assertEqual(auth_body["SRPSession"], "srp-session-id")
        self.assertEqual(auth_body["ClientProof"], base64.b64encode(PROOFS.client_proof).decode())
        self.assertEqual(auth_body["Payload"], {})

    def test_two_factor_is_deferred_until_a_code_arrives(self):
        with mock.patch.object(login.api, "auth_post", side_effect=[_carrier(), _info(), _result(two_factor=True)]):
            outcome = login.sign_in("someone", "secret")

        self.assertEqual(outcome["status"], "two-factor")
        self.assertIsNone(login.current())
        self.assertIsNotNone(login.pending())

        with mock.patch.object(login.api, "auth_post", return_value={"Scope": "full vpn"}):
            finished = login.finish_two_factor("123456")

        self.assertEqual(finished["status"], "signed-in")
        self.assertEqual(login.current()["accessToken"], "access-token")
        self.assertIsNone(login.pending())

    def test_sign_in_with_inline_code_skips_pending(self):
        with mock.patch.object(
            login.api, "auth_post", side_effect=[_carrier(), _info(), _result(two_factor=True), {"Scope": "full vpn"}]
        ):
            outcome = login.sign_in("someone", "secret", code="654321")

        self.assertEqual(outcome["status"], "signed-in")
        self.assertIsNone(login.pending())

    def test_impostor_server_proof_is_refused(self):
        with mock.patch.object(login.api, "auth_post", side_effect=[_carrier(), _info(), _result(proof=b"wrong")]):
            with self.assertRaises(ProtonxError):
                login.sign_in("someone", "secret")
        self.assertIsNone(login.current())

    def test_sign_out_forgets_everything(self):
        with mock.patch.object(login.api, "auth_post", side_effect=[_carrier(), _info(), _result()]):
            login.sign_in("someone", "secret")
        with mock.patch.object(login.api, "auth_post", return_value={}) as call:
            login.sign_out()
        self.assertEqual(call.call_args.kwargs["method"], "DELETE")
        self.assertIsNone(login.current())

    def test_sign_out_clears_local_session_even_without_network(self):
        login.store({"accessToken": "fixture"})
        with mock.patch.object(login.api, "auth_post", side_effect=TimeoutError):
            login.sign_out()
        self.assertIsNone(login.current())
        self.assertIsNone(login.pending())

    def test_failed_keychain_delete_does_not_report_logout(self):
        login.store({"accessToken": "fixture"})
        with mock.patch.object(login.keychain, "delete"), mock.patch.object(login.api, "auth_post") as revoke:
            with self.assertRaisesRegex(ProtonxError, "Could not remove"):
                login.sign_out()
        revoke.assert_not_called()
        self.assertIsNotNone(login.current())

    def test_finish_without_pending_is_an_error(self):
        with self.assertRaises(SessionMissing):
            login.finish_two_factor("123456")


if __name__ == "__main__":
    unittest.main()
