import base64
import hashlib
import os
from typing import NamedTuple

import bcrypt

from .errors import ProtonxError

BYTE_LENGTH = 256
MODULUS_BITS = BYTE_LENGTH * 8
GENERATOR = 2
MIN_SECRET = 512

STANDARD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
BCRYPT_B64 = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
SIGNATURE_MARKER = "-----BEGIN PGP SIGNATURE-----"


class SrpError(ProtonxError):
    pass


class Proofs(NamedTuple):
    client_ephemeral: bytes
    client_proof: bytes
    expected_server_proof: bytes
    shared_secret: bytes


def expand_hash(data):
    return b"".join(hashlib.sha512(data + bytes([index])).digest() for index in range(4))


def bcrypt_encode(raw):
    encoded = base64.b64encode(raw).decode().rstrip("=")
    return "".join(BCRYPT_B64[STANDARD_B64.index(char)] for char in encoded)


def hash_password(password, salt, modulus):
    salt_string = bcrypt_encode(salt + b"proton")
    digest = bcrypt.hashpw(password.encode("utf-8"), f"$2y$10${salt_string}".encode())
    return expand_hash(digest + modulus)


def cleartext_modulus(signed_message):
    lines = signed_message.strip().splitlines()
    try:
        start = lines.index("Hash: SHA256") + 2
        end = lines.index(SIGNATURE_MARKER)
    except ValueError as error:
        raise SrpError("server modulus is not a clear-signed OpenPGP message") from error
    body = "".join(lines[start:end]).strip()
    if not body:
        raise SrpError("server modulus is empty")
    return base64.b64decode(body)


def _le_bytes(value):
    return value.to_bytes(BYTE_LENGTH, "little")


def _le_int(data):
    return int.from_bytes(data, "little")


def _multiplier(modulus):
    return _le_int(expand_hash(_le_bytes(GENERATOR) + _le_bytes(modulus))) % modulus


def _validate(modulus, server_ephemeral):
    if modulus.bit_length() != MODULUS_BITS:
        raise SrpError(f"server modulus is {modulus.bit_length()} bits, expected {MODULUS_BITS}")
    if not 1 < server_ephemeral < modulus - 1:
        raise SrpError("server ephemeral is out of range")


def _random_secret(modulus):
    while True:
        candidate = _le_int(os.urandom(BYTE_LENGTH))
        if MIN_SECRET < candidate < modulus - 1:
            return candidate


def generate_proofs(password, salt, modulus, server_ephemeral, secret=None):
    modulus_int = _le_int(modulus)
    server_int = _le_int(server_ephemeral)
    _validate(modulus_int, server_int)

    hashed = _le_int(hash_password(password, salt, modulus))
    secret_int = _random_secret(modulus_int) if secret is None else secret
    ephemeral = _le_bytes(pow(GENERATOR, secret_int, modulus_int))

    scramble = _le_int(expand_hash(ephemeral + server_ephemeral))
    base = (server_int - _multiplier(modulus_int) * pow(GENERATOR, hashed, modulus_int)) % modulus_int
    exponent = (scramble * hashed + secret_int) % (modulus_int - 1)
    shared = _le_bytes(pow(base, exponent, modulus_int))

    client_proof = expand_hash(ephemeral + server_ephemeral + shared)
    server_proof = expand_hash(ephemeral + client_proof + shared)
    return Proofs(ephemeral, client_proof, server_proof, shared)
