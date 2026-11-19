import shutil
import sys
import time
from dataclasses import dataclass
from urllib.error import URLError

from . import api, auth, catalog, credentials, identity, login, selection, state, system, wireguard
from .countries import NAMES
from .errors import ProtonxError, SelectionError, TunnelError

NETWORK_ERRORS = (URLError, TimeoutError)
TOOL_PATH = "/opt/homebrew/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass
class ConnectOptions:
    paid: bool = False
    p2p: bool = False
    dns: bool = True
    ssh_guard: bool = True
    mtu: int = wireguard.DEFAULT_MTU
    allowed_ips: str = wireguard.ALLOWED_IPS


def client(offline=False, persist=True):
    if offline:
        return None
    return auth.make_client(auth.load_session(), persist=persist)


def load_pool(offline=False, api_client=None, persist=True):
    if offline:
        return catalog.cached()
    return catalog.live(api_client or client(persist=persist))


def tier(session):
    try:
        users = api.auth_post("/core/v4/users", None, session=session, method="GET")
        user = users.get("User") or {}
        return 0 if not user.get("Subscribed") else None
    except (ProtonxError,) + NETWORK_ERRORS:
        return None


def tier_label(value):
    if value is None:
        return "unknown"
    return "free" if value == 0 else str(value)


def default_username():
    session = login.current()
    if session and session.get("username"):
        return session["username"]
    try:
        return credentials.read_json(auth.LEGACY_SERVICE, auth.LEGACY_ACCOUNT).get("username")
    except ProtonxError:
        return None


def account(remote=True):
    session = login.current()
    pending = login.pending()
    payload = {"signedIn": bool(session), "pending": pending is not None}
    if session or pending:
        payload["username"] = (session or pending).get("username")
    else:
        payload["username"] = default_username()
    if session and remote:
        payload["tier"] = tier(session)
    return payload


def destinations(pool, options):
    usable = selection.eligible(pool, include_paid=options.paid, p2p_only=options.p2p)
    grouped = {}
    for server in usable:
        grouped.setdefault(server.exit_country, []).append(server)
    rows = [
        {
            "code": code,
            "name": NAMES.get(code, code),
            "servers": len(items),
            "best_load": min(item.load for item in items),
        }
        for code, items in grouped.items()
    ]
    return sorted(rows, key=lambda row: row["name"])


def servers_in(pool, country, options):
    found = selection.candidates(pool, country, include_paid=options.paid, p2p_only=options.p2p)
    return sorted(found, key=lambda item: (item.load, item.name))


def pick(pool, country_query, server_name, options, randomly=False):
    country = selection.resolve_country(pool, country_query)
    return selection.select(
        pool,
        country=country,
        server=server_name,
        include_paid=options.paid,
        p2p_only=options.p2p,
        strategy=selection.RANDOM if randomly else selection.FASTEST,
    )


def last_target():
    saved = state.load()
    if not saved:
        raise SelectionError("no previous connection to restore; connect once first")
    return saved.get("country"), saved.get("server")


def _entry_for(logical):
    entries = logical.wireguard_entries
    if not entries:
        raise TunnelError("%s exposes no WireGuard entry" % logical.display_name())
    return sorted(entries, key=lambda entry: entry.name)[0]


def _register(api_client, keys):
    if api_client is None:
        return "skipped (offline)"
    try:
        api_client.register_key(keys["ed25519"])
        return "registered"
    except ProtonxError as error:
        return "unregistered (%s)" % error


def bypass_source(options):
    return system.ssh_source() if options.ssh_guard and system.IS_LINUX else None


def tunnel_settings(keys, entry, options):
    return wireguard.config(
        private_key=keys.x25519_priv_b64,
        peer_public_key=entry.x25519,
        endpoint_host=entry.endpoint_host,
        port=entry.port,
        dns=wireguard.DEFAULT_DNS if options.dns else None,
        mtu=options.mtu,
        allowed_ips=options.allowed_ips,
        bypass_source=bypass_source(options),
    )


def _record(logical, settings):
    return {
        "country": logical.exit_country,
        "server": logical.name,
        "label": logical.display_name(),
        "city": logical.city or logical.exit_country,
        "endpoint": wireguard.describe(settings),
        "tier": "free" if logical.free else "plus",
        "load": logical.load,
        "connected_at": int(time.time()),
    }


def connect(logical, api_client, options, dry_run=False):
    keys = identity.load_or_create()
    settings = tunnel_settings(keys, _entry_for(logical), options)
    record = _record(logical, settings)
    if dry_run:
        return dict(record, ok=True, dry_run=True, dns=settings["dns"], config=wireguard.preview(settings))
    registration = _register(api_client, identity.public_keys(keys))
    report = wireguard.up(settings)
    if not report.get("up"):
        raise TunnelError("the helper did not report an active tunnel")
    state.save(record)
    return dict(
        record,
        ok=True,
        interface=report.get("interface"),
        address=report.get("address"),
        identity=keys.x25519_pub_b64[:16],
        registration=registration,
        ssh_guard=settings.get("bypass_source"),
    )


def disconnect():
    report = wireguard.down()
    return {"ok": True, "up": report.get("up", False), "server": state.load()}


def status():
    report = wireguard.status()
    peer = (report.get("peers") or [None])[0]
    return {
        "ok": True,
        "up": report.get("up", False),
        "interface": report.get("interface"),
        "address": report.get("address"),
        "peer": peer,
        "server": state.load(),
        "ssh_guard": report.get("bypass_source"),
    }


def handshake_age(peer):
    stamp = (peer or {}).get("latest_handshake") or 0
    return max(0, int(time.time()) - stamp) if stamp else None


def _session_check():
    session = login.current()
    if not session:
        return ("session", "not signed in", False)
    try:
        auth.make_client(session, persist=False).client_config()
        return ("session", "%s, plan %s" % (session.get("username", "?"), tier_label(tier(session))), True)
    except ProtonxError as error:
        return ("session", str(error), False)
    except NETWORK_ERRORS:
        return ("session", "could not reach Proton", False)


def _wireguard_check():
    if system.IS_WINDOWS:
        found = wireguard.available()
        return ("wireguard", "installed" if found else "missing (winget install WireGuard.WireGuard)", found)
    found = shutil.which("wg-quick", path=TOOL_PATH)
    return ("wireguard", found or "wg-quick missing", bool(found))


def _tunnel_check():
    if system.IS_WINDOWS:
        return ("admin", "yes" if system.is_admin() else "no (needed to connect)", system.is_admin())
    from . import helper

    return ("helper", helper.SOCKET_PATH if helper.available() else "not installed", helper.available())


def health_checks():
    try:
        import cryptography

        crypto = ("cryptography", cryptography.__version__, True)
    except ImportError:
        crypto = ("cryptography", "missing", False)
    return [
        ("system", system.name(), True),
        ("python", sys.version.split()[0], sys.version_info >= (3, 9)),
        crypto,
        _wireguard_check(),
        _tunnel_check(),
        _session_check(),
    ]
