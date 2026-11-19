import errno
import grp
import json
import os
import pwd
import re
import socket
import struct

from helper_common import HelperError, run, tool, write_private
from protonxlib import netstate
from protonxlib import system as host

INTERFACE = "protonx"
STATE_DIR = host.state_dir()
DNS_STATE_PATH = os.path.join(STATE_DIR, "dns.json")
RESOLV_CONF = "/etc/resolv.conf"
RESOLVED_STUB = "/run/systemd/resolve/stub-resolv.conf"
SYS_NET = "/sys/class/net"
CONTROL_GROUP = "protonx"
BYPASS_PRIORITY = 5180
RESOLV_HEADER = netstate.RESOLV_HEADER
BYPASS_RULE = re.compile(r"^%d:\s+from (\S+) lookup main\b" % BYPASS_PRIORITY)


def interface_exists(name):
    return os.path.exists(os.path.join(SYS_NET, name))


def interface_name():
    return INTERFACE if interface_exists(INTERFACE) else None


def clear_interface_name():
    pass


def interface_address(name):
    result = run([tool("ip"), "-4", "-o", "addr", "show", "dev", name], check=False)
    for line in result.stdout.splitlines():
        fields = line.split()
        if "inet" in fields:
            return fields[fields.index("inet") + 1].split("/")[0]
    return None


def remove_interface(name):
    if interface_exists(name):
        run([tool("ip"), "link", "delete", "dev", name], check=False)


def _local_addresses():
    result = run([tool("ip"), "-4", "-o", "addr", "show"], check=False)
    found = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if "inet" in fields:
            found.add(fields[fields.index("inet") + 1].split("/")[0])
    return found


def check_bypass(address):
    if address and address not in _local_addresses():
        raise HelperError("%s is not an address of this machine" % address)


def add_bypass(address):
    if not address:
        return
    check_bypass(address)
    run([tool("ip"), "-4", "rule", "add", "from", address, "lookup", "main", "priority", str(BYPASS_PRIORITY)])


def _bypass_rules():
    result = run([tool("ip"), "-4", "rule", "show"], check=False)
    return [match.group(1) for match in map(BYPASS_RULE.match, result.stdout.splitlines()) if match]


def remove_bypass():
    for address in _bypass_rules():
        run(
            [tool("ip"), "-4", "rule", "del", "from", address, "lookup", "main", "priority", str(BYPASS_PRIORITY)],
            check=False,
        )


def current_bypass():
    rules = _bypass_rules()
    return rules[0] if rules else None


def _uses_resolved():
    try:
        return os.path.realpath(RESOLV_CONF) == RESOLVED_STUB and os.path.exists(RESOLVED_STUB)
    except OSError:
        return False


def _resolvectl(*args, check=True):
    return run([tool("resolvectl")] + list(args), check=check)


def _resolv_snapshot():
    if os.path.islink(RESOLV_CONF):
        return {"link": os.readlink(RESOLV_CONF)}
    try:
        with open(RESOLV_CONF) as handle:
            return {"content": handle.read()}
    except FileNotFoundError:
        return {"content": None}


def _overwrite_in_place(content):
    with open(RESOLV_CONF, "w") as handle:
        handle.write(content)


def _replace_resolv(snapshot):
    temporary = RESOLV_CONF + ".protonx"
    if os.path.lexists(temporary):
        os.unlink(temporary)
    if snapshot.get("link"):
        os.symlink(snapshot["link"], temporary)
    elif snapshot.get("content") is not None:
        with open(temporary, "w") as handle:
            handle.write(snapshot["content"])
        os.chmod(temporary, 0o644)
    else:
        if os.path.lexists(RESOLV_CONF):
            os.unlink(RESOLV_CONF)
        return
    try:
        os.replace(temporary, RESOLV_CONF)
    except OSError as error:
        os.unlink(temporary)
        if error.errno != errno.EBUSY or snapshot.get("link"):
            raise
        _overwrite_in_place(snapshot["content"])


def _save_snapshot(payload):
    os.makedirs(os.path.dirname(DNS_STATE_PATH), mode=0o755, exist_ok=True)
    write_private(DNS_STATE_PATH, json.dumps(payload))


def _snapshot():
    try:
        with open(DNS_STATE_PATH) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except ValueError:
        os.unlink(DNS_STATE_PATH)
        return None


def apply_dns(dns):
    if not dns:
        return
    servers = dns.split(", ")
    if _uses_resolved():
        _save_snapshot({"method": "resolved", "applied": dns})
        _resolvectl("dns", INTERFACE, *servers)
        _resolvectl("domain", INTERFACE, "~.")
        _resolvectl("default-route", INTERFACE, "yes", check=False)
        return
    _save_snapshot(dict(_resolv_snapshot(), method="file", applied=dns))
    content = RESOLV_HEADER + "".join("nameserver %s\n" % server for server in servers)
    _replace_resolv({"content": content})


def restore_dns():
    payload = _snapshot()
    if payload is not None:
        if payload.get("method") == "resolved":
            if interface_exists(INTERFACE):
                _resolvectl("revert", INTERFACE, check=False)
        else:
            _replace_resolv(payload)
        os.unlink(DNS_STATE_PATH)
        return
    # No snapshot: remove a protonx-written resolv.conf instead of leaving the
    # machine without a resolver after a reboot or a helper replacement.
    try:
        with open(RESOLV_CONF) as handle:
            text = handle.read()
    except OSError:
        return
    if not text.startswith(RESOLV_HEADER):
        return
    if os.path.exists(RESOLVED_STUB):
        _replace_resolv({"link": RESOLVED_STUB})
    else:
        try:
            os.unlink(RESOLV_CONF)
        except OSError:
            pass


def applied_dns():
    payload = _snapshot()
    return payload.get("applied") if payload else None


def dns_report(up):
    return netstate.linux_dns_report(up)


def flush_dns():
    netstate.flush_dns()


def resolves(name):
    return netstate.resolves(name)


def internet():
    return netstate.internet()


def peer_uid(connection):
    size = struct.calcsize("3i")
    try:
        data = connection.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, size)
    except OSError:
        return None
    if len(data) < size:
        return None
    return struct.unpack("3i", data)[1]


def may_control(uid):
    if uid is None:
        return False
    if uid == 0:
        return True
    try:
        entry = pwd.getpwuid(uid)
        group = grp.getgrnam(CONTROL_GROUP)
    except KeyError:
        return False
    return group.gr_gid in os.getgrouplist(entry.pw_name, entry.pw_gid)


def prepare_socket_dir(path):
    os.makedirs(path, mode=0o755, exist_ok=True)
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)


def protect_socket(path):
    os.chown(path, 0, 0)
    os.chmod(path, 0o666)
