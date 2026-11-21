import Foundation

@MainActor
final class AppState {
    private(set) var session: SessionPhase = .checking
    private(set) var catalogPhase: CatalogPhase = .idle
    private(set) var catalog: Catalog?
    private(set) var status: Status?
    private(set) var lastServer: LastServer?
    private(set) var statusError: String?
    private(set) var operation: TunnelOperation?
    private(set) var authBusy = false
    private(set) var notice: String?
    private(set) var savedRoutes: Set<Destination>

    var onChange: (() -> Void)?

    private static let savedKey = "SavedRoutes"
    private let engine: any EngineAccess
    private let defaults: UserDefaults
    private var started = false
    private var visible = false
    private var lastRefresh = Date.distantPast
    private var statusPending = false
    private var tunnelRevision = 0
    private var timer: Timer?

    init(engine: any EngineAccess = Engine(), defaults: UserDefaults = .standard) {
        self.engine = engine
        self.defaults = defaults
        let saved = defaults.data(forKey: Self.savedKey)
        savedRoutes = saved.flatMap { try? PropertyListDecoder().decode(Set<Destination>.self, from: $0) } ?? []
    }

    deinit { timer?.invalidate() }

    var isUp: Bool { status?.up == true }
    var dnsStale: Bool { status?.dns?.stale == true }
    var activeDestination: Destination? { isUp ? status?.server?.destination : nil }
    var canConnect: Bool { session.signedIn && status != nil && operation == nil }
    var canDisconnect: Bool { isUp && operation == nil }
    var canSignOut: Bool { session.signedIn && operation == nil && !catalogPhase.isLoading }

    var pollingInterval: TimeInterval? {
        guard isUp, operation == nil else { return nil }
        return visible ? 12 : 60
    }

    func start() {
        guard !started else { return }
        started = true
        retrySession()
        refreshStatus()
    }

    func setVisible(_ value: Bool) {
        guard visible != value else { return }
        visible = value
        updatePolling()
        guard visible else { return }
        refreshStatus()
        refreshCatalog()
    }

    func retrySession() {
        session = .checking
        onChange?()
        run({ engine in Result { try engine.account() } }) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let account):
                self.session = .ready(account)
                if account.signedIn { self.readCache() }
            case .failure(let error):
                self.session = .unavailable(error.localizedDescription)
            }
            self.onChange?()
        }
    }

    func refresh() {
        refreshStatus()
        if case .unavailable = session {
            retrySession()
        } else {
            refreshCatalog(force: true)
        }
    }

    func refreshStatus() {
        guard !statusPending, operation == nil else { return }
        statusPending = true
        let revision = tunnelRevision
        run({ engine in Result { try engine.status() } }) { [weak self] result in
            guard let self else { return }
            self.statusPending = false
            guard revision == self.tunnelRevision else { return }
            if self.applyStatus(result) { self.onChange?() }
        }
    }

    func connect(_ target: Destination) {
        guard canConnect, target != activeDestination, server(for: target) != nil else { return }
        let transition: TunnelOperation = isUp ? .switching(target) : .connecting(target)
        changeTunnel(transition) { try $0.connect(target) }
    }

    func disconnect() {
        guard canDisconnect else { return }
        changeTunnel(.disconnecting) { try $0.disconnect() }
    }

    func signOut() {
        guard canSignOut else { return }
        changeTunnel(.signingOut) { engine in
            if try engine.status().up { try engine.disconnect() }
            try engine.signOut()
        }
    }

    func checkForUpdates(_ completion: @escaping (Result<UpdateStatus, Error>) -> Void) {
        run({ engine in Result { try engine.updateCheck() } }, completion)
    }

    func repair(_ completion: ((Result<RepairReport, Error>) -> Void)? = nil) {
        guard operation == nil else { return }
        tunnelRevision += 1
        operation = .repairing
        notice = nil
        updatePolling()
        onChange?()
        run({ engine in Result { try engine.repair() } }) { [weak self] result in
            guard let self else { return }
            self.operation = nil
            switch result {
            case .success(let report):
                self.notice = report.internet
                    ? "Network repaired · DNS restored · internet reachable"
                    : "Repair finished · DNS restored · internet still unreachable"
            case .failure(let error):
                self.notice = "Repair failed: \(error.localizedDescription)"
            }
            self.refreshStatus()
            self.onChange?()
            completion?(result)
        }
    }

    func server(for destination: Destination) -> Server? {
        catalog?.country(destination.country)?.servers.first { $0.name == destination.server }
    }

    func toggleSaved(_ target: Destination) {
        if savedRoutes.remove(target) == nil { savedRoutes.insert(target) }
        defaults.set(try? PropertyListEncoder().encode(savedRoutes), forKey: Self.savedKey)
        onChange?()
    }

    func dismissNotice() {
        notice = nil
        onChange?()
    }

    func showNotice(_ message: String) {
        notice = message
        onChange?()
    }

    func previewSignedOut() {
        session = .ready(Account(signedIn: false, username: nil, pending: false))
        catalog = nil
        catalogPhase = .idle
        onChange?()
    }

    func signIn(username: String, password: String) {
        let name = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !password.isEmpty else { return }
        authenticate { try $0.signIn(username: name, password: password) }
    }

    func submitTwoFactor(_ pin: String) {
        let code = pin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard code.count == 6, code.utf8.allSatisfy({ (48...57).contains($0) }) else { return }
        authenticate { try $0.submitTwoFactor(code) }
    }

    private func readCache() {
        catalogPhase = .readingCache
        run({ engine in try? engine.catalog(offline: true) }) { [weak self] local in
            guard let self else { return }
            self.catalog = local
            if let local {
                self.catalogPhase = local.isFresh ? .current : .saved(nil)
            } else {
                self.catalogPhase = .idle
            }
            self.refreshCatalog()
            self.onChange?()
        }
    }

    private func refreshCatalog(force: Bool = false) {
        guard session.signedIn, !catalogPhase.isLoading, operation != .signingOut else { return }
        if !force {
            let recentlyTried = Date().timeIntervalSince(lastRefresh) < 60
            guard visible, catalog?.isFresh != true, !recentlyTried else { return }
        }
        lastRefresh = Date()
        catalogPhase = .refreshing
        onChange?()
        run({ engine in Result { try engine.catalog(offline: false) } }) { [weak self] result in
            self?.finishCatalog(result)
        }
    }

    private func finishCatalog(_ result: Result<Catalog, Error>) {
        switch result {
        case .success(let fresh):
            catalog = fresh
            catalogPhase = .current
        case .failure(let error):
            let message = error.localizedDescription
            catalogPhase = catalog == nil ? .unavailable(message) : .saved(message)
            if (error as? EngineError)?.needsSignIn == true, case .ready(let account) = session {
                session = .ready(Account(signedIn: false, username: account.username, pending: account.pending))
                notice = "Your Proton session expired. Sign in again to refresh servers."
            }
        }
        onChange?()
    }

    private func authenticate(_ work: @escaping @Sendable (any EngineAccess) throws -> SignInResult) {
        guard !authBusy else { return }
        authBusy = true
        notice = nil
        onChange?()
        run({ engine in Result { try work(engine) } }) { [weak self] result in
            guard let self else { return }
            self.authBusy = false
            switch result {
            case .success(let signedIn):
                let pending = signedIn.status == "two-factor"
                self.session = .ready(Account(signedIn: !pending, username: signedIn.username, pending: pending))
                if !pending {
                    self.lastRefresh = .distantPast
                    self.readCache()
                }
            case .failure(let error):
                self.notice = error.localizedDescription
            }
            self.onChange?()
        }
    }

    private func changeTunnel(_ action: TunnelOperation, work: @escaping @Sendable (any EngineAccess) throws -> Void) {
        tunnelRevision += 1
        operation = action
        notice = nil
        updatePolling()
        onChange?()
        run({ engine in
            let command = Result { try work(engine) }
            return (command, Result { try engine.status() })
        }) { [weak self] command, snapshot in
            guard let self else { return }
            self.operation = nil
            _ = self.applyStatus(snapshot)
            switch command {
            case .success where action == .signingOut:
                self.session = .ready(Account(signedIn: false, username: nil, pending: false))
                self.catalog = nil
                self.catalogPhase = .idle
            case .failure(let error):
                self.notice = error.localizedDescription
            case .success:
                break
            }
            self.onChange?()
        }
    }

    private func applyStatus(_ snapshot: Result<Status, Error>) -> Bool {
        let before = status
        let previousError = statusError
        switch snapshot {
        case .success(let fresh):
            status = fresh
            lastServer = fresh.server
            statusError = fresh.flowError
        case .failure(let error):
            status = nil
            statusError = error.localizedDescription
        }
        updatePolling()
        return before != status || previousError != statusError
    }

    private func updatePolling() {
        let interval = pollingInterval
        if interval == timer?.timeInterval { return }
        timer?.invalidate()
        timer = nil
        guard let interval else { return }
        let scheduled = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refreshStatus() }
        }
        scheduled.tolerance = interval / 4
        RunLoop.main.add(scheduled, forMode: .common)
        timer = scheduled
    }

    private func run<Value: Sendable>(
        _ work: @escaping @Sendable (any EngineAccess) -> Value,
        _ finish: @escaping (Value) -> Void
    ) {
        let engine = self.engine
        Task {
            let value = await Task.detached(priority: .utility) { work(engine) }.value
            finish(value)
        }
    }
}
