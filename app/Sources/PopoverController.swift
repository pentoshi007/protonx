import AppKit

@MainActor
final class PopoverController: NSViewController {
    static let popoverSize = NSSize(width: 428, height: 625)
    static let windowSize = NSSize(width: 510, height: 684)

    var openWindow: ((DirectoryPage) -> Void)?
    var dismissForAlert: (() -> Bool)?
    var restoreAfterAlert: (() -> Void)?
    var checkForUpdates: (() -> Void)?
    var repairNetwork: (() -> Void)?
    var page: DirectoryPage { directory.page }

    private let state: AppState
    private let initialPage: DirectoryPage
    private let size: NSSize
    private let route = RouteCard()
    private let refresh = ConsoleButton("Refresh", symbol: "arrow.clockwise", style: .icon, height: 32)
    private let accountButton = ConsoleButton("Account", symbol: "person.crop.circle", style: .icon, height: 32)
    private let showWindow = ConsoleButton("Window", symbol: "macwindow", height: 32)
    private let notice = wrapped("", color: Theme.error, lines: 3)
    private let banner = Surface(Theme.errorFill, radius: 8)
    private let footer = text("", 11, color: Theme.secondary)
    private let accountIndicator = text("", 11, color: Theme.secondary)
    private lazy var directory = DirectoryView(state: state, page: initialPage)
    private lazy var sessionView = SessionView(state: state)
    private var footerRow: NSView?
    private var presented = false
    private var lastSignedIn: Bool?

    init(state: AppState, page: DirectoryPage = .locations, detached: Bool = false) {
        self.state = state
        self.initialPage = page
        self.size = detached ? Self.windowSize : Self.popoverSize
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    override func loadView() {
        let root = Surface(Theme.background)
        root.frame = NSRect(origin: .zero, size: size)
        view = root
        preferredContentSize = NSSize(width: size.width, height: state.session.signedIn ? size.height : 540)
        let content = column([makeHeader(), route, banner, sessionView, directory, makeFooter()], spacing: 12)
        content.setCustomSpacing(11, after: route)
        content.setCustomSpacing(9, after: directory)
        install(content, in: root, x: 16, y: 13)
        banner.widthAnchor.constraint(equalTo: content.widthAnchor).isActive = true
        configureBanner()
        sessionView.setContentHuggingPriority(.defaultLow, for: .vertical)
        showWindow.isHidden = openWindow == nil
        render()
    }

    private func makeHeader() -> NSView {
        let logo = Surface(Theme.ink, radius: 9)
        let image = NSImageView(image: routeMark(connected: true))
        image.contentTintColor = Theme.signal
        image.imageScaling = .scaleNone
        install(image, in: logo)
        logo.widthAnchor.constraint(equalToConstant: 33).isActive = true
        logo.heightAnchor.constraint(equalToConstant: 33).isActive = true
        let wordmark = text("ProtonX", 17, .bold)
        wordmark.setContentCompressionResistancePriority(.required, for: .horizontal)
        let channel = mono("WIREGUARD", 9)
        let name = column([wordmark, channel], spacing: 0, fill: false)
        refresh.handler = { [weak state] in state?.refresh() }
        accountButton.handler = { [weak self] in self?.showAccountMenu() }
        showWindow.handler = { [weak self] in
            guard let self else { return }
            self.openWindow?(self.page)
        }
        return line([logo, name, space(), refresh, accountButton, showWindow], spacing: 8)
    }

    private func makeAccountMenu() -> NSMenu? {
        guard case .ready(let account) = state.session, account.signedIn else { return nil }
        let menu = NSMenu()
        menu.autoenablesItems = false
        let identity = NSMenuItem(title: account.username ?? "Proton account", action: nil, keyEquivalent: "")
        identity.isEnabled = false
        menu.addItem(identity)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let build = NSMenuItem(title: "ProtonX \(version)", action: nil, keyEquivalent: "")
        build.isEnabled = false
        menu.addItem(build)
        menu.addItem(.separator())
        let updates = NSMenuItem(title: "Check for Updates…", action: #selector(checkForUpdatesAction), keyEquivalent: "")
        updates.target = self
        updates.isEnabled = checkForUpdates != nil
        menu.addItem(updates)
        let login = NSMenuItem(title: "Launch at Login", action: #selector(toggleLaunchAtLogin), keyEquivalent: "")
        login.target = self
        login.state = LaunchAtLogin.isEnabled ? .on : .off
        menu.addItem(login)
        let repair = NSMenuItem(title: "Repair Network", action: #selector(repairNetworkAction), keyEquivalent: "")
        repair.target = self
        repair.isEnabled = repairNetwork != nil
        menu.addItem(repair)
        menu.addItem(.separator())
        let signOut = NSMenuItem(title: "Sign Out…", action: #selector(confirmSignOut), keyEquivalent: "")
        signOut.target = self
        signOut.isEnabled = state.canSignOut
        menu.addItem(signOut)
        return menu
    }

    private func showAccountMenu() {
        // Present after the button's mouse event finishes. Popping the menu
        // inside that event lets the same mouse-up dismiss it on the first
        // click; the second click only worked because the window was already
        // active by then.
        DispatchQueue.main.async { [weak self] in self?.presentAccountMenu() }
    }

    private func presentAccountMenu(capture: String? = nil, cancelAfter: TimeInterval? = nil) {
        guard let menu = makeAccountMenu() else { return }
        if let cancelAfter {
            let timer = Timer(timeInterval: cancelAfter, repeats: false) { _ in
                if let capture, !capture.isEmpty {
                    let process = Process()
                    process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
                    process.arguments = ["-x", capture]
                    try? process.run()
                    process.waitUntilExit()
                }
                menu.cancelTracking()
            }
            RunLoop.main.add(timer, forMode: .common)
        }
        // The popover is application-defined, so opening a menu cannot make the
        // system close it. The menu is presented after the button's mouse event
        // so that same event cannot dismiss it either.
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: accountButton.bounds.height + 4), in: accountButton)
    }

    func accountMenuTitles() -> [String] {
        makeAccountMenu()?.items.map(\.title) ?? []
    }

    func presentAccountMenuForProbe(capture: String?, cancelAfter: TimeInterval = 0.8) {
        presentAccountMenu(capture: capture, cancelAfter: cancelAfter)
    }

    @objc private func confirmSignOut() {
        DispatchQueue.main.async { [weak self] in self?.presentSignOutAlert() }
    }

    @objc private func checkForUpdatesAction() {
        checkForUpdates?()
    }

    @objc private func repairNetworkAction() {
        repairNetwork?()
    }

    @objc private func toggleLaunchAtLogin() {
        do {
            try LaunchAtLogin.setEnabled(!LaunchAtLogin.isEnabled)
        } catch {
            state.showNotice("Could not update the login item: \(error.localizedDescription)")
        }
    }

    func presentSignOutAlert() {
        guard state.canSignOut else { return }
        let alert = NSAlert()
        alert.messageText = "Sign out of ProtonX?"
        alert.informativeText = state.isUp
            ? "This will disconnect the active tunnel and remove your sign-in from this Mac. Your saved servers will stay."
            : "This will remove your sign-in from this Mac. Your saved servers will stay."
        let cancel = alert.addButton(withTitle: "Cancel")
        cancel.keyEquivalent = "\r"
        let confirm = alert.addButton(withTitle: "Sign Out")
        confirm.keyEquivalent = ""
        let escape = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            guard [53, 36, 76].contains(event.keyCode) else { return event }
            NSApp.stopModal(withCode: .alertFirstButtonReturn)
            return nil
        }
        let restore = dismissForAlert?() ?? false
        alert.window.center()
        NSApp.activate(ignoringOtherApps: true)
        let response = alert.runModal()
        if let escape { NSEvent.removeMonitor(escape) }
        if restore { restoreAfterAlert?() }
        if response == .alertSecondButtonReturn { state.signOut() }
    }

    private func configureBanner() {
        notice.alignment = .left
        let dismiss = ConsoleButton("Dismiss message", symbol: "xmark", style: .icon, height: 25)
        dismiss.handler = { [weak state] in state?.dismissNotice() }
        install(line([notice, dismiss], spacing: 4), in: banner, x: 8, y: 5)
    }

    private func makeFooter() -> NSView {
        let status = line([footer, space(), accountIndicator], spacing: 9)
        status.heightAnchor.constraint(equalToConstant: 17).isActive = true
        footerRow = status
        return status
    }

    func setPresented(_ isVisible: Bool) {
        guard presented != isVisible else { return }
        presented = isVisible
        if !isVisible { sessionView.clearSensitiveFields() }
        render()
        if isVisible, state.session.signedIn { directory.focusList() }
    }

    func render() {
        guard isViewLoaded else { return }
        let signedIn = state.session.signedIn
        resize(for: signedIn)
        accountButton.isHidden = !signedIn
        accountButton.isEnabled = state.operation != .signingOut
        refresh.isHidden = !signedIn
        route.isHidden = !signedIn
        footerRow?.isHidden = !signedIn
        directory.isHidden = !signedIn
        sessionView.isHidden = signedIn
        banner.isHidden = state.notice == nil
        notice.stringValue = state.notice ?? ""
        notice.toolTip = state.notice
        refresh.isEnabled = !state.catalogPhase.isLoading && !state.authBusy
        route.render(state, visible: presented)
        directory.render(presented: presented && signedIn)
        sessionView.render(presented: presented && !signedIn)
        renderFooter()
    }

    private func resize(for signedIn: Bool) {
        guard lastSignedIn != signedIn else { return }
        lastSignedIn = signedIn
        let target = NSSize(width: size.width, height: signedIn ? size.height : 540)
        preferredContentSize = target
        if let window = view.window, window.styleMask.contains(.titled) {
            window.setContentSize(target)
        }
    }

    private func renderFooter() {
        accountIndicator.stringValue = state.session.signedIn ? "Free WireGuard servers" : "Proton account"
        if case .ready(let account) = state.session { accountIndicator.toolTip = account.signedIn ? account.username : nil }
        switch state.catalogPhase {
        case .readingCache, .refreshing: footer.stringValue = "Updating server directory…"
        case .current: footer.stringValue = catalogTime(prefix: "Updated")
        case .saved(let reason):
            footer.stringValue = catalogTime(prefix: "Saved list ·")
            footer.toolTip = reason ?? "Showing the last downloaded server list"
            return
        case .unavailable: footer.stringValue = "Couldn’t update the directory"
        case .idle: footer.stringValue = ""
        }
        footer.toolTip = nil
    }

    private func catalogTime(prefix: String) -> String {
        guard let catalog = state.catalog else { return "" }
        let time = Date(timeIntervalSince1970: catalog.fetchedAt).formatted(date: .omitted, time: .shortened)
        return "\(prefix) \(time)"
    }

    func focusSearch() {
        guard state.session.signedIn else { return }
        directory.focusSearch()
    }

    func navigate(_ page: DirectoryPage) { directory.navigate(page) }
}

@MainActor
func routeMark(connected: Bool) -> NSImage {
    let icon = NSImage(size: NSSize(width: 19, height: 19), flipped: false) { _ in
        let first = NSPoint(x: 3.5, y: 5)
        let last = NSPoint(x: 15.5, y: 14)
        let route = NSBezierPath()
        route.move(to: first)
        route.curve(to: last, controlPoint1: NSPoint(x: 10, y: 5), controlPoint2: NSPoint(x: 9, y: 14))
        NSColor.black.setStroke()
        NSColor.black.setFill()
        route.lineWidth = 1.55
        route.stroke()
        NSBezierPath(ovalIn: NSRect(x: first.x - 2, y: first.y - 2, width: 4, height: 4)).fill()
        let end = NSBezierPath(ovalIn: NSRect(x: last.x - 2.4, y: last.y - 2.4, width: 4.8, height: 4.8))
        end.lineWidth = 1.5
        if connected { end.fill() } else { end.stroke() }
        return true
    }
    icon.isTemplate = true
    return icon
}
