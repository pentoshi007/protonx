import os
import re
import shutil
import socket
import struct
import subprocess

from . import system
from .errors import NO_TRAFFIC

TUNNEL_RESOLVERS = ("10.2.0.1", "10.200.")
NETWORKSETUP = "/usr/sbin/networksetup"
ROUTE = "/sbin/route"
RESOLV_CONF = "/etc/resolv.conf"
RESOLVED_STUB = "/run/systemd/resolve/stub-resolv.conf"
RESOLV_HEADER = "# Written by protonx while the VPN is connected; restored on disconnect.\n"
COMMAND_TIMEOUT = 8


def is_tunnel_resolver(server):
    return any(server.startswith(prefix) for prefix in TUNNEL_RESOLVERS)


def _run(args):
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
            env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def mac_default_device():
    result = _run([ROUTE, "-n", "get", "default"])
    if result is None:
        return None
    for line in result.stdout.splitlines():
        if line.strip().startswith("interface:"):
            return line.split(":", 1)[1].strip()
    return None


def mac_primary_service():
    device = mac_default_device()
    if not device:
        return None
    result = _run([NETWORKSETUP, "-listnetworkserviceorder"])
    if result is None:
        return None
    service = None
    for line in result.stdout.splitlines():
        text = line.strip()
        match = re.match(r"^\(\d+\)\s+(.+)$", text)
        if match:
            service = match.group(1)
        elif "Device: %s)" % device in text:
            return service
    return None


def mac_read_dns(service):
    if not service:
        return []
    result = _run([NETWORKSETUP, "-getdnsservers", service])
    if result is None or "aren't any DNS Servers" in result.stdout:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def mac_write_dns(service, servers):
    if not service:
        return
    _run([NETWORKSETUP, "-setdnsservers", service] + (list(servers) or ["Empty"]))


def mac_dns_report(up):
    service = mac_primary_service()
    servers = mac_read_dns(service)
    stale = (not up) and any(is_tunnel_resolver(server) for server in servers)
    return {"stale": stale, "servers": servers, "service": service}


def linux_dns_report(up):
    servers = []
    stale = False
    try:
        with open(RESOLV_CONF) as handle:
            text = handle.read()
    except OSError:
        return {"stale": False, "servers": [], "service": RESOLV_CONF}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "nameserver":
            servers.append(fields[1])
    stale = (not up) and (text.startswith(RESOLV_HEADER) or any(is_tunnel_resolver(server) for server in servers))
    return {"stale": stale, "servers": servers, "service": RESOLV_CONF}


def dns_report(up):
    if system.IS_MAC:
        return mac_dns_report(up)
    if system.IS_LINUX:
        return linux_dns_report(up)
    return {"stale": False, "servers": [], "service": None}


def flush_dns():
    if system.IS_MAC:
        _run(["/usr/bin/dscacheutil", "-flushcache"])
        _run(["/usr/bin/killall", "-HUP", "mDNSResponder"])
        return
    if system.IS_LINUX and shutil.which("resolvectl"):
        _run(["resolvectl", "flush-caches"])


def resolves(host):
    try:
        socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except socket.gaierror:
        return False


def internet():
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            return True
    except OSError:
        return False


FLOW_RESOLVER = "10.2.0.1"
FLOW_PROBE_NAME = "proton.me"
FLOW_TIMEOUT = 3


def _query(name, ident):
    header = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    return header + labels + b"\x00" + struct.pack("!HH", 1, 1)


def flow_problem(resolver=FLOW_RESOLVER, timeout=FLOW_TIMEOUT, name=FLOW_PROBE_NAME):
    """Return why the tunnel carries no traffic, or None when data flows.

    The probe talks to the resolver that lives inside the tunnel, using a bare
    IP so nothing outside the interface can make it pass or fail.
    """
    ident = struct.unpack("!H", os.urandom(2))[0]
    payload = _query(name, ident)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(timeout)
            probe.sendto(payload, (resolver, 53))
            reply, _ = probe.recvfrom(2048)
    except OSError as error:
        return "%s (no answer from %s: %s)" % (NO_TRAFFIC, resolver, error)
    if len(reply) < 12 or struct.unpack("!H", reply[:2])[0] != ident:
        return "%s (unexpected answer from %s)" % (NO_TRAFFIC, resolver)
    return None
