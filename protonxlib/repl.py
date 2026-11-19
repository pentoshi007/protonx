import time
from urllib.error import URLError

from . import __version__, cache, catalog, login, preferences, service, state, system, term, wireguard
from .countries import name as country_name
from .errors import ApiError, CatalogUnavailable, ProtonxError, SessionExpired, SessionMissing
from .term import Back, Choice

POOL_TTL = cache.DEFAULT_TTL
WRONG_PASSWORD = 8002


def _bytes(count):
    value = float(count or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return ("%d %s" % (value, unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024


def _duration(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    if minutes:
        return "%dm %02ds" % (minutes, seconds)
    return "%ds" % seconds


def _load_badge(load):
    return "%3d%% load" % max(0, min(100, load))


def _joined(*parts):
    return (" %s " % term.symbol("sep")).join(str(part) for part in parts if part)


def _place(record):
    city = record.get("city")
    code = record.get("country") or ""
    return "%s, %s" % (city, country_name(code)) if city and city != code else country_name(code)


class Menu:
    def __init__(self, persist=True):
        self.persist = persist
        self.options = preferences.load()
        self.pool = None
        self.pool_at = 0
        self.tunnel = {}

    def run(self):
        self._banner()
        try:
            while True:
                if login.current():
                    action = self._home()
                else:
                    action = self._welcome()
                if action is None:
                    break
                self._attempt(action)
        except KeyboardInterrupt:
            term.say()
        self._farewell()
        return 0

    def _banner(self):
        term.say()
        term.say("%s %s" % (term.paint("ProtonX", "bold", "magenta"), term.paint(__version__, "dim")))
        if term.PLAIN:
            term.note("Type the number of an option and press Enter. Ctrl+C quits; the VPN keeps its state.")
        else:
            term.note("Pick with the arrow keys and Enter. Esc goes back. Ctrl+C quits; the VPN keeps its state.")

    def _farewell(self):
        if self.tunnel.get("up"):
            term.note("Bye. The VPN stays connected; run protonx again to disconnect or switch.")
        else:
            term.note("Bye.")

    def _attempt(self, action):
        try:
            action()
        except Back:
            pass
        except KeyboardInterrupt:
            term.say()
            term.note("Cancelled.")
        except SessionExpired as error:
            term.failure("Your Proton session expired, please sign in again. (%s)" % error)
            self._forget_session()
        except SessionMissing as error:
            term.failure(str(error))
        except (URLError, TimeoutError):
            term.failure("Could not reach Proton. Check your internet connection and try again.")
        except (ProtonxError, OSError) as error:
            term.failure(str(error))

    def _forget_session(self):
        try:
            login.sign_out()
        except ProtonxError as error:
            term.failure(str(error))

    def _refresh_tunnel(self):
        try:
            self.tunnel = service.status()
            self.tunnel["error"] = None
        except (ProtonxError, OSError) as error:
            self.tunnel = {"up": False, "server": state.load(), "error": str(error)}
        return self.tunnel

    def _status_lines(self):
        tunnel = self._refresh_tunnel()
        saved = tunnel.get("server")
        if tunnel.get("up"):
            parts = [saved["label"], _place(saved)] if saved else []
            if tunnel.get("address"):
                parts.append(tunnel["address"])
            if saved and saved.get("connected_at"):
                parts.append("for " + _duration(time.time() - saved["connected_at"]))
            marker = term.paint(term.symbol("dot"), "green")
            line = "%s %s  %s" % (marker, term.paint("Connected", "green", "bold"), _joined(*parts))
        else:
            suffix = term.paint("  last: %s" % saved["label"], "dim") if saved else ""
            line = "%s %s%s" % (term.paint(term.symbol("ring"), "dim"), term.paint("Disconnected", "bold"), suffix)
        lines = [line]
        if tunnel.get("error"):
            lines.append(term.paint("! %s" % tunnel["error"], "yellow"))
        return lines

    def _header(self):
        term.say()
        session = login.current() or {}
        term.note("Signed in as %s" % session.get("username", "?"))
        for line in self._status_lines():
            term.say(line)
        term.say()

    def _welcome(self):
        term.say()
        term.say("%s %s" % (term.paint(term.symbol("ring"), "dim"), term.paint("Not signed in", "bold")))
        term.note("Sign in once with your Proton account. Your password is never stored.")
        term.say()
        choices = []
        if login.pending():
            choices.append(Choice("Enter two-factor code", self._two_factor, "finish the sign-in you started"))
        choices += [
            Choice("Sign in", self._sign_in, "Proton username or email and password"),
            Choice("Check setup", self._doctor, "dependencies, helper and network"),
            Choice("Exit", None),
        ]
        return term.select("What do you want to do?", choices, allow_back=False, searchable=False)

    def _home(self):
        self._header()
        up = self.tunnel.get("up")
        last = self.tunnel.get("server")
        choices = []
        if up:
            choices += [
                Choice("Disconnect", self._disconnect, "turn the VPN off"),
                Choice("Switch server", self._browse, "pick another country or server"),
                Choice("Switch to the fastest server", self._fastest, "lowest load anywhere"),
                Choice("Connection details", self._details, "live handshake and traffic"),
            ]
        else:
            if last:
                choices.append(Choice("Reconnect to %s" % last["label"], self._reconnect, _place(last)))
            choices += [
                Choice("Connect to the fastest server", self._fastest, "lowest load anywhere"),
                Choice("Choose a country", self._browse, "browse countries, servers and load"),
            ]
        choices += [
            Choice("Settings", self._settings, self._settings_summary()),
            Choice("Account", self._account, "plan, sign out"),
            Choice("Check setup", self._doctor, "dependencies, helper and session"),
            Choice("Exit", None, "the VPN stays connected" if up else ""),
        ]
        return term.select("What do you want to do?", choices, allow_back=False, searchable=False)

    def _sign_in(self):
        username = term.ask("Proton username or email", default=service.default_username())
        password = term.ask("Password", secret=True)
        try:
            with term.spinner("Signing in (this takes a few seconds)"):
                outcome = login.sign_in(username, password)
        except ApiError as error:
            if error.code == WRONG_PASSWORD:
                raise ProtonxError("Wrong username or password.") from error
            raise
        if outcome["status"] == "two-factor":
            term.note("Your account uses two-factor authentication.")
            self._two_factor()
            return
        term.success("Signed in as %s" % outcome.get("username"))

    def _two_factor(self):
        code = term.ask("Two-factor code from your authenticator app")
        with term.spinner("Checking the code"):
            outcome = login.finish_two_factor(code.replace(" ", ""))
        term.success("Signed in as %s" % outcome.get("username"))

    def _account(self):
        session = login.current() or {}
        with term.spinner("Checking your plan"):
            plan = service.tier_label(service.tier(session))
        term.say("  Account  %s" % term.paint(session.get("username", "?"), "bold"))
        term.say("  Plan     %s" % plan)
        choices = [
            Choice("Sign out", "out", "forget the session on this machine"),
            Choice("Back", None),
        ]
        if term.select("Account", choices) != "out":
            return
        if not term.confirm("Sign out of %s?" % session.get("username", "Proton"), default=False):
            return
        login.sign_out()
        term.success("Signed out. The VPN state was not changed.")

    def _servers(self, force=False):
        if self.pool is not None and not force and time.time() - self.pool_at < POOL_TTL:
            return self.pool
        try:
            with term.spinner("Fetching the server list"):
                self.pool, self.pool_at = service.load_pool(persist=self.persist)
        except (SessionMissing, SessionExpired):
            raise
        except (URLError, TimeoutError, ProtonxError) as error:
            try:
                self.pool, self.pool_at = catalog.cached()
            except CatalogUnavailable:
                raise error
            age = _duration(time.time() - self.pool_at)
            term.note("Proton could not be reached; using the saved server list from %s ago." % age)
        return self.pool

    def _connect(self, logical):
        verb = "Switching to" if self.tunnel.get("up") else "Connecting to"
        with term.spinner("%s %s" % (verb, logical.display_name())):
            payload = service.connect(logical, service.client(persist=self.persist), self.options)
        term.success("Connected to " + _joined(term.paint(payload["label"], "bold"), _place(payload), payload.get("address")))
        if payload.get("ssh_guard"):
            term.note("  Your SSH session to %s stays outside the tunnel, so it will not drop." % payload["ssh_guard"])
        elif system.IS_LINUX and system.ssh_source():
            term.note("  SSH guard is off in Settings; this SSH session may drop.")

    def _fastest(self):
        pool = self._servers()
        self._connect(service.pick(pool, None, None, self.options))

    def _reconnect(self):
        country, server = service.last_target()
        pool = self._servers()
        self._connect(service.pick(pool, country, server, self.options))

    def _browse(self):
        while True:
            pool = self._servers()
            rows = service.destinations(pool, self.options)
            if not rows:
                raise ProtonxError("No servers match your settings. Turn off 'P2P only' or check your plan.")
            choices = [Choice("Fastest country", "fastest", "lowest load anywhere", tone="magenta")]
            choices += [
                Choice(
                    row["name"],
                    row["code"],
                    _joined(row["code"], "%d server%s" % (row["servers"], "" if row["servers"] == 1 else "s")),
                    badge="best %3d%%" % row["best_load"],
                    badge_tone=term.load_tone(row["best_load"]),
                    keywords=row["code"],
                )
                for row in rows
            ]
            choices.append(Choice("Refresh the server list", "refresh", "download it again", tone="dim"))
            picked = term.select("Choose a country (%d available)" % len(rows), choices, searchable=True)
            if picked == "refresh":
                self._servers(force=True)
                continue
            if picked == "fastest":
                self._connect(service.pick(pool, None, None, self.options))
                return
            try:
                self._choose_server(pool, picked)
                return
            except Back:
                continue

    def _choose_server(self, pool, country):
        found = service.servers_in(pool, country, self.options)
        best = found[0]
        current = (self.tunnel.get("server") or {}).get("server") if self.tunnel.get("up") else None
        choices = [
            Choice(
                "Fastest in %s" % country_name(country),
                best,
                "currently %s" % best.display_name(),
                badge=_load_badge(best.load),
                badge_tone=term.load_tone(best.load),
                tone="magenta",
            )
        ]
        for item in found:
            details = [item.city or country]
            if not item.free:
                details.append("plus")
            if item.p2p:
                details.append("p2p")
            if item.name == current:
                details.append("connected")
            choices.append(
                Choice(
                    item.display_name(),
                    item,
                    _joined(*details),
                    badge=_load_badge(item.load),
                    badge_tone=term.load_tone(item.load),
                    keywords=item.city,
                )
            )
        logical = term.select("Choose a server in %s (lowest load first)" % country_name(country), choices)
        self._connect(logical)

    def _disconnect(self):
        with term.spinner("Disconnecting"):
            service.disconnect()
        term.success("Disconnected. Your normal connection is back.")

    def _details_lines(self):
        try:
            tunnel = service.status()
        except (ProtonxError, OSError) as error:
            return [term.paint("! %s" % error, "yellow")]
        saved = tunnel.get("server") or {}
        rows = []
        if tunnel.get("up"):
            rows.append(("Status", term.paint("%s Connected" % term.symbol("dot"), "green", "bold")))
        else:
            rows.append(("Status", term.paint("%s Disconnected" % term.symbol("ring"), "bold")))
        if saved:
            rows.append(("Server", _joined(saved.get("label"), _place(saved))))
            rows.append(("Endpoint", saved.get("endpoint", "-")))
            rows.append(("Load", "%s%% when connected" % saved.get("load", "?")))
        if tunnel.get("up"):
            peer = tunnel.get("peer") or {}
            age = service.handshake_age(peer)
            rows.append(("Interface", _joined(tunnel.get("interface"), tunnel.get("address"))))
            rows.append(("Handshake", "waiting" if age is None else "%s ago" % _duration(age)))
            if peer:
                rows.append(("Traffic", _joined(_bytes(peer.get("rx_bytes")) + " down", _bytes(peer.get("tx_bytes")) + " up")))
            if saved.get("connected_at"):
                rows.append(("Uptime", _duration(time.time() - saved["connected_at"])))
            if tunnel.get("ssh_guard"):
                rows.append(("SSH guard", "replies from %s bypass the tunnel" % tunnel["ssh_guard"]))
        return ["  %s  %s" % (term.paint(label.ljust(10), "dim"), value) for label, value in rows]

    def _details(self):
        term.live(self._details_lines)

    def _settings_summary(self):
        active = []
        if self.options.paid:
            active.append("plus servers")
        if self.options.p2p:
            active.append("p2p only")
        if not self.options.dns:
            active.append("system DNS")
        return ", ".join(active) if active else "server filters, DNS"

    def _settings(self):
        toggles = [
            ("paid", "Show Plus servers", "only usable with a paid Proton plan"),
            ("p2p", "P2P servers only", "servers that allow file sharing"),
            ("dns", "Use Proton DNS", "recommended; stops DNS leaks"),
        ]
        if system.IS_LINUX:
            toggles.append(("ssh_guard", "SSH guard", "keep the SSH session you are using reachable"))
        while True:
            choices = [
                Choice(
                    label,
                    key,
                    detail,
                    badge="on " if getattr(self.options, key) else "off",
                    badge_tone="green" if getattr(self.options, key) else "dim",
                )
                for key, label, detail in toggles
            ]
            choices.append(Choice("Back", None))
            key = term.select("Settings (Enter toggles; applies to the next connection)", choices, searchable=False)
            if key is None:
                return
            setattr(self.options, key, not getattr(self.options, key))
            preferences.save(self.options)

    def _doctor(self):
        with term.spinner("Checking"):
            checks = service.health_checks()
        for name, value, ok in checks:
            mark = term.paint(term.symbol("ok"), "green") if ok else term.paint(term.symbol("fail"), "red")
            term.say("  %s %s %s" % (mark, name.ljust(13), value))
        if not wireguard.available():
            term.note("  The tunnel backend is missing. Re-run the protonx installer for %s." % system.name())
        term.pause()


def run(persist=True):
    return Menu(persist=persist).run()
