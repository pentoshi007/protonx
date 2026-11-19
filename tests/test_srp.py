import base64
import json
import os
import unittest

from protonxlib import srp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "tests", "srp_vector.json")) as handle:
    VECTOR = json.load(handle)


def _modulus():
    return base64.b64decode(VECTOR["modulus_b64"])


class SrpTest(unittest.TestCase):
    def test_reproduces_go_verified_proofs(self):
        self.assertTrue(VECTOR["go_verified"], "fixture must be produced by a go-srp server accepting our proof")
        proofs = srp.generate_proofs(
            VECTOR["password"],
            base64.b64decode(VECTOR["salt"]),
            _modulus(),
            base64.b64decode(VECTOR["server_ephemeral"]),
            secret=int.from_bytes(bytes.fromhex(VECTOR["client_secret"]), "little"),
        )
        self.assertEqual(base64.b64encode(proofs.client_ephemeral).decode(), VECTOR["client_ephemeral"])
        self.assertEqual(base64.b64encode(proofs.client_proof).decode(), VECTOR["client_proof"])
        self.assertEqual(
            base64.b64encode(proofs.expected_server_proof).decode(), VECTOR["expected_server_proof"]
        )

    def test_bcrypt_salt_encoding_matches_bcrypt_alphabet(self):
        encoded = srp.bcrypt_encode(bytes(range(16)))
        self.assertEqual(len(encoded), 22)
        self.assertTrue(set(encoded) <= set(srp.BCRYPT_B64))
        self.assertIn(encoded[-1], "Oeu.")

    def test_cleartext_modulus_unwraps_signed_message(self):
        modulus = srp.cleartext_modulus(VECTOR["modulus_signed"])
        self.assertEqual(base64.b64encode(modulus).decode(), VECTOR["modulus_b64"])

    def test_cleartext_modulus_rejects_unsigned_input(self):
        with self.assertRaises(srp.SrpError):
            srp.cleartext_modulus("bm90IGEgc2lnbmVkIG1vZHVsdXM=")

    def test_rejects_out_of_range_server_ephemeral(self):
        with self.assertRaises(srp.SrpError):
            srp.generate_proofs("a", b"\0" * 16, _modulus(), b"\x01\x00")

    def test_rejects_wrong_modulus_size(self):
        with self.assertRaises(srp.SrpError):
            srp.generate_proofs("a", b"\0" * 16, b"\x01" * 32, b"\x05" * 256)


if __name__ == "__main__":
    unittest.main()
