import base64
import ipaddress
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

SOCKET_DIR = "/var/run/protonx"
SOCKET_PATH = os.path.join(SOCKET_DIR, "helper.sock")
CONFIG_PATH = os.path.join(SOCKET_DIR, "protonx.conf")
DNS_STATE_PATH = os.path.join(SOCKET_DIR, "dns.json")
NAME_PATH = "/var/run/wireguard/protonx.name"
NETWORKSETUP = "/usr/sbin/networksetup"
ROUTE = "/sbin/route"
TUNNEL_RESOLVERS = ("10.2.0.1", "10.200.")
TUNNEL_LOCK = threading.Lock()
ADMIN_GID = 80
MIN_MTU = 1280
MAX_MTU = 1500
MAX_MESSAGE = 16384
TOOL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REQUIRED_FIELDS = (
    "private_key",
    "address",
    "peer_public_key",
    "allowed_ips",
    "endpoint_host",
    "endpoint_port",
)
OPTIONAL_FIELDS = ("dns", "mtu", "keepalive")

HOST_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


class HelperError(Exception):
    pass


def _tool(name):
    found = shutil.which(name, path=TOOL_PATH)
    if not found:
        raise HelperError("%s is not installed" % name)
    return found


def _run(args, check=True):
    try:
        result = subprocess.run(args, capture_output=True, text=True, env={"PATH": TOOL_PATH}, timeout=12)
    except subprocess.TimeoutExpired as error:
        raise HelperError("%s timed out" % os.path.basename(args[0])) from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HelperError("%s failed: %s" % (args[0], detail))
    return result


def _key(value, field):
    if not isinstance(value, str) or len(value) != 44:
        raise HelperError("%s must be a 44 character base64 key" % field)
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise HelperError("%s is not valid base64: %s" % (field, error))
    if len(raw) != 32:
        raise HelperError("%s must decode to 32 bytes" % field)
    return value


def _cidr_list(value):
    if not isinstance(value, str):
        raise HelperError("allowed_ips must be a string")
    networks = [item.strip() for item in value.split(",") if item.strip()]
    if not networks:
        raise HelperError("allowed_ips must list at least one network")
    for item in networks:
        try:
            ipaddress.IPv4Network(item, strict=False)
        except ValueError:
            raise HelperError("allowed_ips contains an invalid network: %s" % item)
    return ", ".join(networks)


def _address(value):
    if not isinstance(value, str) or "/" not in value:
        raise HelperError("address must be an IPv4 address with a prefix length")
    try:
        ipaddress.IPv4Interface(value)
    except ValueError:
        raise HelperError("address is not a valid IPv4 interface: %s" % value)
    return value


def _dns(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise HelperError("dns must be a string")
    for entry in value.split(","):
        try:
            ipaddress.IPv4Address(entry.strip())
        except ValueError:
            raise HelperError("dns contains an invalid address: %s" % entry)
    return ", ".join(entry.strip() for entry in value.split(","))


def _host(value):
    if not isinstance(value, str) or not HOST_PATTERN.fullmatch(value):
        raise HelperError("endpoint_host is not a valid host name or address")
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        if not re.search(r"[A-Za-z]", value):
            raise HelperError("endpoint_host is not a valid host name or address")
    return value


def _port(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise HelperError("%s must be an integer between 1 and 65535" % field)
    return str(value)


def _mtu(value):
    if value is None:
        return "1420"
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_MTU <= value <= MAX_MTU:
        raise HelperError("mtu must be an integer between %d and %d" % (MIN_MTU, MAX_MTU))
    return str(value)


def _keepalive(value):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
        raise HelperError("keepalive must be an integer between 0 and 65535")
    return str(value)


def validate(config):
    if not isinstance(config, dict):
        raise HelperError("config must be an object")
    unknown = set(config) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        raise HelperError("config contains unsupported fields: %s" % ", ".join(sorted(unknown)))
    missing = [field for field in REQUIRED_FIELDS if field not in config]
    if missing:
        raise HelperError("config is missing fields: %s" % ", ".join(missing))
    return {
        "private_key": _key(config["private_key"], "private_key"),
        "address": _address(config["address"]),
        "peer_public_key": _key(config["peer_public_key"], "peer_public_key"),
        "allowed_ips": _cidr_list(config["allowed_ips"]),
        "endpoint_host": _host(config["endpoint_host"]),
        "endpoint_port": _port(config["endpoint_port"], "endpoint_port"),
        "dns": _dns(config.get("dns")),
        "mtu": _mtu(config.get("mtu")),
        "keepalive": _keepalive(config.get("keepalive")),
    }


def render(config):
    return _render_fields(validate(config))


def _render_fields(fields):
    lines = ["[Interface]", "PrivateKey = %s" % fields["private_key"], "Address = %s" % fields["address"]]
    lines.append("MTU = %s" % fields["mtu"])
    lines.extend(
        [
            "",
            "[Peer]",
            "PublicKey = %s" % fields["peer_public_key"],
            "AllowedIPs = %s" % fields["allowed_ips"],
            "Endpoint = %s:%s" % (fields["endpoint_host"], fields["endpoint_port"]),
        ]
    )
    if fields["keepalive"]:
        lines.append("PersistentKeepalive = %s" % fields["keepalive"])
    return "\n".join(lines) + "\n"


def _interface_address(name):
    result = _run([_tool("ifconfig"), name], check=False)
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("inet "):
            return stripped.split()[1]
    return None


def _peer_from_dump(parts):
    return {
        "public_key": parts[1],
        "endpoint": parts[3],
        "allowed_ips": parts[4],
        "latest_handshake": int(parts[5]) if parts[5].isdigit() else 0,
        "rx_bytes": int(parts[6]) if parts[6].isdigit() else 0,
        "tx_bytes": int(parts[7]) if parts[7].isdigit() else 0,
    }


def _dump():
    result = _run([_tool("wg"), "show", "all", "dump"], check=False)
    interfaces = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        bucket = interfaces.setdefault(parts[0], [])
        if len(parts) == 9:
            bucket.append(_peer_from_dump(parts))
    return interfaces


def _interface_name():
    if not os.path.exists(NAME_PATH):
        return None
    with open(NAME_PATH) as handle:
        return handle.read().strip() or None


def status():
    interfaces = _dump()
    name = _interface_name()
    up = bool(name) and name in interfaces
    return {
        "ok": True,
        "up": up,
        "interface": name if up else None,
        "address": _interface_address(name) if up else None,
        "peers": interfaces.get(name, []) if up else [],
        "config": os.path.exists(CONFIG_PATH),
    }


def _default_device():
    result = _run([ROUTE, "-n", "get", "default"], check=False)
    for line in result.stdout.splitlines():
        if line.strip().startswith("interface:"):
            return line.split(":", 1)[1].strip()
    return None


def _primary_service():
    device = _default_device()
    if not device:
        return None
    result = _run([NETWORKSETUP, "-listnetworkserviceorder"], check=False)
    service = None
    for line in result.stdout.splitlines():
        text = line.strip()
        match = re.match(r"^\(\d+\)\s+(.+)$", text)
        if match:
            service = match.group(1)
        elif "Device: %s)" % device in text:
            return service
    return None


def _read_dns(service):
    result = _run([NETWORKSETUP, "-getdnsservers", service])
    if "aren't any DNS Servers" in result.stdout:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _write_dns(service, servers):
    _run([NETWORKSETUP, "-setdnsservers", service] + (servers or ["Empty"]))


def _is_tunnel_resolver(server):
    return any(server.startswith(prefix) for prefix in TUNNEL_RESOLVERS)


def _dns_snapshot():
    try:
        with open(DNS_STATE_PATH) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except ValueError:
        os.unlink(DNS_STATE_PATH)
        return None


def _restore_dns():
    payload = _dns_snapshot()
    if payload is None:
        return
    servers = [item for item in payload["servers"] if not _is_tunnel_resolver(item)]
    _write_dns(payload["service"], servers)
    os.unlink(DNS_STATE_PATH)


def _apply_dns(dns):
    if not dns:
        return
    service = _primary_service()
    if not service:
        raise HelperError("could not identify the Mac’s default network service for DNS")
    payload = {"service": service, "servers": _read_dns(service), "applied": dns}
    temp = DNS_STATE_PATH + ".new"
    with open(temp, "w") as handle:
        json.dump(payload, handle)
    os.chmod(temp, 0o600)
    os.replace(temp, DNS_STATE_PATH)
    _write_dns(service, dns.split(", "))


def _write_config(text):
    os.makedirs(SOCKET_DIR, mode=0o700, exist_ok=True)
    temp = CONFIG_PATH + ".new"
    with open(temp, "w") as handle:
        handle.write(text)
    os.chmod(temp, 0o600)
    os.replace(temp, CONFIG_PATH)


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
    deadline = time.monotonic() + 2
    ifconfig = _tool("ifconfig")
    while _run([ifconfig, name], check=False).returncode == 0:
        if time.monotonic() >= deadline:
            raise HelperError("the previous tunnel did not stop (%s)" % name)
        time.sleep(0.05)


def _stop_tunnel():
    name = _interface_name()
    if os.path.exists(CONFIG_PATH):
        _run([_tool("wg-quick"), "down", CONFIG_PATH], check=False)
    if name:
        _wait_for_interface_exit(name)
    _restore_dns()
    if os.path.exists(CONFIG_PATH):
        os.unlink(CONFIG_PATH)


def _previous_tunnel():
    if not _interface_name() or not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH) as handle:
        text = handle.read()
    snapshot = _dns_snapshot()
    if snapshot is None:
        return text, None
    dns = snapshot.get("applied")
    if dns is None:
        dns = ", ".join(_read_dns(snapshot["service"])) or None
    return text, dns


def _start_tunnel(text, dns):
    _write_config(text)
    result = _run([_tool("wg-quick"), "up", CONFIG_PATH], check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HelperError("wg-quick up failed: %s" % detail)
    report = status()
    if not report["up"]:
        raise HelperError("wg-quick reported success but no tunnel interface exists")
    _apply_dns(dns)
    return report


def _recover_tunnel(previous):
    _stop_tunnel()
    if previous is None:
        return ""
    try:
        _start_tunnel(*previous)
    except (HelperError, OSError):
        _stop_tunnel()
        raise
    return " (previous tunnel restored)"


def down():
    _stop_tunnel()
    return status()


def up(config):
    fields = validate(config)
    fields["endpoint_host"] = _resolve_ipv4(fields["endpoint_host"], fields["endpoint_port"])
    previous = _previous_tunnel()
    _stop_tunnel()
    try:
        return _start_tunnel(_render_fields(fields), fields["dns"])
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


def _peer_uid(connection):
    try:
        data = connection.getsockopt(0, 0x001, 12)
    except OSError:
        return None
    if len(data) < 8:
        return None
    return int.from_bytes(data[4:8], sys.byteorder)


def _may_control(uid):
    if uid is None:
        return False
    if uid == 0:
        return True
    try:
        entry = pwd.getpwuid(uid)
        return ADMIN_GID in os.getgrouplist(entry.pw_name, entry.pw_gid)
    except KeyError:
        return False


def _respond(connection):
    with connection:
        if not _may_control(_peer_uid(connection)):
            connection.sendall(json.dumps({"ok": False, "error": "permission denied"}).encode() + b"\n")
            return
        payload = b""
        while not payload.endswith(b"\n") and len(payload) < MAX_MESSAGE:
            chunk = connection.recv(4096)
            if not chunk:
                break
            payload += chunk
        try:
            request = json.loads(payload.decode("utf-8") or "{}")
            response = dispatch(request)
        except (ValueError, HelperError) as error:
            response = {"ok": False, "error": str(error)}
        except Exception as error:
            response = {"ok": False, "error": "unexpected failure: %s" % error}
        connection.sendall(json.dumps(response).encode() + b"\n")


def serve():
    os.makedirs(SOCKET_DIR, mode=0o770, exist_ok=True)
    os.chown(SOCKET_DIR, 0, ADMIN_GID)
    os.chmod(SOCKET_DIR, 0o770)
    if not _interface_name():
        _restore_dns()
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chown(SOCKET_PATH, 0, ADMIN_GID)
    os.chmod(SOCKET_PATH, 0o660)
    server.listen(16)
    while True:
        connection, _ = server.accept()
        threading.Thread(target=_respond, args=(connection,), daemon=True).start()


if __name__ == "__main__":
    serve()
