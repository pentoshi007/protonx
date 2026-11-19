import json
import os
import pwd
import sys

from helper_common import HelperError, run, tool, write_private
from protonxlib import netstate
from protonxlib import system as host

STATE_DIR = host.state_dir()
DNS_STATE_PATH = os.path.join(STATE_DIR, "dns.json")
NAME_PATH = "/var/run/wireguard/protonx.name"
ADMIN_GID = 80
SOL_LOCAL = 0
LOCAL_PEERCRED = 0x001


def interface_name():
    if not os.path.exists(NAME_PATH):
        return None
    with open(NAME_PATH) as handle:
        return handle.read().strip() or None


def clear_interface_name():
    try:
        os.unlink(NAME_PATH)
    except FileNotFoundError:
        pass


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


def _primary_service():
    return netstate.mac_primary_service()


def _read_dns(service):
    return netstate.mac_read_dns(service)


def _write_dns(service, servers):
    netstate.mac_write_dns(service, servers)


def _is_tunnel_resolver(server):
    return netstate.is_tunnel_resolver(server)


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
    if payload is not None:
        servers = [item for item in payload["servers"] if not _is_tunnel_resolver(item)]
        _write_dns(payload["service"], servers)
        os.unlink(DNS_STATE_PATH)
        return
    # No snapshot (reboot, helper replacement, or a crash): never leave the
    # machine pointing at a resolver that only exists inside the tunnel.
    service = _primary_service()
    if not service:
        return
    current = _read_dns(service)
    if any(_is_tunnel_resolver(item) for item in current):
        _write_dns(service, [item for item in current if not _is_tunnel_resolver(item)])


def apply_dns(dns):
    if not dns:
        return
    service = _primary_service()
    if not service:
        raise HelperError("could not identify the Mac’s default network service for DNS")
    payload = {"service": service, "servers": _read_dns(service), "applied": dns}
    os.makedirs(os.path.dirname(DNS_STATE_PATH), mode=0o755, exist_ok=True)
    write_private(DNS_STATE_PATH, json.dumps(payload))
    _write_dns(service, dns.split(", "))


def applied_dns():
    payload = _snapshot()
    if payload is None:
        return None
    if payload.get("applied") is not None:
        return payload["applied"]
    return ", ".join(_read_dns(payload["service"])) or None


def dns_report(up):
    return netstate.mac_dns_report(up)


def flush_dns():
    netstate.flush_dns()


def resolves(name):
    return netstate.resolves(name)


def internet():
    return netstate.internet()


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
