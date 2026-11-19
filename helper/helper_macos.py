import json
import os
import pwd
import re
import sys

from helper_common import HelperError, run, tool, write_private

STATE_DIR = "/var/run/protonx"
DNS_STATE_PATH = os.path.join(STATE_DIR, "dns.json")
NAME_PATH = "/var/run/wireguard/protonx.name"
NETWORKSETUP = "/usr/sbin/networksetup"
ROUTE = "/sbin/route"
TUNNEL_RESOLVERS = ("10.2.0.1", "10.200.")
ADMIN_GID = 80
SOL_LOCAL = 0
LOCAL_PEERCRED = 0x001


def interface_name():
    if not os.path.exists(NAME_PATH):
        return None
    with open(NAME_PATH) as handle:
        return handle.read().strip() or None


def interface_exists(name):
    return run([tool("ifconfig"), name], check=False).returncode == 0


def interface_address(name):
    result = run([tool("ifconfig"), name], check=False)
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("inet "):
            return stripped.split()[1]
    return None


def remove_interface(name):
    pass


def check_bypass(address):
    if address:
        raise HelperError("keeping an SSH session outside the tunnel is only supported on Linux")


def add_bypass(address):
    check_bypass(address)


def remove_bypass():
    pass


def current_bypass():
    return None


def _default_device():
    result = run([ROUTE, "-n", "get", "default"], check=False)
    for line in result.stdout.splitlines():
        if line.strip().startswith("interface:"):
            return line.split(":", 1)[1].strip()
    return None


def _primary_service():
    device = _default_device()
    if not device:
        return None
    result = run([NETWORKSETUP, "-listnetworkserviceorder"], check=False)
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
    result = run([NETWORKSETUP, "-getdnsservers", service])
    if "aren't any DNS Servers" in result.stdout:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _write_dns(service, servers):
    run([NETWORKSETUP, "-setdnsservers", service] + (servers or ["Empty"]))


def _is_tunnel_resolver(server):
    return any(server.startswith(prefix) for prefix in TUNNEL_RESOLVERS)


def _snapshot():
    try:
        with open(DNS_STATE_PATH) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except ValueError:
        os.unlink(DNS_STATE_PATH)
        return None


def restore_dns():
    payload = _snapshot()
    if payload is None:
        return
    servers = [item for item in payload["servers"] if not _is_tunnel_resolver(item)]
    _write_dns(payload["service"], servers)
    os.unlink(DNS_STATE_PATH)


def apply_dns(dns):
    if not dns:
        return
    service = _primary_service()
    if not service:
        raise HelperError("could not identify the Mac’s default network service for DNS")
    payload = {"service": service, "servers": _read_dns(service), "applied": dns}
    write_private(DNS_STATE_PATH, json.dumps(payload))
    _write_dns(service, dns.split(", "))


def applied_dns():
    payload = _snapshot()
    if payload is None:
        return None
    if payload.get("applied") is not None:
        return payload["applied"]
    return ", ".join(_read_dns(payload["service"])) or None


def peer_uid(connection):
    try:
        data = connection.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, 12)
    except OSError:
        return None
    if len(data) < 8:
        return None
    return int.from_bytes(data[4:8], sys.byteorder)


def may_control(uid):
    if uid is None:
        return False
    if uid == 0:
        return True
    try:
        entry = pwd.getpwuid(uid)
        return ADMIN_GID in os.getgrouplist(entry.pw_name, entry.pw_gid)
    except KeyError:
        return False


def prepare_socket_dir(path):
    os.makedirs(path, mode=0o770, exist_ok=True)
    os.chown(path, 0, ADMIN_GID)
    os.chmod(path, 0o770)


def protect_socket(path):
    os.chown(path, 0, ADMIN_GID)
    os.chmod(path, 0o660)
