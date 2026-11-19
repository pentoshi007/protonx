from . import helper
from .errors import TunnelError

DEFAULT_DNS = "10.2.0.1"
DEFAULT_MTU = 1420
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
):
    return {
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


def preview(settings):
    return helper.call({"command": "render", "config": settings})["config"]


def up(settings):
    return helper.up(settings)


def down():
    return helper.down()


def status():
    return helper.status()


def peer(settings):
    report = status()
    for item in report.get("peers", []):
        if item.get("public_key") == settings.get("peer_public_key"):
            return item
    return report.get("peers", [None])[0]


def describe(settings):
    return "%s:%s" % (settings["endpoint_host"], settings["endpoint_port"])
