from . import system, wgconf
from .errors import TunnelError

if system.IS_WINDOWS:
    from . import tunnel_windows as backend
else:
    from . import helper as backend

DEFAULT_DNS = "10.2.0.1"
DEFAULT_MTU = wgconf.DEFAULT_MTU
DEFAULT_ADDRESS = "10.2.0.2/32"
ALLOWED_IPS = "0.0.0.0/0"
DEFAULT_KEEPALIVE = 25


def config(
    private_key,
    peer_public_key,
    endpoint_host,
    port,
    dns=DEFAULT_DNS,
    mtu=DEFAULT_MTU,
    address=DEFAULT_ADDRESS,
    allowed_ips=ALLOWED_IPS,
    keepalive=DEFAULT_KEEPALIVE,
    bypass_source=None,
):
    settings = {
        "private_key": private_key,
        "address": address,
        "peer_public_key": peer_public_key,
        "allowed_ips": allowed_ips,
        "endpoint_host": endpoint_host,
        "endpoint_port": int(port),
        "dns": dns,
        "mtu": int(mtu),
        "keepalive": keepalive,
    }
    if bypass_source:
        settings["bypass_source"] = bypass_source
    return settings


def preview(settings):
    try:
        return wgconf.render(wgconf.validate(settings), with_dns=system.IS_WINDOWS)
    except wgconf.ConfigError as error:
        raise TunnelError(str(error)) from error


def available():
    return backend.available()


def up(settings):
    return backend.up(settings)


def down():
    return backend.down()


def status():
    return backend.status()


def peer(settings):
    report = status()
    for item in report.get("peers", []):
        if item.get("public_key") == settings.get("peer_public_key"):
            return item
    return report.get("peers", [None])[0]


def describe(settings):
    return "%s:%s" % (settings["endpoint_host"], settings["endpoint_port"])
