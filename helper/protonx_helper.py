import ipaddress
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from helper_common import HelperError, run, tool, write_private, write_public
from protonxlib import system as host
from protonxlib import wgconf

if sys.platform == "darwin":
    import helper_macos as system
elif sys.platform.startswith("linux"):
    import helper_linux as system
else:
    raise SystemExit("the protonx helper runs on macOS and Linux only")

SOCKET_DIR = "/var/run/protonx"
SOCKET_PATH = os.path.join(SOCKET_DIR, "helper.sock")
CONFIG_PATH = os.path.join(host.state_dir(), "protonx.conf")
TUNNEL_LOCK = threading.Lock()
MAX_MESSAGE = 16384
INTERFACE_EXIT_TIMEOUT = 2
START_ATTEMPTS = 2
RETRY_DELAY = 0.6
META_FIELDS = ("country", "server", "label", "city", "endpoint")


def _state_dir():
    return os.path.dirname(CONFIG_PATH)


def _tunnel_path():
    return os.path.join(_state_dir(), "tunnel.json")


def _read_tunnel():
    try:
        with open(_tunnel_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_tunnel(payload):
    os.makedirs(_state_dir(), mode=0o755, exist_ok=True)
    write_public(_tunnel_path(), json.dumps(payload))


def _clear_tunnel():
    try:
        os.unlink(_tunnel_path())
    except FileNotFoundError:
        pass


def _clean_meta(meta):
    if not isinstance(meta, dict):
        return None
    clean = {}
    for key in META_FIELDS:
        value = meta.get(key)
        if isinstance(value, str) and value and len(value) <= 200:
            clean[key] = value
    stamp = meta.get("connected_at")
    if isinstance(stamp, int) and not isinstance(stamp, bool):
        clean["connected_at"] = stamp
    return clean or None


def validate(config):
    try:
        return wgconf.validate(config)
    except wgconf.ConfigError as error:
        raise HelperError(str(error)) from error


def render(config):
    return wgconf.render(validate(config))


def _dns_report(up):
    reporter = getattr(system, "dns_report", None)
    if reporter is None:
        return {"stale": False, "servers": [], "service": None}
    return reporter(up)


def status():
    name = system.interface_name()
    if name and not system.interface_exists(name):
        name = None
    dump = wgconf.parse_dump(run([tool("wg"), "show", "all", "dump"], check=False).stdout)
    up = bool(name) and name in dump
    record = _read_tunnel() if up else None
    return {
        "ok": True,
        "up": up,
        "interface": name if up else None,
        "address": system.interface_address(name) if up else None,
        "peers": dump.get(name, []) if up else [],
        "config": os.path.exists(CONFIG_PATH),
        "bypass_source": system.current_bypass() if up else None,
        "server": record.get("server") if record else None,
        "dns": _dns_report(up),
    }


def _resolve_ipv4(hostname, port):
    try:
        return str(ipaddress.IPv4Address(hostname))
    except ValueError:
        pass
    try:
        return socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
    except socket.gaierror as error:
        raise HelperError("could not resolve %s: %s" % (hostname, error)) from error


def _wait_for_interface_exit(name):
    deadline = time.monotonic() + INTERFACE_EXIT_TIMEOUT
    while system.interface_exists(name):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _stop_tunnel():
    warnings = []
    name = system.interface_name()
    if os.path.exists(CONFIG_PATH):
        result = run([tool("wg-quick"), "down", CONFIG_PATH], check=False)
        if result.returncode != 0:
            warnings.append("wg-quick down reported: %s" % (result.stderr or result.stdout).strip())
    if name:
        try:
            system.remove_interface(name)
        except OSError as error:
            warnings.append("could not remove %s: %s" % (name, error))
        if not _wait_for_interface_exit(name):
            warnings.append("the previous tunnel did not stop (%s)" % name)
            try:
                system.remove_interface(name)
            except OSError:
                pass
    clear_name = getattr(system, "clear_interface_name", None)
    if clear_name is not None:
        clear_name()
    system.remove_bypass()
    try:
        system.restore_dns()
    except (HelperError, OSError) as error:
        warnings.append("DNS restore failed: %s" % error)
    if os.path.exists(CONFIG_PATH):
        os.unlink(CONFIG_PATH)
    _clear_tunnel()
    return warnings


def _previous_tunnel():
    if not system.interface_name() or not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH) as handle:
        text = handle.read()
    record = _read_tunnel() or {}
    return {
        "text": text,
        "dns": system.applied_dns(),
        "bypass": system.current_bypass(),
        "meta": record.get("server"),
    }


def _start_tunnel(text, dns, bypass, meta):
    os.makedirs(_state_dir(), mode=0o755, exist_ok=True)
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
    _write_tunnel(
        {
            "interface": report.get("interface"),
            "address": report.get("address"),
            "dns": dns,
            "server": meta,
            "started_at": int(time.time()),
        }
    )
    report["server"] = meta
    report["dns"] = _dns_report(True)
    return report



def down():
    warnings = _stop_tunnel()
    report = status()
    report["warnings"] = warnings
    return report


def up(config, meta=None):
    fields = validate(config)
    system.check_bypass(fields["bypass_source"])
    fields["endpoint_host"] = _resolve_ipv4(fields["endpoint_host"], fields["endpoint_port"])
    meta = _clean_meta(meta)
    previous = _previous_tunnel()
    _stop_tunnel()
    last_error = None
    for attempt in range(START_ATTEMPTS):
        try:
            report = _start_tunnel(wgconf.render(fields), fields["dns"], fields["bypass_source"], meta)
            if attempt:
                report["retried"] = True
            return report
        except (HelperError, OSError) as error:
            last_error = error
            _stop_tunnel()
            if attempt + 1 < START_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    if previous is not None:
        try:
            _start_tunnel(previous["text"], previous["dns"], previous["bypass"], previous.get("meta"))
        except (HelperError, OSError) as recovery_error:
            _stop_tunnel()
            raise HelperError("%s. Recovery failed: %s" % (last_error, recovery_error)) from last_error
        raise HelperError("%s (previous tunnel restored)" % last_error) from last_error
    raise HelperError("%s. The system was restored to its normal network settings." % last_error) from last_error


def repair():
    actions = []
    actions.extend(_stop_tunnel())
    flush = getattr(system, "flush_dns", None)
    if flush is not None:
        flush()
        actions.append("flushed the DNS cache")
    system.restore_dns()
    actions.append("restored the system DNS settings")
    report = status()
    report["actions"] = actions
    resolves = getattr(system, "resolves", None)
    internet = getattr(system, "internet", None)
    report["resolves"] = resolves("apple.com") if resolves is not None else True
    report["internet"] = internet() if internet is not None else True
    return report


def _reconcile():
    name = system.interface_name()
    if name and not system.interface_exists(name):
        clear_name = getattr(system, "clear_interface_name", None)
        if clear_name is not None:
            clear_name()
        name = None
    if name:
        dump = wgconf.parse_dump(run([tool("wg"), "show", "all", "dump"], check=False).stdout)
        if name not in dump:
            clear_name = getattr(system, "clear_interface_name", None)
            if clear_name is not None:
                clear_name()
            name = None
    if not name:
        system.remove_bypass()
        system.restore_dns()
        _clear_tunnel()


def dispatch(request):
    command = request.get("command")
    if command == "render":
        return {"ok": True, "config": render(request.get("config"))}
    with TUNNEL_LOCK:
        if command == "status":
            return status()
        if command == "up":
            return up(request.get("config"), request.get("meta"))
        if command == "down":
            return down()
        if command == "repair":
            return repair()
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
    _reconcile()
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
