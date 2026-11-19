import ipaddress
import os
import sys

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = os.name == "nt"


def name():
    if IS_MAC:
        return "macOS"
    if IS_WINDOWS:
        return "Windows"
    if IS_LINUX:
        return "Linux"
    return sys.platform


def config_dir():
    if IS_WINDOWS:
        # An elevated process can start with a reduced environment, so fall back
        # to the profile directory instead of writing next to the working dir.
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "protonx")
    return os.path.expanduser("~/.config/protonx")


def state_dir():
    """Root-owned, reboot-safe state shared by the helper and the CLI probe."""
    if IS_MAC:
        return "/Library/Application Support/ProtonX"
    if IS_LINUX:
        return "/var/lib/protonx"
    base = os.environ.get("ProgramData") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ProtonX")


def ssh_source():
    parts = os.environ.get("SSH_CONNECTION", "").split()
    if len(parts) != 4:
        return None
    try:
        address = ipaddress.ip_address(parts[2])
    except ValueError:
        return None
    return str(address) if address.version == 4 else None


def ssh_guard_supported():
    return IS_LINUX and ssh_source() is not None


def is_admin():
    if IS_WINDOWS:
        import ctypes

        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return os.geteuid() == 0
