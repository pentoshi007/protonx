import AppKit

@MainActor
final class AppController: NSObject, NSApplicationDelegate, NSPopoverDelegate, NSWindowDelegate {
    private let state: AppState
    private let initialPage: DirectoryPage
    private let appearanceOverride: NSAppearance?
    private let offlineImage = routeMark(connected: false)
    private let onlineImage = routeMark(connected: true)
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private var window: NSWindow?
    private var statusTip: String?

    override init() {
        let arguments = CommandLine.arguments
        if let path = arguments.first(where: { $0.hasPrefix("--engine=/") })?.dropFirst("--engine=".count) {
            state = AppState(engine: Engine(executable: URL(fileURLWithPath: String(path))))
        } else {
            state = AppState()
        }
        if let code = arguments.first(where: { $0.hasPrefix("--country=") })?.dropFirst("--country=".count) {
            initialPage = .country(code.uppercased())
        } else {
            initialPage = .locations
        }
        if arguments.contains("--appearance=dark") {
            appearanceOverride = NSAppearance(named: .darkAqua)
        } else if arguments.contains("--appearance=light") {
            appearanceOverride = NSAppearance(named: .aqua)
        } else {
            appearanceOverride = nil
        }
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let arguments = CommandLine.arguments
        if let appearanceOverride { NSApp.appearance = appearanceOverride }
        configureStatusItem()
        configureMenu()
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(didWake), name: NSWorkspace.didWakeNotification, object: nil)
        state.onChange = { [weak self] in self?.render() }
        state.start()
        if arguments.contains("--window") { showWindow(page: initialPage) }
        if arguments.contains("--popover") { togglePopover() }
        if arguments.contains("--selftest-popover") {
            DispatchQueue.main.async { [weak self] in self?.testPopoverOwnership() }
        }
        if arguments.contains("--selftest-status") {
            DispatchQueue.main.async { [weak self] in self?.testNativeStatus() }
        }
        if arguments.contains("--preview-signin") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in self?.state.previewSignedOut() }
        }
        if arguments.contains("--selftest-layout") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.dumpLayout() }
        }
        if arguments.contains("--selftest-signout") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in self?.testSignOut() }
        }
        if arguments.contains("--selftest-alert") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
                guard let self else { return }
                let controller = self.popover?.isShown == true
                    ? self.popover?.contentViewController
                    : self.window?.contentViewController
                (controller as? PopoverController)?.presentSignOutAlert()
            }
        }
        if arguments.contains("--selftest-alert-probe") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in self?.probeAlertPlacement() }
        }
        if arguments.contains("--selftest-alert-confirm") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.probeAlertConfirm() }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(page: nil)
        return false
    }

    private func configureStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: 28)
        item.button?.target = self
        item.button?.action = #selector(menuBarAction)
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        statusItem = item
        renderIcon()
    }

    private func configureMenu() {
        let main = NSMenu()
        let app = NSMenu(title: "ProtonX")
        let edit = NSMenu(title: "Edit")
        let view = NSMenu(title: "View")
        for menu in [app, edit, view] {
            let item = NSMenuItem()
            item.submenu = menu
            main.addItem(item)
        }
        app.addItem(withTitle: "Quit ProtonX", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        view.addItem(makeItem("Find Servers", #selector(focusSearch), key: "f"))
        view.addItem(makeItem("Refresh", #selector(refresh), key: "r"))
        view.addItem(makeItem("Open Window", #selector(openWindow), key: "o"))
        view.addItem(makeItem("Close", #selector(closePanel), key: "w"))
        NSApp.mainMenu = main
    }

    private func makeItem(_ title: String, _ action: Selector, key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    private func render() {
        renderIcon()
        if popover?.isShown == true { (popover?.contentViewController as? PopoverController)?.render() }
        if windowIsVisible { (window?.contentViewController as? PopoverController)?.render() }
    }

    private func renderIcon() {
        let label: String
        if state.operation != nil {
            label = "ProtonX · Changing route"
        } else if state.isUp {
            label = "ProtonX · \(state.status?.server?.label ?? "Tunnel up")"
        } else if state.status != nil {
            label = "ProtonX · Disconnected"
        } else {
            label = "ProtonX · Status unknown"
        }
        guard label != statusTip else { return }
        statusTip = label
        statusItem?.button?.image = state.isUp ? onlineImage : offlineImage
        statusItem?.button?.toolTip = label
        statusItem?.button?.setAccessibilityLabel(label)
    }

    @objc private func menuBarAction() {
        if NSApp.currentEvent?.type == .rightMouseUp { showContextMenu() } else { togglePopover() }
    }

    private func showContextMenu() {
        guard let button = statusItem?.button else { return }
        state.refreshStatus()
        let menu = NSMenu()
        menu.autoenablesItems = false
        if state.isUp {
            let disconnect = makeItem("Disconnect", #selector(disconnectTunnel))
            disconnect.isEnabled = state.canDisconnect
            menu.addItem(disconnect)
        } else {
            let recent = makeItem("Reconnect to Last Server", #selector(reconnectLast))
            recent.isEnabled = state.canConnect && state.lastServer.flatMap { state.server(for: $0.destination) } != nil
            menu.addItem(recent)
            let best = makeItem("Connect by Lowest Load", #selector(connectBest))
            best.isEnabled = state.canConnect && state.catalog?.bestDestination(in: nil) != nil
            menu.addItem(best)
        }
        menu.addItem(.separator())
        menu.addItem(makeItem("Open Window", #selector(openWindow)))
        menu.addItem(makeItem("Refresh", #selector(refresh)))
        menu.addItem(withTitle: "Quit ProtonX", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.maxY + 4), in: button)
    }

    private func togglePopover() {
        guard let button = statusItem?.button else { return }
        if popover?.isShown == true {
            popover?.performClose(nil)
            return
        }
        let panel = popover ?? makePopover()
        popover = panel
        (panel.contentViewController as? PopoverController)?.render()
        activate()
        panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        updateVisibility()
    }

    private func makePopover() -> NSPopover {
        let panel = NSPopover()
        let controller = PopoverController(state: state, page: initialPage)
        controller.openWindow = { [weak self] page in self?.showWindow(page: page) }
        controller.dismissForAlert = { [weak self] in
            guard let self, let popover = self.popover else { return false }
            let wasShown = popover.isShown
            popover.close()
            return wasShown
        }
        controller.restoreAfterAlert = { [weak self] in self?.togglePopover() }
        panel.contentViewController = controller
        if let appearanceOverride {
            panel.appearance = appearanceOverride
            controller.view.appearance = appearanceOverride
        }
        panel.contentSize = NSSize(width: PopoverController.popoverSize.width,
                                   height: state.session.signedIn ? PopoverController.popoverSize.height : 540)
        panel.behavior = .transient
        panel.animates = !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        panel.delegate = self
        return panel
    }

    private func showWindow(page: DirectoryPage?) {
        let target = window ?? makeWindow(page: page ?? initialPage)
        if let page { (target.contentViewController as? PopoverController)?.navigate(page) }
        window = target
        popover?.performClose(nil)
        if target.isMiniaturized { target.deminiaturize(nil) }
        activate()
        target.makeKeyAndOrderFront(nil)
        if !state.session.signedIn {
            target.setContentSize(NSSize(width: PopoverController.windowSize.width, height: 540))
        }
        (target.contentViewController as? PopoverController)?.render()
        updateVisibility()
    }

    private func makeWindow(page: DirectoryPage) -> NSWindow {
        let height = state.session.signedIn ? PopoverController.windowSize.height : 540
        let rect = NSRect(origin: .zero, size: NSSize(width: PopoverController.windowSize.width, height: height))
        let target = NSWindow(contentRect: rect, styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        target.title = "ProtonX"
        target.titleVisibility = .hidden
        target.titlebarAppearsTransparent = true
        target.backgroundColor = Theme.background
        target.isReleasedWhenClosed = false
        let controller = PopoverController(state: state, page: page, detached: true)
        target.contentViewController = controller
        if let appearanceOverride {
            target.appearance = appearanceOverride
            controller.view.appearance = appearanceOverride
        }
        target.contentMinSize = NSSize(width: 422, height: 540)
        if !target.setFrameUsingName("ProtonXConsole") { target.center() }
        target.setFrameAutosaveName("ProtonXConsole")
        target.setContentSize(rect.size)
        target.delegate = self
        return target
    }

    private var windowIsVisible: Bool {
        guard let window else { return false }
        return window.isVisible && !window.isMiniaturized && window.occlusionState.contains(.visible)
    }

    private func updateVisibility() {
        let isPopover = popover?.isShown == true
        let isWindow = windowIsVisible
        (popover?.contentViewController as? PopoverController)?.setPresented(isPopover)
        (window?.contentViewController as? PopoverController)?.setPresented(isWindow)
        state.setVisible(isPopover || isWindow)
    }

    private func activate() {
        if #available(macOS 14.0, *) { NSApp.activate() } else { NSApp.activate(ignoringOtherApps: true) }
    }

    func popoverDidShow(_ notification: Notification) { updateVisibility() }
    func popoverDidClose(_ notification: Notification) { updateVisibility() }
    func windowDidChangeOcclusionState(_ notification: Notification) { updateVisibility() }
    func windowDidMiniaturize(_ notification: Notification) { updateVisibility() }
    func windowDidDeminiaturize(_ notification: Notification) { updateVisibility() }
    func windowWillClose(_ notification: Notification) { DispatchQueue.main.async { [weak self] in self?.updateVisibility() } }

    @objc private func didWake() { state.refreshStatus() }
    @objc private func refresh() { state.refresh() }
    @objc private func openWindow() { showWindow(page: nil) }
    @objc private func disconnectTunnel() { state.disconnect() }
    @objc private func reconnectLast() { if let target = state.lastServer?.destination { state.connect(target) } }
    @objc private func connectBest() { if let target = state.catalog?.bestDestination(in: nil) { state.connect(target) } }

    @objc private func focusSearch() {
        let controller = popover?.isShown == true ? popover?.contentViewController : window?.contentViewController
        (controller as? PopoverController)?.focusSearch()
    }

    @objc private func closePanel() {
        if popover?.isShown == true { popover?.performClose(nil) } else { window?.performClose(nil) }
    }

    private func probeAlertPlacement(attempts: Int = 60) {
        guard let button = statusItem?.button else {
            print("Alert placement: FAIL (no status item)")
            exit(1)
        }
        let panel = popover ?? makePopover()
        popover = panel
        panel.animates = false
        panel.behavior = .applicationDefined
        if !panel.isShown { panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY) }
        guard state.canSignOut else {
            guard attempts > 0 else {
                print("Alert placement: FAIL (not ready: \(state.session))")
                exit(1)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
                self?.probeAlertPlacement(attempts: attempts - 1)
            }
            return
        }
        guard let controller = panel.contentViewController as? PopoverController else {
            print("Alert placement: FAIL (no controller)")
            exit(1)
        }
        let probe = Timer(timeInterval: 4.0, repeats: false) { _ in
            let modal = NSApp.modalWindow
            let level = modal?.level.rawValue ?? -1
            let visible = modal?.isVisible ?? false
            let popoverClosed = !panel.isShown
            let passed = visible && level >= NSWindow.Level.modalPanel.rawValue && popoverClosed
            let frame = modal.map { NSStringFromRect($0.frame) } ?? "none"
            print("Alert placement: probe (canSignOut=\(self.state.canSignOut), catalog=\(self.state.catalogPhase), modal=\(modal != nil))")
            print("Alert placement: \(passed ? "PASS" : "FAIL") (level=\(level), visible=\(visible), popoverClosed=\(popoverClosed), frame=\(frame))")
            NSApp.stopModal(withCode: .alertFirstButtonReturn)
            DispatchQueue.main.async { exit(passed ? 0 : 1) }
        }
        RunLoop.main.add(probe, forMode: .common)
        print("Alert placement: presenting (canSignOut=\(state.canSignOut), session=\(state.session), catalog=\(state.catalogPhase))")
        controller.presentSignOutAlert()
    }

    private func probeAlertConfirm() {
        guard let button = statusItem?.button else {
            print("Alert confirm: FAIL (no status item)")
            exit(1)
        }
        let panel = popover ?? makePopover()
        popover = panel
        panel.animates = false
        panel.behavior = .applicationDefined
        panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self, let controller = panel.contentViewController as? PopoverController else {
                print("Alert confirm: FAIL (no controller)")
                exit(1)
            }
            let probe = Timer(timeInterval: 1.0, repeats: false) { _ in
                NSApp.stopModal(withCode: .alertSecondButtonReturn)
            }
            RunLoop.main.add(probe, forMode: .common)
            controller.presentSignOutAlert()
            self.waitForSignOutProbe(attempts: 80)
        }
    }

    private func waitForSignOutProbe(attempts: Int) {
        if case .ready(let account) = state.session, !account.signedIn {
            print("Alert confirm: PASS (confirm button ran sign-out)")
            exit(0)
        }
        guard attempts > 0 else {
            print("Alert confirm: FAIL (session=\(state.session), notice=\(state.notice ?? "none"))")
            exit(1)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            self?.waitForSignOutProbe(attempts: attempts - 1)
        }
    }

    private func testPopoverOwnership() {
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in self?.runPopoverSteps() }
    }

    private func runPopoverSteps() {
        guard let button = statusItem?.button else {
            print("Popover ownership: FAIL (no status item)")
            exit(1)
        }
        let panel = makePopover()
        panel.animates = false
        panel.behavior = .applicationDefined
        popover = panel
        panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        let before = panel.contentViewController?.view
        let initial = panel.isShown && before?.superview != nil
        showWindow(page: nil)
        let detached = window?.contentViewController?.view
        let detachedShown = window?.isVisible == true && detached != nil
        panel.performClose(nil)
        window?.close()
        panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        let after = panel.contentViewController?.view
        after?.layoutSubtreeIfNeeded()
        let intact = after === before && after !== detached && after?.superview != nil
        let size = after?.bounds.size ?? .zero
        let passed = initial && detachedShown && panel.isShown && intact && size.width >= 420
        print("Popover ownership: \(passed ? "PASS" : "FAIL") (initial=\(initial), window=\(detachedShown), reopened=\(panel.isShown), intact=\(intact), size=\(size))")
        exit(passed ? 0 : 1)
    }

    private func dumpLayout() {
        guard let root = window?.contentViewController?.view else {
            print("Layout: no window")
            exit(1)
        }
        func walk(_ view: NSView, _ depth: Int) {
            let name = String(describing: type(of: view))
            print(String(repeating: "  ", count: depth) + "\(name) frame=\(view.frame) hidden=\(view.isHidden)")
            for child in view.subviews { walk(child, depth + 1) }
        }
        walk(root, 0)
        exit(0)
    }

    private func testSignOut() {
        guard state.canSignOut else {
            print("Sign out: FAIL (not ready, session=\(state.session))")
            exit(1)
        }
        state.signOut()
        waitForSignOut(attempts: 60)
    }

    private func waitForSignOut(attempts: Int) {
        if case .ready(let account) = state.session, !account.signedIn {
            print("Sign out: PASS (session cleared, tunnel up=\(state.isUp), catalog=\(state.catalog == nil ? "cleared" : "kept"))")
            exit(0)
        }
        guard attempts > 0 else {
            print("Sign out: FAIL (session=\(state.session), notice=\(state.notice ?? "none"))")
            exit(1)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in self?.waitForSignOut(attempts: attempts - 1) }
    }

    private func testNativeStatus() {
        do {
            let status = try Engine().status()
            let label = status.server?.label ?? "none"
            print("Native status: PASS (up=\(status.up), interface=\(status.interface ?? "none"), last=\(label), peer=\(status.peer != nil))")
            exit(0)
        } catch {
            print("Native status: FAIL (\(error.localizedDescription))")
            exit(1)
        }
    }
}

@main @MainActor
private enum Launch {
    static func main() {
        let application = NSApplication.shared
        let controller = AppController()
        application.delegate = controller
        withExtendedLifetime(controller) { application.run() }
    }
}
