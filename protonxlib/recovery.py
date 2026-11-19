import json
import os
import subprocess

from . import netstate, system

TUNNEL_FILE = "tunnel.json"
CONFIG_FILE = "protonx.conf"


def state_dir():
    return system.state_dir()


def tunnel_path():
    return os.path.join(state_dir(), TUNNEL_FILE)


def config_path():
    return os.path.join(state_dir(), CONFIG_FILE)


def load_tunnel():
    try:
        with open(tunnel_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def interface_exists(name):
    if not name:
        return False
    if system.IS_MAC:
        try:
            return subprocess.run(
                ["/sbin/ifconfig", name], capture_output=True, timeout=5
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if system.IS_LINUX:
        return os.path.exists(os.path.join("/sys/class/net", name))
    return False


def probe():
    """Unprivileged status used when the helper socket is unavailable."""
    record = load_tunnel()
    name = (record or {}).get("interface")
    up = interface_exists(name)
    return {
        "ok": True,
        "up": up,
        "interface": name if up else None,
        "address": record.get("address") if up else None,
        "peers": [],
        "config": os.path.exists(config_path()),
        "bypass_source": None,
        "server": record.get("server") if up else None,
        "dns": netstate.dns_report(up),
        "fallback": True,
    }


def manual_hint():
    if system.IS_MAC:
        return (
            "The ProtonX helper is not running. Restore DNS manually with:\n"
            "  sudo networksetup -setdnsservers Wi-Fi Empty\n"
            "  sudo dscacheutil -flushcache\n"
            "  sudo killall -HUP mDNSResponder\n"
            "Then reinstall ProtonX to restore the helper."
        )
    if system.IS_LINUX:
        return (
            "The ProtonX helper is not running. Restore DNS manually with:\n"
            "  sudo resolvectl flush-caches\n"
            "  sudo rm -f /etc/resolv.conf.protonx\n"
            "Then reinstall ProtonX to restore the helper."
        )
    return (
        "The ProtonX helper is not running. Stop the tunnel service manually with:\n"
        "  sc.exe stop WireGuardTunnel$protonx\n"
        "  sc.exe delete WireGuardTunnel$protonx\n"
        "Then reinstall ProtonX."
    )
