import ipaddress
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from helper_common import HelperError, run, tool, write_private
from protonxlib import wgconf

if sys.platform == "darwin":
    import helper_macos as system
elif sys.platform.startswith("linux"):
    import helper_linux as system
else:
    raise SystemExit("the protonx helper runs on macOS and Linux only")

SOCKET_DIR = "/var/run/protonx"
SOCKET_PATH = os.path.join(SOCKET_DIR, "helper.sock")
CONFIG_PATH = os.path.join(SOCKET_DIR, "protonx.conf")
TUNNEL_LOCK = threading.Lock()
MAX_MESSAGE = 16384
INTERFACE_EXIT_TIMEOUT = 2


def validate(config):
    try:
        return wgconf.validate(config)
    except wgconf.ConfigError as error:
        raise HelperError(str(error)) from error


def render(config):
    return wgconf.render(validate(config))


def status():
    dump = wgconf.parse_dump(run([tool("wg"), "show", "all", "dump"], check=False).stdout)
    name = system.interface_name()
    up = bool(name) and name in dump
    return {
        "ok": True,
        "up": up,
        "interface": name if up else None,
        "address": system.interface_address(name) if up else None,
        "peers": dump.get(name, []) if up else [],
        "config": os.path.exists(CONFIG_PATH),
        "bypass_source": system.current_bypass() if up else None,
    }


def _resolve_ipv4(host, port):
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    try:
        return socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
    except socket.gaierror as error:
        raise HelperError("could not resolve %s: %s" % (host, error)) from error


def _wait_for_interface_exit(name):
    deadline = time.monotonic() + INTERFACE_EXIT_TIMEOUT
    while system.interface_exists(name):
        if time.monotonic() >= deadline:
            raise HelperError("the previous tunnel did not stop (%s)" % name)
        time.sleep(0.05)


def _stop_tunnel():
    name = system.interface_name()
    if os.path.exists(CONFIG_PATH):
        run([tool("wg-quick"), "down", CONFIG_PATH], check=False)
    if name:
        system.remove_interface(name)
        _wait_for_interface_exit(name)
    system.remove_bypass()
    system.restore_dns()
    if os.path.exists(CONFIG_PATH):
        os.unlink(CONFIG_PATH)


def _previous_tunnel():
    if not system.interface_name() or not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH) as handle:
        text = handle.read()
    return {"text": text, "dns": system.applied_dns(), "bypass": system.current_bypass()}


def _start_tunnel(text, dns, bypass):
    os.makedirs(SOCKET_DIR, mode=0o700, exist_ok=True)
    write_private(CONFIG_PATH, text)
    system.add_bypass(bypass)
    result = run([tool("wg-quick"), "up", CONFIG_PATH], check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HelperError("wg-quick up failed: %s" % detail)
    report = status()
    if not report["up"]:
        raise HelperError("wg-quick reported success but no tunnel interface exists")
    system.apply_dns(dns)
    return report


def _recover_tunnel(previous):
    _stop_tunnel()
    if previous is None:
        return ""
    try:
        _start_tunnel(previous["text"], previous["dns"], previous["bypass"])
    except (HelperError, OSError):
        _stop_tunnel()
        raise
    return " (previous tunnel restored)"


def down():
    _stop_tunnel()
    return status()


def up(config):
    fields = validate(config)
    system.check_bypass(fields["bypass_source"])
    fields["endpoint_host"] = _resolve_ipv4(fields["endpoint_host"], fields["endpoint_port"])
    previous = _previous_tunnel()
    _stop_tunnel()
    try:
        return _start_tunnel(wgconf.render(fields), fields["dns"], fields["bypass_source"])
    except (HelperError, OSError) as error:
        try:
            recovery = _recover_tunnel(previous)
        except (HelperError, OSError) as recovery_error:
            raise HelperError("%s. Recovery failed: %s" % (error, recovery_error)) from error
        raise HelperError("%s%s" % (error, recovery)) from error


def dispatch(request):
    command = request.get("command")
    if command == "render":
        return {"ok": True, "config": render(request.get("config"))}
    with TUNNEL_LOCK:
        if command == "status":
            return status()
        if command == "up":
            return up(request.get("config"))
        if command == "down":
            return down()
    raise HelperError("unknown command: %s" % command)


def _reply(connection, payload):
    connection.sendall(json.dumps(payload).encode() + b"\n")


def _respond(connection):
    with connection:
        if not system.may_control(system.peer_uid(connection)):
            _reply(connection, {"ok": False, "error": "permission denied"})
            return
        payload = b""
        while not payload.endswith(b"\n") and len(payload) < MAX_MESSAGE:
            chunk = connection.recv(4096)
            if not chunk:
                break
            payload += chunk
        try:
            response = dispatch(json.loads(payload.decode("utf-8") or "{}"))
        except (ValueError, HelperError) as error:
            response = {"ok": False, "error": str(error)}
        except Exception as error:
            response = {"ok": False, "error": "unexpected failure: %s" % error}
        _reply(connection, response)


def serve():
    system.prepare_socket_dir(SOCKET_DIR)
    if not system.interface_name():
        system.remove_bypass()
        system.restore_dns()
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    system.protect_socket(SOCKET_PATH)
    server.listen(16)
    while True:
        connection, _ = server.accept()
        threading.Thread(target=_respond, args=(connection,), daemon=True).start()


if __name__ == "__main__":
    serve()
