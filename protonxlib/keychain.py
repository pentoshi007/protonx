import json
import subprocess

from .errors import SessionMissing

SECURITY = "/usr/bin/security"


def read(service, account):
    result = subprocess.run(
        [SECURITY, "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SessionMissing(
            f"no keychain item '{account}' in service '{service}': {result.stderr.strip()}"
        )
    return result.stdout.strip()


def read_json(service, account):
    raw = read(service, account)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SessionMissing(f"keychain item '{account}' is not valid JSON: {error}") from error


def write_json(service, account, payload):
    raw = json.dumps(payload, separators=(",", ":"))
    result = subprocess.run(
        [SECURITY, "add-generic-password", "-U", "-s", service, "-a", account, "-w", raw],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SessionMissing(f"cannot write keychain item '{account}': {result.stderr.strip()}")


def exists(service, account):
    try:
        read(service, account)
        return True
    except SessionMissing:
        return False


def delete(service, account):
    subprocess.run(
        [SECURITY, "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
        text=True,
    )
