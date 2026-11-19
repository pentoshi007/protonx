import json
import os
import socket

from .errors import TunnelError

SOCKET_PATH = "/var/run/protonx/helper.sock"
READ_LIMIT = 65536
PERMISSION_HINT = (
    "the protonx helper refused this user. On Linux, add yourself to the 'protonx' group "
    "(sudo usermod -aG protonx $USER); on macOS, use an administrator account."
)


def available():
    return os.path.exists(SOCKET_PATH)


def call(request, timeout=45):
    if not available():
        raise TunnelError("the protonx helper is not running; re-run the protonx installer")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(SOCKET_PATH)
        connection.sendall(json.dumps(request).encode() + b"\n")
        reply = _read(connection)
    except OSError as error:
        raise TunnelError("helper communication failed: %s" % error)
    finally:
        connection.close()
    if reply.get("error") == "permission denied":
        raise TunnelError(PERMISSION_HINT)
    if not reply.get("ok"):
        raise TunnelError(reply.get("error") or "helper rejected the request")
    return reply


def _read(connection):
    payload = b""
    while not payload.endswith(b"\n"):
        chunk = connection.recv(READ_LIMIT)
        if not chunk:
            break
        payload += chunk
    if not payload:
        raise TunnelError("helper closed the connection without a reply")
    try:
        return json.loads(payload.decode())
    except ValueError as error:
        raise TunnelError("helper sent an unreadable reply: %s" % error)


def status():
    return call({"command": "status"})


def up(config, meta=None):
    request = {"command": "up", "config": config}
    if meta:
        request["meta"] = meta
    return call(request)


def down():
    return call({"command": "down"})


def repair():
    return call({"command": "repair"}, timeout=60)
