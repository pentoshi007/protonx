import os
import subprocess
import time

from . import netstate, system, wgconf
from .errors import TunnelError

TUNNEL = "protonx"
SERVICE = "WireGuardTunnel$" + TUNNEL
WIREGUARD_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "WireGuard")
CONFIG_PATH = os.path.join(system.config_dir(), "tunnel", TUNNEL + ".conf")
START_TIMEOUT = 15
STOP_TIMEOUT = 10
SERVICE_MISSING = 1060
INSTALL_HINT = "WireGuard for Windows is not installed. Install it with: winget install WireGuard.WireGuard"
ADMIN_HINT = (
    "connecting on Windows needs an Administrator terminal. Right-click your terminal, "
    "choose 'Run as administrator', then run protonx again."
)


def _executable(name):
    path = os.path.join(WIREGUARD_DIR, name)
    if not os.path.exists(path):
        raise TunnelError(INSTALL_HINT)
    return path


def _run(args, check=True):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise TunnelError("%s timed out" % os.path.basename(args[0])) from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise TunnelError("%s failed: %s" % (os.path.basename(args[0]), detail))
    return result


def _require_admin():
    if not system.is_admin():
        raise TunnelError(ADMIN_HINT)


def _service_state():
    result = _run(["sc.exe", "query", SERVICE], check=False)
    if result.returncode == SERVICE_MISSING or "1060" in result.stdout:
        return None
    for line in result.stdout.splitlines():
        if "STATE" in line:
            return line.split()[-1]
    return "UNKNOWN"


def _wait(predicate, timeout):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def _configured_address():
    try:
        with open(CONFIG_PATH) as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip() == "Address":
                    return value.strip().split("/")[0]
    except OSError:
        pass
    return None


def _peers():
    if not system.is_admin():
        return []
    result = _run([_executable("wg.exe"), "show", "all", "dump"], check=False)
    return wgconf.parse_dump(result.stdout).get(TUNNEL, [])


def available():
    return os.path.exists(os.path.join(WIREGUARD_DIR, "wireguard.exe"))


def status():
    up = available() and _service_state() == "RUNNING"
    return {
        "ok": True,
        "up": up,
        "interface": TUNNEL if up else None,
        "address": _configured_address() if up else None,
        "peers": _peers() if up else [],
        "config": os.path.exists(CONFIG_PATH),
        "bypass_source": None,
        "server": None,
        "dns": {"stale": False, "servers": [], "service": None},
    }


def _uninstall():
    if _service_state() is None:
        return
    _run([_executable("wireguard.exe"), "/uninstalltunnelservice", TUNNEL], check=False)
    if not _wait(lambda: _service_state() is None, STOP_TIMEOUT):
        raise TunnelError("the previous WireGuard tunnel did not stop")


def _install(text):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as handle:
        handle.write(text)
    _run([_executable("wireguard.exe"), "/installtunnelservice", CONFIG_PATH])
    if not _wait(lambda: _service_state() == "RUNNING", START_TIMEOUT):
        raise TunnelError("WireGuard did not start the tunnel")


def _previous():
    if _service_state() is None:
        return None
    try:
        with open(CONFIG_PATH) as handle:
            return handle.read()
    except OSError:
        return None


def up(settings):
    _require_admin()
    _executable("wireguard.exe")
    try:
        fields = wgconf.validate(settings)
    except wgconf.ConfigError as error:
        raise TunnelError(str(error)) from error
    if fields["bypass_source"]:
        raise TunnelError("keeping an SSH session outside the tunnel is only supported on Linux")
    previous = _previous()
    _uninstall()
    last_error = None
    for attempt in range(2):
        try:
            _install(wgconf.render(fields, with_dns=True))
            report = status()
            if attempt:
                report["retried"] = True
            return report
        except TunnelError as error:
            last_error = error
            _uninstall()
            if attempt == 0:
                time.sleep(0.6)
    if previous is not None:
        try:
            _install(previous)
        except TunnelError:
            _uninstall()
            raise TunnelError("%s. Recovery failed; the tunnel is stopped." % last_error) from last_error
        raise TunnelError("%s (previous tunnel restored)" % last_error) from last_error
    raise TunnelError("%s. The system was restored to its normal network settings." % last_error) from last_error


def down():
    if _service_state() is not None:
        _require_admin()
        _uninstall()
    if os.path.exists(CONFIG_PATH):
        os.unlink(CONFIG_PATH)
    return status()


def repair():
    _require_admin()
    actions = []
    if _service_state() is not None:
        _uninstall()
        actions.append("stopped the WireGuard tunnel service")
    if os.path.exists(CONFIG_PATH):
        os.unlink(CONFIG_PATH)
        actions.append("removed the tunnel configuration")
    report = status()
    report["actions"] = actions
    report["resolves"] = netstate.resolves("apple.com")
    report["internet"] = netstate.internet()
    return report
