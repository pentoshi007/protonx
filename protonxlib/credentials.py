import json
import os
import tempfile

from . import keychain, system
from .errors import SessionMissing


def _directory():
    return os.path.join(system.config_dir(), "secrets")


def _path(service, account):
    return os.path.join(_directory(), "%s-%s.json" % (service, account))


def read_json(service, account):
    if system.IS_MAC:
        return keychain.read_json(service, account)
    try:
        with open(_path(service, account)) as handle:
            return json.load(handle)
    except FileNotFoundError as error:
        raise SessionMissing("no stored item '%s' for '%s'" % (account, service)) from error
    except (OSError, ValueError) as error:
        raise SessionMissing("stored item '%s' is unreadable: %s" % (account, error)) from error


def write_json(service, account, payload):
    if system.IS_MAC:
        return keychain.write_json(service, account, payload)
    directory = _directory()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, _path(service, account))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def delete(service, account):
    if system.IS_MAC:
        return keychain.delete(service, account)
    try:
        os.unlink(_path(service, account))
    except FileNotFoundError:
        pass


def exists(service, account):
    try:
        read_json(service, account)
        return True
    except SessionMissing:
        return False
