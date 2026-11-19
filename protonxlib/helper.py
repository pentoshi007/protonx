import json
import os
import socket

from .errors import TunnelError

SOCKET_PATH = "/var/run/protonx/helper.sock"
READ_LIMIT = 65536


def available():
    return os.path.exists(SOCKET_PATH)


def call(request, timeout=45):
    if not available():
        raise TunnelError(
            "protonx helper is not installed; run 'sudo ./install.sh' from the protonx folder"
        )
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


def up(config):
    return call({"command": "up", "config": config})


def down():
    return call({"command": "down"})
