import argparse
import getpass
import json
import sys
from urllib.error import URLError

from . import __version__, catalog, login, recovery, selection, service, wireguard
from .countries import NAMES
from .errors import ProtonxError, SessionExpired, SessionMissing, TunnelError


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
    return service.client(offline=getattr(args, "offline", False), persist=not args.no_persist)


def _pool(args, client=None):
    offline = getattr(args, "offline", False)
    return service.load_pool(offline=offline, api_client=client, persist=not args.no_persist)[0]


def _options(args):
    return service.ConnectOptions(
        paid=getattr(args, "paid", False),
        p2p=getattr(args, "p2p", False),
        dns=not getattr(args, "no_dns", False),
        ssh_guard=not getattr(args, "no_ssh_guard", False),
        mtu=getattr(args, "mtu", wireguard.DEFAULT_MTU),
        allowed_ips=getattr(args, "allowed_ips", wireguard.ALLOWED_IPS),
    )


def cmd_doctor(args):
    checks = service.health_checks()
    healthy = all(ok for _, _, ok in checks)
    if args.json:
        _emit([{"name": name, "value": value, "ok": ok} for name, value, ok in checks])
        return 0 if healthy else 1
    for name, value, ok in checks:
        print("[%s] %-13s %s" % ("ok" if ok else "!!", name, value))
    return 0 if healthy else 1


def _read_password(from_stdin):
    if from_stdin or not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("Proton password: ")


def _report_login(outcome, as_json):
    if outcome["status"] == "two-factor":
        if as_json:
            _emit({"ok": True, "status": "two-factor", "username": outcome.get("username")})
        else:
            print("two-factor code required: protonx login --two-factor CODE")
        return 0
    tier = service.tier(login.current() or {})
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
    print("signed in as %s · plan %s" % (outcome.get("username"), service.tier_label(tier)))
    return 0


def cmd_login(args):
    if args.two_factor_stdin:
        return _report_login(login.finish_two_factor(sys.stdin.readline().strip()), args.json)
    if args.two_factor:
        return _report_login(login.finish_two_factor(args.two_factor), args.json)
    username = args.username or service.default_username()
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
    payload = service.account(remote=not args.local)
    if args.json:
        _emit(payload)
        return 0
    if payload["signedIn"]:
        print("%s · plan %s" % (payload.get("username"), service.tier_label(payload.get("tier"))))
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
    found = service.servers_in(pool, country, _options(args))
    rows = [
        {
            "name": item.display_name(),
            "city": item.city or "-",
            "load": item.load,
            "tier": "free" if item.free else "plus",
            "ports": sorted({entry.port for entry in item.wireguard_entries}),
        }
        for item in found
    ]
    if args.json:
        _emit(rows)
        return 0
    _print_table(
        [(row["name"], row["city"], row["load"], row["tier"], ",".join(str(port) for port in row["ports"])) for row in rows],
        ("SERVER", "CITY", "LOAD", "TIER", "PORT"),
    )
    return 0


def _print_plan(payload):
    print("server    %s (%s)" % (payload["label"], payload["city"]))
    print("endpoint  %s" % payload["endpoint"])
    print("tier      %s · load %s%%" % (payload["tier"], payload["load"]))
    if payload.get("dns"):
        print("dns       %s (set by the helper, restored on disconnect)" % payload["dns"])
    print("\n" + payload["config"])


def cmd_connect(args):
    client = _client(args)
    pool = _pool(args, client)
    country, server = service.last_target() if args.restore else (args.country, args.server)
    options = _options(args)
    logical = service.pick(pool, country, server, options, randomly=args.random)
    payload = service.connect(logical, client, options, dry_run=args.dry_run)
    if args.json:
        _emit(payload)
        return 0
    if args.dry_run:
        _print_plan(payload)
        return 0
    print("server    %s (%s)" % (payload["label"], payload["city"]))
    print("endpoint  %s" % payload["endpoint"])
    print("tunnel    up · %s · %s%s" % (payload.get("interface"), payload.get("address"), " · retried" if payload.get("retried") else ""))
    print("identity  %s... %s" % (payload["identity"], payload["registration"]))
    if payload.get("ssh_guard"):
        print("ssh       replies from %s stay outside the tunnel" % payload["ssh_guard"])
    return 0


def cmd_disconnect(args):
    payload = service.disconnect()
    if args.json:
        _emit(payload)
        return 0
    print("tunnel    down")
    for warning in payload.get("warnings", []):
        print("warning   %s" % warning)
    return 0


def _handshake_text(peer):
    if not peer:
        return "no peer"
    age = service.handshake_age(peer)
    return "no handshake yet" if age is None else "%ds ago" % age


def cmd_status(args):
    payload = service.status()
    saved = payload["server"]
    if args.json:
        _emit(payload)
        return 0
    if not payload["up"]:
        suffix = " · last %s" % saved["label"] if saved else ""
        print("vpn        down" + suffix)
        if (payload.get("dns") or {}).get("stale"):
            print("warning    DNS is still pointed at the VPN. Run: protonx repair")
        return 0
    print("vpn        up · %s" % payload["interface"])
    if saved:
        print("server     %s (%s)" % (saved["label"], saved["city"]))
    print("address    %s" % payload["address"])
    print("handshake  %s" % _handshake_text(payload["peer"]))
    return 0


def cmd_repair(args):
    try:
        payload = service.repair()
    except TunnelError as error:
        return _command_error(args, "%s\n%s" % (error, recovery.manual_hint()), kind="repair")
    if args.json:
        _emit(payload)
        return 0
    dns = payload.get("dns") or {}
    print("tunnel    down")
    print("dns       %s" % ("restored" if not dns.get("stale") else "still stale"))
    print("internet  %s" % ("reachable" if payload.get("internet") else "not reachable"))
    for action in payload.get("actions", []):
        print("  - %s" % action)
    return 0 if payload.get("internet") else 1


def cmd_update(args):
    from . import update as updater

    try:
        status = updater.update(check_only=args.check, assume_yes=args.yes, target="app" if args.app else "cli")
    except updater.UpdateError as error:
        return _command_error(args, str(error), kind="update")
    if args.json:
        _emit(status)
        return 0
    if not status["update"]:
        print("protonx %s is up to date" % status["current"])
    elif status.get("cancelled"):
        print("update cancelled")
    elif status.get("installed"):
        print("updated to protonx %s" % status["latest"])
        print("restart ProtonX if it is running")
    else:
        print("protonx %s is available (current %s)" % (status["latest"], status["current"]))
        print("run protonx update to install it")
    return 0


def cmd_menu(args):
    from . import repl

    return repl.run(persist=not args.no_persist)


def _add_pool_options(parser):
    parser.add_argument("--paid", action="store_true", help="include plus-tier servers")
    parser.add_argument("--p2p", action="store_true", help="require P2P support")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="protonx",
        description="Choose any Proton VPN location that your plan can use. Run without a command for the interactive menu.",
    )
    parser.add_argument("--version", action="version", version="protonx " + __version__)
    parser.add_argument("--no-persist", action="store_true", help="do not write refreshed tokens back")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("menu", help="open the interactive menu (the default with no command)")
    doctor = sub.add_parser("doctor", help="check dependencies, helper and session")
    doctor.add_argument("--json", action="store_true")
    login_parser = sub.add_parser("login", help="sign in to your Proton account once")
    login_parser.add_argument("--username")
    login_parser.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    login_parser.add_argument("--code", help="two-factor code for this same call")
    login_parser.add_argument("--two-factor", dest="two_factor", help="finish a pending sign-in with this code")
    login_parser.add_argument("--two-factor-stdin", action="store_true", help="finish a pending sign-in with a code from stdin")
    login_parser.add_argument("--json", action="store_true")

    logout = sub.add_parser("logout", help="forget the ProtonX session")
    logout.add_argument("--json", action="store_true")

    whoami = sub.add_parser("whoami", help="report whether ProtonX holds a session")
    whoami.add_argument("--local", action="store_true", help="check the local session without network access")
    whoami.add_argument("--json", action="store_true")

    catalog_parser = sub.add_parser("catalog", help="print the free WireGuard catalog as JSON")
    catalog_parser.add_argument("--offline", action="store_true", help="use the cached server list")
    catalog_parser.add_argument("--json", action="store_true")

    listing = sub.add_parser("countries", help="list available countries")
    listing.add_argument("--free", action="store_true", help="only countries with free-tier servers")
    listing.add_argument("--search")
    listing.add_argument("--offline", action="store_true", help="use the cached server list")
    listing.add_argument("--json", action="store_true")

    servers = sub.add_parser("servers", help="list servers in a country, lowest load first")
    servers.add_argument("--country", required=True)
    servers.add_argument("--offline", action="store_true", help="use the cached server list")
    servers.add_argument("--json", action="store_true")
    _add_pool_options(servers)

    connect = sub.add_parser("connect", help="bring up a tunnel, or switch servers if one is already up")
    connect.add_argument("--country")
    connect.add_argument("--server")
    connect.add_argument("--random", action="store_true")
    connect.add_argument("--restore", action="store_true", help="reconnect to the last used server")
    connect.add_argument("--offline", action="store_true", help="use the cached server list")
    connect.add_argument("--dry-run", action="store_true")
    connect.add_argument("--json", action="store_true")
    connect.add_argument("--no-dns", action="store_true", help="keep the system resolver")
    connect.add_argument(
        "--no-ssh-guard", action="store_true", help="on Linux over SSH, also route this SSH session through the tunnel"
    )
    connect.add_argument("--allowed-ips", default=wireguard.ALLOWED_IPS)
    connect.add_argument("--mtu", type=int, default=wireguard.DEFAULT_MTU)
    _add_pool_options(connect)

    disconnect = sub.add_parser("disconnect", help="tear the tunnel down")
    disconnect.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="show tunnel state and the last server")
    status.add_argument("--json", action="store_true")
    repair = sub.add_parser("repair", help="stop the tunnel and restore DNS and internet access")
    repair.add_argument("--json", action="store_true")
    update_parser = sub.add_parser("update", help="check for a newer release and install it")
    update_parser.add_argument("--check", action="store_true", help="only report whether an update is available")
    update_parser.add_argument("--yes", action="store_true", help="install without asking for confirmation")
    update_parser.add_argument("--app", action="store_true", help="update the macOS app instead of the CLI")
    update_parser.add_argument("--json", action="store_true")
    return parser


COMMANDS = {
    "menu": cmd_menu,
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
    "repair": cmd_repair,
    "update": cmd_update,
}


def _command_error(args, message, kind="failed"):
    if getattr(args, "json", False):
        print(json.dumps({"error": message, "kind": kind}), file=sys.stderr)
    else:
        print("error: %s" % message, file=sys.stderr)
    return 2


def _interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        if not _interactive():
            parser.print_help()
            return 2
        args.command = "menu"
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
