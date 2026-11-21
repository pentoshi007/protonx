import AppKit
import Foundation

private let nl = Destination(country: "NL", server: "NL-FREE#1")
private let us = Destination(country: "US", server: "US-FREE#1")
private let signedIn = Account(signedIn: true, username: "tester", pending: false)
private let signedOut = Account(signedIn: false, username: nil, pending: false)

private func sample(fresh: Bool = true) -> Catalog {
    Catalog(fetchedAt: fresh ? Date().timeIntervalSince1970 : 1, countries: [
        Country(code: "NL", name: "Netherlands", servers: [Server(name: nl.server, city: "Amsterdam", load: 12)]),
        Country(code: "US", name: "United States", servers: [Server(name: us.server, city: "Seattle", load: 8)]),
    ])
}

private func snapshot(_ target: Destination? = nil) -> Status {
    let server = target.map { LastServer(country: $0.country, server: $0.server, label: $0.server, city: "Test", connectedAt: nil) }
    return Status(up: server != nil, interface: server.map { _ in "utun1" }, address: nil, peer: nil, server: server, dns: nil, flowError: nil)
}

private final class StubEngine: EngineAccess, @unchecked Sendable {
    let accountReply: @Sendable () throws -> Account
    let local: Catalog?
    let live: @Sendable () throws -> Catalog
    let connectGate: DispatchSemaphore?
    let disconnectError: EngineError?
    let repairReply: @Sendable () throws -> RepairReport
    private let lock = NSLock()
    private var connected: Destination?
    private var record: [String] = []

    init(account: @escaping @Sendable () throws -> Account = { signedIn }, local: Catalog? = nil,
         live: @escaping @Sendable () throws -> Catalog = { sample() }, connected: Destination? = nil,
         connectGate: DispatchSemaphore? = nil, disconnectError: EngineError? = nil,
         repairReply: @escaping @Sendable () throws -> RepairReport = {
             RepairReport(ok: true, actions: ["flushed the DNS cache"], resolves: true, internet: true, dns: nil)
         }) {
        self.accountReply = account
        self.local = local
        self.live = live
        self.connected = connected
        self.connectGate = connectGate
        self.disconnectError = disconnectError
        self.repairReply = repairReply
    }

    var calls: [String] { lock.withLock { record } }

    func account() throws -> Account {
        lock.withLock { record.append("account") }
        return try accountReply()
    }

    func catalog(offline: Bool) throws -> Catalog {
        lock.withLock { record.append(offline ? "cache" : "live") }
        if !offline { return try live() }
        guard let local else { throw EngineError("missing cache") }
        return local
    }

    func status() -> Status {
        lock.withLock {
            record.append("status")
            return snapshot(connected)
        }
    }

    func connect(_ target: Destination) {
        lock.withLock { record.append("connect:\(target.server)") }
        _ = connectGate?.wait(timeout: .now() + 2)
        lock.withLock { connected = target }
    }

    func disconnect() throws {
        lock.withLock { record.append("disconnect") }
        if let disconnectError { throw disconnectError }
        lock.withLock { connected = nil }
    }

    func signOut() { lock.withLock { record.append("logout") } }
    func signIn(username: String, password: String) -> SignInResult { SignInResult(status: "two-factor", username: username) }
    func submitTwoFactor(_ code: String) -> SignInResult { SignInResult(status: "signed-in", username: "tester") }
    func updateCheck() -> UpdateStatus { UpdateStatus(current: "1.1.0", latest: "1.1.0", update: false) }

    func repair() throws -> RepairReport {
        lock.withLock { record.append("repair") }
        return try repairReply()
    }
}

@main @MainActor
private enum StateTests {
    static func main() async throws {
        _ = NSApplication.shared
        try await restoredSessionStaysInCheckState()
        try await absentAndUnavailableSessionsDiffer()
        try await cacheEnablesInstantBrowsingWhileRefreshWaits()
        try await coldLoadDistinguishesWaitingFromEmptyAndFailure()
        try await switchUsesOneMutationAndResumesPolling()
        try await signOutDisconnectsBeforeRemovingSession()
        try await failedDisconnectPreventsLogout()
        try await repairRestoresNetworkAndRefreshesStatus()
        savedServersPersistAndSearchUsesServerData()
        saveControlTogglesThroughTheButton()
        try await searchControlFiltersTheTable()
        print("11 ProtonX state scenarios passed")
    }

    static func restoredSessionStaysInCheckState() async throws {
        let gate = DispatchSemaphore(value: 0)
        let engine = StubEngine(account: {
            _ = gate.wait(timeout: .now() + 2)
            return signedIn
        }, local: sample())
        let state = AppState(engine: engine)
        state.start()
        state.setVisible(true)
        require(state.session == .checking, "unknown account cannot be signed out")
        gate.signal()
        try await until { state.session == .ready(signedIn) && state.catalogPhase == .current }
        require(!engine.calls.contains("live"), "fresh disk catalog should skip network")
        state.setVisible(false)
        require(state.pollingInterval == nil, "idle background cannot poll")
    }

    static func absentAndUnavailableSessionsDiffer() async throws {
        let missing = AppState(engine: StubEngine(account: { signedOut }))
        let failed = AppState(engine: StubEngine(account: { throw EngineError("keychain unavailable") }))
        missing.start()
        failed.start()
        try await until {
            missing.session == .ready(signedOut) && failed.session == .unavailable("keychain unavailable")
        }
        require(missing.catalogPhase == .idle, "no authenticated catalog request while signed out")
    }

    static func cacheEnablesInstantBrowsingWhileRefreshWaits() async throws {
        let gate = DispatchSemaphore(value: 0)
        let engine = StubEngine(local: sample(fresh: false), live: {
            _ = gate.wait(timeout: .now() + 2)
            throw EngineError("offline", kind: "network")
        })
        let state = AppState(engine: engine)
        state.start()
        state.setVisible(true)
        try await until { state.catalogPhase == .refreshing }
        require(state.server(for: nl)?.load == 12 && state.server(for: us)?.city == "Seattle", "navigation must read from the same cache")
        state.refresh()
        gate.signal()
        try await until { state.catalogPhase == .saved("offline") }
        require(state.catalog?.bestDestination(in: nil) == us, "best server uses smallest reported load")
        require(engine.calls.filter { $0 == "live" }.count == 1, "duplicate refresh should coalesce")
        require(state.session.signedIn, "network failure is not an expired session")
    }

    static func coldLoadDistinguishesWaitingFromEmptyAndFailure() async throws {
        let gate = DispatchSemaphore(value: 0)
        let empty = AppState(engine: StubEngine(live: {
            _ = gate.wait(timeout: .now() + 2)
            return Catalog(fetchedAt: 1, countries: [])
        }))
        empty.start()
        empty.setVisible(true)
        try await until { empty.catalogPhase == .refreshing && empty.catalog == nil }
        gate.signal()
        try await until { empty.catalogPhase == .current && empty.catalog?.countries.isEmpty == true }
        let failed = AppState(engine: StubEngine(live: { throw EngineError("offline") }))
        failed.start()
        failed.setVisible(true)
        try await until { failed.catalogPhase == .unavailable("offline") }
        require(failed.catalog == nil, "no cache after refresh failure")
        let expired = AppState(engine: StubEngine(live: { throw EngineError("revoked", kind: "session") }))
        expired.start()
        expired.setVisible(true)
        try await until { expired.notice?.contains("expired") == true }
        require(!expired.session.signedIn, "definite server rejection requires sign-in")
    }

    static func switchUsesOneMutationAndResumesPolling() async throws {
        let gate = DispatchSemaphore(value: 0)
        let engine = StubEngine(local: sample(), connected: nl, connectGate: gate)
        let state = AppState(engine: engine)
        state.start()
        try await until { state.activeDestination == nl && state.catalog != nil }
        require(state.pollingInterval == 60, "connected background uses relaxed polling")
        state.setVisible(true)
        require(state.pollingInterval == 12, "visible tunnel has live metrics")
        state.connect(nl)
        require(state.operation == nil, "active server cannot be re-selected")
        state.connect(us)
        state.disconnect()
        state.connect(nl)
        require(state.operation == .switching(us) && state.pollingInterval == nil, "switch holds one writer and pauses polling")
        gate.signal()
        try await until { state.operation == nil && state.activeDestination == us }
        require(engine.calls.filter { $0.hasPrefix("connect:") } == ["connect:\(us.server)"], "one explicit target, no duplicate mutation")
        state.disconnect()
        try await until { state.status?.up == false && state.operation == nil }
        require(state.pollingInterval == nil, "disconnect stops periodic work")
    }

    static func signOutDisconnectsBeforeRemovingSession() async throws {
        let engine = StubEngine(local: sample(), connected: nl)
        let state = AppState(engine: engine)
        state.start()
        try await until { state.canSignOut && state.isUp }
        state.signOut()
        require(state.operation == .signingOut, "logout is in progress before touching the session")
        try await until { state.session == .ready(signedOut) }
        require(engine.calls.filter { $0 == "disconnect" || $0 == "logout" } == ["disconnect", "logout"], "disconnect before logout")
        require(!state.isUp && state.catalog == nil, "signed-out state cannot expose a stale active route")
    }

    static func failedDisconnectPreventsLogout() async throws {
        let engine = StubEngine(local: sample(), connected: nl, disconnectError: EngineError("could not disconnect"))
        let state = AppState(engine: engine)
        state.start()
        try await until { state.canSignOut && state.isUp }
        state.signOut()
        try await until { state.notice == "could not disconnect" }
        require(state.session.signedIn && state.isUp && !engine.calls.contains("logout"), "failed disconnect protects the live session")
    }

    static func repairRestoresNetworkAndRefreshesStatus() async throws {
        let engine = StubEngine(local: sample(), connected: nl)
        let state = AppState(engine: engine)
        state.start()
        try await until { state.isUp && state.catalog != nil }
        state.repair()
        require(state.operation == .repairing, "repair holds the tunnel writer")
        try await until { state.operation == nil && state.notice?.contains("repaired") == true }
        require(engine.calls.contains("repair"), "repair command ran")
        require(state.notice?.contains("internet reachable") == true, "repair reports connectivity")
    }

    static func savedServersPersistAndSearchUsesServerData() {
        let suite = "ProtonX.Test.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else { exit(1) }
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(engine: StubEngine(), defaults: defaults)
        state.toggleSaved(nl)
        let restored = AppState(engine: StubEngine(), defaults: defaults)
        require(restored.savedRoutes == [nl], "pin survives relaunch")
        let city = DirectoryInput(page: .locations, catalog: sample(), saved: restored.savedRoutes, query: "amsterdam")
        require(city.rows == [.server(nl, location: "Netherlands", data: sample().country("NL")?.servers.first)], "global city search finds server")
        let unavailable = DirectoryInput(page: .saved, catalog: nil, saved: restored.savedRoutes, query: "NL-FREE#1")
        require(unavailable.rows.count == 1, "a missing catalog keeps pins available for removal")
        restored.toggleSaved(nl)
        require(AppState(engine: StubEngine(), defaults: defaults).savedRoutes.isEmpty, "unpin persists")
    }

    static func saveControlTogglesThroughTheButton() {
        let defaults = UserDefaults(suiteName: "StateTests.saveControl")!
        defaults.removePersistentDomain(forName: "StateTests.saveControl")
        let state = AppState(engine: StubEngine(), defaults: defaults)
        let cell = DirectoryCell(frame: NSRect(x: 0, y: 0, width: 460, height: 44))
        cell.render(.server(nl, location: "Netherlands", data: sample().country("NL")?.servers.first), state: state)
        guard let star = findButton(in: cell, width: 30) else {
            require(false, "save control is missing from the server row")
            return
        }
        star.performClick(nil)
        require(state.savedRoutes == [nl], "star control saves the server")
        require(AppState(engine: StubEngine(), defaults: defaults).savedRoutes == [nl], "star control persists")
        star.performClick(nil)
        require(state.savedRoutes.isEmpty, "star control removes the server")
    }

    static func searchControlFiltersTheTable() async throws {
        let state = AppState(engine: StubEngine(local: sample()))
        state.start()
        state.setVisible(true)
        try await until { state.catalog != nil }
        let view = DirectoryView(state: state, page: .country("NL"))
        view.frame = NSRect(x: 0, y: 0, width: 460, height: 400)
        view.render(presented: true)
        guard let field = findSearchField(in: view), let table = findTable(in: view) else {
            require(false, "search field or table is missing")
            return
        }
        require(table.numberOfRows == 1, "country page starts with every server")
        field.stringValue = "tokyo"
        field.sendAction(field.action, to: field.target)
        require(table.numberOfRows == 0, "search hides non-matching servers")
        field.stringValue = "amsterdam"
        field.sendAction(field.action, to: field.target)
        require(table.numberOfRows == 1, "search matches the city")
    }

    static func findSearchField(in view: NSView) -> NSSearchField? {
        if let field = view as? NSSearchField { return field }
        for child in view.subviews {
            if let found = findSearchField(in: child) { return found }
        }
        return nil
    }

    static func findTable(in view: NSView) -> NSTableView? {
        if let table = view as? NSTableView { return table }
        for child in view.subviews {
            if let found = findTable(in: child) { return found }
        }
        return nil
    }

    static func findButton(in view: NSView, width: CGFloat) -> ConsoleButton? {
        if let button = view as? ConsoleButton, button.intrinsicContentSize.width == width { return button }
        for child in view.subviews {
            if let found = findButton(in: child, width: width) { return found }
        }
        return nil
    }

    static func until(_ criterion: () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(3)
        while !criterion() && Date() < deadline { try await Task.sleep(nanoseconds: 5_000_000) }
        require(criterion(), "timed out waiting for asynchronous result")
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String, line: UInt = #line) {
        guard condition() else {
            FileHandle.standardError.write(Data("StateTests.swift:\(line): \(message)\n".utf8))
            exit(1)
        }
    }
}
