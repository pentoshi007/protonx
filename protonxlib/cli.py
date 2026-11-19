import argparse
import getpass
import json
import sys
import time
from urllib.error import URLError

from . import api, auth, catalog, helper, identity, keychain, login, selection, state, wireguard
from .countries import NAMES
from .errors import ProtonxError, SelectionError, SessionExpired, SessionMissing, TunnelError


def _print_table(rows, headers):
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    template = "  ".join("{:<%d}" % width for width in widths)
    print(template.format(*headers))
    print(template.format(*["-" * width for width in widths]))
    for row in rows:
        print(template.format(*[str(cell) for cell in row]))


def _emit(payload):
    print(json.dumps(payload, indent=2))


def _client(args):
    if getattr(args, "offline", False):
        return None
    session = auth.load_session()
    return auth.make_client(session, persist=not args.no_persist)


def _pool(args, client=None):
    if getattr(args, "offline", False):
        return catalog.cached()[0]
    return catalog.live(client or _client(args))[0]


def _session_check():
    session = login.current()
    if not session:
        return ("session", "not signed in - use the sign-in card in ProtonX", False)
    try:
        client = auth.make_client(session, persist=False)
        client.client_config()
        return (
            "session",
            "%s, plan %s" % (session.get("username", "?"), _tier_label(_tier(session))),
            True,
        )
    except ProtonxError as error:
        return ("session", str(error), False)


def _checks():
    try:
        import cryptography

        crypto = ("cryptography", cryptography.__version__, True)
    except ImportError:
        crypto = ("cryptography", "missing", False)
    helper_state = (
        "helper",
        helper.SOCKET_PATH if helper.available() else "not installed",
        helper.available(),
    )
    return [
        ("python", sys.version.split()[0], sys.version_info >= (3, 9)),
        crypto,
        helper_state,
        _session_check(),
    ]


def cmd_doctor(args):
    checks = _checks()
    healthy = all(ok for _, _, ok in checks)
    if args.json:
        _emit([{"name": name, "value": value, "ok": ok} for name, value, ok in checks])
        return 0 if healthy else 1
    for name, value, ok in checks:
        print("[%s] %-13s %s" % ("ok" if ok else "!!", name, value))
    return 0 if healthy else 1


def _default_username():
    session = login.current()
    if session and session.get("username"):
        return session["username"]
    try:
        return keychain.read_json("ProtonVPN", "authCredentials").get("username")
    except ProtonxError:
        return None


def _read_password(from_stdin):
    if from_stdin or not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("Proton password: ")


def _tier(session):
    try:
        users = api.auth_post("/core/v4/users", None, session=session, method="GET")
        user = users.get("User") or {}
        return 0 if not user.get("Subscribed") else None
    except (ProtonxError, URLError, TimeoutError):
        return None


def _tier_label(tier):
    if tier is None:
        return "unknown"
    return "free" if tier == 0 else str(tier)


def _report_login(outcome, as_json):
    if outcome["status"] == "two-factor":
        if as_json:
            _emit({"ok": True, "status": "two-factor", "username": outcome.get("username")})
        else:
            print("two-factor code required: protonx login --two-factor CODE")
        return 0
    tier = _tier(login.current() or {})
    if as_json:
        _emit(
            {
                "ok": True,
                "status": "signed-in",
                "username": outcome.get("username"),
                "scopes": outcome.get("scopes", []),
                "tier": tier,
            }
        )
        return 0
    print("signed in as %s · plan %s" % (outcome.get("username"), _tier_label(tier)))
    return 0


def cmd_login(args):
    if args.two_factor_stdin:
        return _report_login(login.finish_two_factor(sys.stdin.readline().strip()), args.json)
    if args.two_factor:
        return _report_login(login.finish_two_factor(args.two_factor), args.json)
    username = args.username or _default_username()
    if not username:
        print("error: pass --username for the first sign-in", file=sys.stderr)
        return 2
    outcome = login.sign_in(username, _read_password(args.password_stdin), code=args.code)
    return _report_login(outcome, args.json)


def cmd_logout(args):
    login.sign_out()
    if args.json:
        _emit({"ok": True, "status": "signed-out"})
        return 0
    print("signed out")
    return 0


def cmd_whoami(args):
    session = login.current()
    pending = login.pending()
    payload = {"signedIn": bool(session), "pending": pending is not None}
    if session or pending:
        payload["username"] = (session or pending).get("username")
    else:
        payload["username"] = _default_username()
    if session and not args.local:
        payload["tier"] = _tier(session)
    if args.json:
        _emit(payload)
        return 0
    if session:
        print("%s · plan %s" % (payload.get("username"), _tier_label(payload.get("tier"))))
    else:
        print("not signed in")
    return 0


def cmd_catalog(args):
    snapshot = catalog.cached() if args.offline else catalog.live(_client(args))
    _emit(catalog.free_snapshot(*snapshot))
    return 0


def cmd_countries(args):
    pool = _pool(args)
    summary = (selection.eligible(pool) if args.free else pool).countries()
    rows = []
    for code in sorted(summary, key=lambda item: NAMES.get(item, item)):
        bucket = summary[code]
        if args.free and not bucket["free"]:
            continue
        label = NAMES.get(code, code)
        if args.search:
            needle = args.search.lower()
            if needle not in label.lower() and needle != code.lower():
                continue
        rows.append(
            {
                "code": code,
                "name": label,
                "servers": bucket["count"],
                "tier": "free" if bucket["free"] else "plus",
            }
        )
    if args.json:
        _emit(rows)
        return 0
    _print_table(
        [(row["code"], row["name"], row["servers"], row["tier"]) for row in rows],
        ("CODE", "COUNTRY", "SERVERS", "TIER"),
    )
    print("\n%d locations · %d with free-tier servers" % (len(rows), sum(1 for row in rows if row["tier"] == "free")))
    return 0


def cmd_servers(args):
    pool = _pool(args)
    country = selection.resolve_country(pool, args.country)
    found = selection.candidates(pool, country, include_paid=args.paid, p2p_only=args.p2p)
    rows = [
        {
            "name": item.display_name(),
            "city": item.city or "-",
            "load": item.load,
            "tier": "free" if item.free else "plus",
            "ports": sorted({entry.port for entry in item.wireguard_entries}),
        }
        for item in sorted(found, key=lambda item: item.load)
    ]
    if args.json:
        _emit(rows)
        return 0
    _print_table(
        [(row["name"], row["city"], row["load"], row["tier"], ",".join(str(port) for port in row["ports"])) for row in rows],
        ("SERVER", "CITY", "LOAD", "TIER", "PORT"),
    )
    return 0


def _entry_for(logical):
    entries = logical.wireguard_entries
    if not entries:
        raise TunnelError("%s exposes no WireGuard entry" % logical.display_name())
    return sorted(entries, key=lambda entry: entry.name)[0]


def _register(client, keys):
    try:
        client.register_key(keys["ed25519"])
        return "registered"
    except ProtonxError as error:
        return "unregistered (%s)" % error


def _saved_target():
    saved = state.load()
    if not saved:
        raise SelectionError("no previous connection to restore; connect once first")
    return saved.get("country"), saved.get("server")


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


def _target(args):
    if args.restore:
        return _saved_target()
    return args.country, args.server


def _pick(args, pool):
    country_query, server_name = _target(args)
    country = selection.resolve_country(pool, country_query)
    strategy = selection.RANDOM if args.random else selection.FASTEST
    return selection.select(
        pool,
        country=country,
        server=server_name,
        include_paid=args.paid,
        p2p_only=args.p2p,
        strategy=strategy,
    )


def _settings(args, keys, entry):
    return wireguard.config(
        private_key=keys.x25519_priv_b64,
        peer_public_key=entry.x25519,
        endpoint_host=entry.endpoint_host,
        port=entry.port,
        dns=None if args.no_dns else wireguard.DEFAULT_DNS,
        mtu=args.mtu,
        allowed_ips=args.allowed_ips,
    )


def _print_plan(record, settings, config_text):
    print("server    %s (%s)" % (record["label"], record["city"]))
    print("endpoint  %s" % record["endpoint"])
    print("tier      %s · load %s%%" % (record["tier"], record["load"]))
    if settings.get("dns"):
        print("dns       %s (set by the helper, restored on disconnect)" % settings["dns"])
    print("\n" + config_text)


def cmd_connect(args):
    client = _client(args)
    pool = _pool(args, client)
    logical = _pick(args, pool)
    entry = _entry_for(logical)
    keys = identity.load_or_create()
    settings = _settings(args, keys, entry)
    record = _record(logical, settings)
    if args.dry_run:
        text = wireguard.preview(settings)
        if args.json:
            _emit(dict(record, ok=True, dry_run=True, config=text))
        else:
            _print_plan(record, settings, text)
        return 0
    registration = "skipped (offline)" if client is None else _register(client, identity.public_keys(keys))
    report = wireguard.up(settings)
    if not report.get("up"):
        raise TunnelError("the helper did not report an active tunnel")
    state.save(record)
    payload = dict(
        record,
        ok=True,
        interface=report.get("interface"),
        address=report.get("address"),
        identity=keys.x25519_pub_b64[:16],
        registration=registration,
    )
    if args.json:
        _emit(payload)
        return 0
    print("server    %s (%s)" % (record["label"], record["city"]))
    print("endpoint  %s" % record["endpoint"])
    print("tunnel    up · %s · %s" % (report.get("interface"), report.get("address")))
    print("identity  %s... %s" % (payload["identity"], registration))
    return 0


def cmd_disconnect(args):
    report = wireguard.down()
    payload = {"ok": True, "up": report.get("up", False), "server": state.load()}
    if args.json:
        _emit(payload)
        return 0
    print("tunnel    down")
    return 0


def _handshake_text(peer):
    if not peer:
        return "no peer"
    stamp = peer.get("latest_handshake") or 0
    if not stamp:
        return "no handshake yet"
    return "%ds ago" % max(0, int(time.time()) - stamp)


def cmd_status(args):
    report = wireguard.status()
    saved = state.load()
    peer = (report.get("peers") or [None])[0]
    payload = {
        "ok": True,
        "up": report.get("up", False),
        "interface": report.get("interface"),
        "address": report.get("address"),
        "peer": peer,
        "server": saved,
    }
    if args.json:
        _emit(payload)
        return 0
    if not report.get("up"):
        suffix = " · last %s" % saved["label"] if saved else ""
        print("vpn        down" + suffix)
        return 0
    print("vpn        up · %s" % report.get("interface"))
    if saved:
        print("server     %s (%s)" % (saved["label"], saved["city"]))
    print("address    %s" % report.get("address"))
    print("handshake  %s" % _handshake_text(peer))
    return 0


def _add_pool_options(parser):
    parser.add_argument("--paid", action="store_true", help="include plus-tier servers")
    parser.add_argument("--p2p", action="store_true", help="require P2P support")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="protonx", description="Choose any Proton VPN location that your plan can use"
    )
    parser.add_argument("--no-persist", action="store_true", help="do not write refreshed tokens back")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check dependencies, helper and session")
    doctor.add_argument("--json", action="store_true")
    login = sub.add_parser("login", help="sign in to your Proton account once")
    login.add_argument("--username")
    login.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    login.add_argument("--code", help="two-factor code for this same call")
    login.add_argument("--two-factor", dest="two_factor", help="finish a pending sign-in with this code")
    login.add_argument("--two-factor-stdin", action="store_true", help="finish a pending sign-in with a code from stdin")
    login.add_argument("--json", action="store_true")

    logout = sub.add_parser("logout", help="forget the ProtonX session")
    logout.add_argument("--json", action="store_true")

    whoami = sub.add_parser("whoami", help="report whether ProtonX holds a session")
    whoami.add_argument("--local", action="store_true", help="check the local session without network access")
    whoami.add_argument("--json", action="store_true")

    catalog = sub.add_parser("catalog", help="print the free WireGuard catalog as JSON")
    catalog.add_argument("--offline", action="store_true", help="use the cached server list")
    catalog.add_argument("--json", action="store_true")

    listing = sub.add_parser("countries", help="list available countries")
    listing.add_argument("--free", action="store_true", help="only countries with free-tier servers")
    listing.add_argument("--search")
    listing.add_argument("--offline", action="store_true", help="use the cached server list")
    listing.add_argument("--json", action="store_true")

    servers = sub.add_parser("servers", help="list servers in a country")
    servers.add_argument("--country", required=True)
    servers.add_argument("--offline", action="store_true", help="use the cached server list")
    servers.add_argument("--json", action="store_true")
    _add_pool_options(servers)

    connect = sub.add_parser("connect", help="bring up a tunnel")
    connect.add_argument("--country")
    connect.add_argument("--server")
    connect.add_argument("--random", action="store_true")
    connect.add_argument("--restore", action="store_true", help="reconnect to the last used server")
    connect.add_argument("--offline", action="store_true", help="use the cached server list")
    connect.add_argument("--dry-run", action="store_true")
    connect.add_argument("--json", action="store_true")
    connect.add_argument("--no-dns", action="store_true")
    connect.add_argument("--allowed-ips", default=wireguard.ALLOWED_IPS)
    connect.add_argument("--mtu", type=int, default=wireguard.DEFAULT_MTU)
    _add_pool_options(connect)

    disconnect = sub.add_parser("disconnect", help="tear the tunnel down")
    disconnect.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="show tunnel state and the last server")
    status.add_argument("--json", action="store_true")
    return parser


COMMANDS = {
    "doctor": cmd_doctor,
    "login": cmd_login,
    "logout": cmd_logout,
    "whoami": cmd_whoami,
    "catalog": cmd_catalog,
    "countries": cmd_countries,
    "servers": cmd_servers,
    "connect": cmd_connect,
    "disconnect": cmd_disconnect,
    "status": cmd_status,
}


def _command_error(args, message, kind="failed"):
    if args.json:
        print(json.dumps({"error": message, "kind": kind}), file=sys.stderr)
    else:
        print("error: %s" % message, file=sys.stderr)
    return 2


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (SessionMissing, SessionExpired) as error:
        return _command_error(args, str(error), kind="session")
    except (URLError, TimeoutError):
        return _command_error(args, "Could not reach Proton. Check your connection and try again.", kind="network")
    except (ProtonxError, OSError) as error:
        return _command_error(args, str(error))
    except KeyboardInterrupt:
        return 130
