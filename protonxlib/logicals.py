from dataclasses import dataclass, field

WIREGUARD_DEFAULT_PORT = 51820
SECURE_CORE_FEATURE = 4
P2P_FEATURE = 2


@dataclass(frozen=True)
class Entry:
    server_id: str
    name: str
    domain: str
    entry_ip: str
    x25519: str
    ports: tuple

    @property
    def endpoint_host(self):
        return self.entry_ip or self.domain

    @property
    def port(self):
        return self.ports[0] if self.ports else WIREGUARD_DEFAULT_PORT


@dataclass(frozen=True)
class Logical:
    id: str
    name: str
    exit_country: str
    entry_country: str
    city: str
    tier: int
    load: int
    status: int
    features: int
    entries: tuple = field(default_factory=tuple)

    @property
    def free(self):
        return self.tier == 0

    @property
    def online(self):
        return self.status == 1

    @property
    def secure_core(self):
        return bool(self.features & SECURE_CORE_FEATURE) or self.entry_country != self.exit_country

    @property
    def p2p(self):
        return bool(self.features & P2P_FEATURE)

    @property
    def wireguard_entries(self):
        return tuple(entry for entry in self.entries if entry.x25519)

    def display_name(self):
        return self.name or self.id


class LogicalList(list):
    def by_country(self, code):
        return LogicalList(item for item in self if item.exit_country == code)

    def free_only(self):
        return LogicalList(item for item in self if item.free)

    def online_only(self):
        return LogicalList(item for item in self if item.online)

    def standard_only(self):
        return LogicalList(item for item in self if not item.secure_core)

    def countries(self):
        codes = {}
        for item in self:
            bucket = codes.setdefault(item.exit_country, {"count": 0, "free": False})
            bucket["count"] += 1
            bucket["free"] = bucket["free"] or item.free
        return codes


def _ports(protocol_entry):
    if not isinstance(protocol_entry, dict):
        return ()
    raw = protocol_entry.get("Ports") or protocol_entry.get("ports") or ()
    return tuple(int(port) for port in raw if str(port).isdigit())


def _protocol_entry(server, protocol):
    entries = server.get("ProtocolEntries") or server.get("EntryPerProtocol") or {}
    return entries.get(protocol) if isinstance(entries, dict) else None


def parse_entry(server, protocol="WireGuardUDP"):
    protocol_entry = _protocol_entry(server, protocol)
    x25519 = server.get("X25519PublicKey") or (protocol_entry or {}).get("X25519PublicKey") or ""
    ipv4 = (protocol_entry or {}).get("Ipv4") or (protocol_entry or {}).get("IPv4") or server.get("EntryIP")
    return Entry(
        server_id=str(server.get("ID", "")),
        name=str(server.get("Name") or server.get("Domain") or server.get("EntryIP") or ""),
        domain=str(server.get("Domain") or ""),
        entry_ip=str(ipv4 or ""),
        x25519=str(x25519),
        ports=_ports(protocol_entry),
    )


def parse_logical(raw, protocol="WireGuardUDP"):
    servers = raw.get("Servers") or []
    return Logical(
        id=str(raw.get("ID", "")),
        name=str(raw.get("Name", "")),
        exit_country=str(raw.get("ExitCountry", "")).upper(),
        entry_country=str(raw.get("EntryCountry", raw.get("ExitCountry", ""))).upper(),
        city=str(raw.get("City") or ""),
        tier=int(raw.get("Tier") or 0),
        load=int(raw.get("Load") or 0),
        status=int(raw.get("Status") or 0),
        features=int(raw.get("Features") or 0),
        entries=tuple(parse_entry(server, protocol) for server in servers),
    )


def parse(payload, protocol="WireGuardUDP"):
    return LogicalList(parse_logical(raw, protocol) for raw in payload.get("LogicalServers") or [])
