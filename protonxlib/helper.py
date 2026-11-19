import errno
import grp
import json
import os
import pwd
import socket
import time

from . import system
from .errors import TunnelError

SOCKET_PATH = "/var/run/protonx/helper.sock"
READ_LIMIT = 65536
CONTROL_GROUP = "protonx"
ATTEMPTS = 2
RETRY_DELAY = 0.5
# A peer that closes with unread bytes queued makes the kernel answer with a
# reset instead of a clean shutdown, so these can be a one-off race in a
# well-behaved helper and are worth one retry.
TRANSIENT = {errno.ECONNRESET, errno.EPIPE, errno.ECONNABORTED}
PERMISSION_HINT = (
    "the protonx helper refused this user. On Linux, add yourself to the 'protonx' group "
    "(sudo usermod -aG protonx $USER, then log out and back in); on macOS, use an administrator account."
)


class _Dropped(Exception):
    """The helper closed the connection without leaving a usable reply."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def available():
    return os.path.exists(SOCKET_PATH)


def group_problem():
    """Return a short reason this user cannot control the helper, or None."""
    if not system.IS_LINUX or os.geteuid() == 0:
        return None
    try:
        group = grp.getgrnam(CONTROL_GROUP)
    except KeyError:
        return "the protonx group is missing, so reinstall protonx"
    try:
        user = pwd.getpwuid(os.geteuid()).pw_name
        groups = os.getgrouplist(user, os.getegid())
    except (KeyError, OSError):
        return None
    if group.gr_gid in groups:
        return None
    return "user %s is not in the protonx group" % user


def permission_hint():
    problem = group_problem()
    if not problem:
        return None
    return "%s. Run 'sudo usermod -aG protonx $USER', then log out and back in (or run 'newgrp protonx')" % problem


def restart_hint():
    if system.IS_LINUX:
        return "Restart it with: sudo systemctl restart protonx-helper (details: journalctl -u protonx-helper)"
    if system.IS_MAC:
        return "Re-run the ProtonX installer to restore the helper."
    return "Reinstall protonx."


def call(request, timeout=45):
    if not available():
        raise TunnelError("the protonx helper is not running. " + restart_hint())
    payload = json.dumps(request).encode() + b"\n"
    failure = None
    for attempt in range(ATTEMPTS):
        try:
            return _reply(_exchange(payload, timeout))
        except _Dropped as dropped:
            failure = dropped
            if attempt + 1 < ATTEMPTS and dropped.code in TRANSIENT:
                time.sleep(RETRY_DELAY)
                continue
            break
    raise TunnelError(_dropped_message(failure)) from failure


def _exchange(payload, timeout):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(SOCKET_PATH)
        connection.sendall(payload)
        return _read(connection)
    except socket.timeout as error:
        raise _Dropped("the helper did not answer within %d seconds" % timeout) from error
    except OSError as error:
        raise _Dropped(str(error), error.errno) from error
    finally:
        connection.close()


def _read(connection):
    payload = b""
    while not payload.endswith(b"\n"):
        chunk = connection.recv(READ_LIMIT)
        if not chunk:
            break
        payload += chunk
    if not payload:
        raise _Dropped("the helper closed the connection without a reply")
    try:
        return json.loads(payload.decode())
    except ValueError as error:
        raise _Dropped("the helper sent an unreadable reply: %s" % error) from error


def _reply(reply):
    if reply.get("error") == "permission denied":
        raise TunnelError(PERMISSION_HINT)
    if not reply.get("ok"):
        raise TunnelError(reply.get("error") or "helper rejected the request")
    return reply


def _dropped_message(failure):
    if failure.code == errno.ECONNREFUSED:
        return "the protonx helper is not listening. " + restart_hint()
    hint = permission_hint() or restart_hint()
    return "the protonx helper dropped the connection (%s). %s" % (failure, hint)


def status():
    return call({"command": "status"})


def up(config, meta=None):
    request = {"command": "up", "config": config}
    if meta:
        request["meta"] = meta
    try:
        return call(request)
    except TunnelError:
        # The tunnel may be up even though the answer never arrived.
        report = settled()
        if report and report.get("up") and _same_server(report, meta):
            return report
        raise


def _same_server(report, meta):
    if not meta:
        return True
    active = (report.get("server") or {}).get("server")
    return active in (None, meta.get("server"))


def settled(timeout=20):
    """Ask for the real tunnel state now, or None when the helper cannot answer."""
    try:
        return call({"command": "status"}, timeout=timeout)
    except TunnelError:
        return None


def down():
    return call({"command": "down"})


def repair():
    return call({"command": "repair"}, timeout=60)
