import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from . import cache, credentials

SERVICE = "protonx"
ACCOUNT = "identity"
IDENTITY_PATH = os.path.join(cache.CONFIG_DIR, "identity.json")


class Identity:
    def __init__(self, seed_b64, ed25519_pub_b64, x25519_priv_b64, x25519_pub_b64):
        self.seed_b64 = seed_b64
        self.ed25519_pub_b64 = ed25519_pub_b64
        self.x25519_priv_b64 = x25519_priv_b64
        self.x25519_pub_b64 = x25519_pub_b64

    def as_dict(self):
        return {
            "seed": self.seed_b64,
            "ed25519PublicKey": self.ed25519_pub_b64,
            "x25519PrivateKey": self.x25519_priv_b64,
            "x25519PublicKey": self.x25519_pub_b64,
        }


def _b64(raw):
    return base64.b64encode(raw).decode()


def clamp(seed):
    digest = hashlib.sha512(seed).digest()[:32]
    scalar = bytearray(digest)
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    return bytes(scalar)


def derive(seed):
    ed_private = Ed25519PrivateKey.from_private_bytes(seed)
    ed_public = ed_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    x_private = X25519PrivateKey.from_private_bytes(clamp(seed))
    x_public = x_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return Identity(_b64(seed), _b64(ed_public), _b64(clamp(seed)), _b64(x_public))


def create():
    return derive(os.urandom(32))


def _from_dict(data):
    return Identity(
        data["seed"],
        data["ed25519PublicKey"],
        data["x25519PrivateKey"],
        data["x25519PublicKey"],
    )


def _migrate_from_keychain():
    try:
        return _from_dict(credentials.read_json(SERVICE, ACCOUNT))
    except Exception:
        return None


def load():
    with open(IDENTITY_PATH) as handle:
        return _from_dict(json.load(handle))


def load_or_create():
    try:
        return load()
    except (OSError, ValueError, KeyError):
        return save(_migrate_from_keychain() or create())


def save(identity):
    os.makedirs(cache.CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(IDENTITY_PATH, "w") as handle:
        json.dump(identity.as_dict(), handle, indent=2)
    os.chmod(IDENTITY_PATH, 0o600)
    return identity


def public_keys(identity):
    return {"ed25519": identity.ed25519_pub_b64, "x25519": identity.x25519_pub_b64}


def dump(identity):
    return json.dumps(identity.as_dict(), indent=2)
