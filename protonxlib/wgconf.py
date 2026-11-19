import base64
import ipaddress
import re

MIN_MTU = 1280
MAX_MTU = 1500
DEFAULT_MTU = 1420

REQUIRED_FIELDS = (
    "private_key",
    "address",
    "peer_public_key",
    "allowed_ips",
    "endpoint_host",
    "endpoint_port",
)
OPTIONAL_FIELDS = ("dns", "mtu", "keepalive", "bypass_source")

HOST_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


class ConfigError(ValueError):
    pass


def _key(value, field):
    if not isinstance(value, str) or len(value) != 44:
        raise ConfigError("%s must be a 44 character base64 key" % field)
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ConfigError("%s is not valid base64: %s" % (field, error))
    if len(raw) != 32:
        raise ConfigError("%s must decode to 32 bytes" % field)
    return value


def _cidr_list(value):
    if not isinstance(value, str):
        raise ConfigError("allowed_ips must be a string")
    networks = [item.strip() for item in value.split(",") if item.strip()]
    if not networks:
        raise ConfigError("allowed_ips must list at least one network")
    for item in networks:
        try:
            ipaddress.IPv4Network(item, strict=False)
        except ValueError:
            raise ConfigError("allowed_ips contains an invalid network: %s" % item)
    return ", ".join(networks)


def _address(value):
    if not isinstance(value, str) or "/" not in value:
        raise ConfigError("address must be an IPv4 address with a prefix length")
    try:
        ipaddress.IPv4Interface(value)
    except ValueError:
        raise ConfigError("address is not a valid IPv4 interface: %s" % value)
    return value


def _dns(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError("dns must be a string")
    for entry in value.split(","):
        try:
            ipaddress.IPv4Address(entry.strip())
        except ValueError:
            raise ConfigError("dns contains an invalid address: %s" % entry)
    return ", ".join(entry.strip() for entry in value.split(","))


def _host(value):
    if not isinstance(value, str) or not HOST_PATTERN.fullmatch(value):
        raise ConfigError("endpoint_host is not a valid host name or address")
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        if not re.search(r"[A-Za-z]", value):
            raise ConfigError("endpoint_host is not a valid host name or address")
    return value


def _port(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise ConfigError("%s must be an integer between 1 and 65535" % field)
    return str(value)


def _mtu(value):
    if value is None:
        return str(DEFAULT_MTU)
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_MTU <= value <= MAX_MTU:
        raise ConfigError("mtu must be an integer between %d and %d" % (MIN_MTU, MAX_MTU))
    return str(value)


def _keepalive(value):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
        raise ConfigError("keepalive must be an integer between 0 and 65535")
    return str(value)


def _bypass_source(value):
    if value in (None, ""):
        return None
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError:
        raise ConfigError("bypass_source must be an IPv4 address")


def validate(config):
    if not isinstance(config, dict):
        raise ConfigError("config must be an object")
    unknown = set(config) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        raise ConfigError("config contains unsupported fields: %s" % ", ".join(sorted(unknown)))
    missing = [field for field in REQUIRED_FIELDS if field not in config]
    if missing:
        raise ConfigError("config is missing fields: %s" % ", ".join(missing))
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
        "bypass_source": _bypass_source(config.get("bypass_source")),
    }


def render(fields, with_dns=False):
    lines = ["[Interface]", "PrivateKey = %s" % fields["private_key"], "Address = %s" % fields["address"]]
    if with_dns and fields["dns"]:
        lines.append("DNS = %s" % fields["dns"])
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


def parse_dump(text):
    interfaces = {}
    for line in text.splitlines():
        parts = line.split("\t")
        bucket = interfaces.setdefault(parts[0], [])
        if len(parts) == 9:
            bucket.append(_peer_from_dump(parts))
    return interfaces


def _peer_from_dump(parts):
    return {
        "public_key": parts[1],
        "endpoint": parts[3],
        "allowed_ips": parts[4],
        "latest_handshake": int(parts[5]) if parts[5].isdigit() else 0,
        "rx_bytes": int(parts[6]) if parts[6].isdigit() else 0,
        "tx_bytes": int(parts[7]) if parts[7].isdigit() else 0,
    }
