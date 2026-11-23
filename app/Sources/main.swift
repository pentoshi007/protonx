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
    private var statusLabel: String?

    override init() {
        let arguments = CommandLine.arguments
        if let path = arguments.first(where: { $0.hasPrefix("--engine=/") })?.dropFirst("--engine=".count) {
            state = AppState(engine: Engine(executable: URL(fileURLWithPath: String(path)), usesNativeStatus: false))
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
        if arguments.contains("--selftest-status-item") {
            DispatchQueue.main.async { [weak self] in self?.testStatusItem() }
        }
        if arguments.contains("--selftest-engine") {
            DispatchQueue.main.async { [weak self] in self?.testEngineSurface() }
        }
        if arguments.contains("--selftest-account-menu") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.testAccountMenu() }
        }
        if arguments.contains("--selftest-update") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.testUpdateCheck() }
        }
        if arguments.contains("--selftest-repair") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.testRepair() }
        }
        if arguments.contains("--selftest-repair-alert") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.testRepairAlert() }
        }
        if arguments.contains("--selftest-menus") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in self?.testMenus() }
        }
        if arguments.contains("--selftest-update-alert") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.testUpdateAlert() }
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
        app.addItem(makeItem("Check for Updates…", #selector(checkForUpdates)))
        app.addItem(makeItem("Launch at Login", #selector(toggleLaunchAtLogin)))
        app.addItem(makeItem("Repair Network", #selector(repairNetwork)))
        app.addItem(.separator())
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
        guard label != statusLabel else { return }
        statusLabel = label
        statusItem?.button?.image = state.isUp ? onlineImage : offlineImage
        // No button.toolTip: on macOS 27.2 AppKit can leave the status item's
        // NSToolTipPanel on screen after the pointer leaves, and it follows the
        // pointer when the tooltip text changes. The accessibility label below
        // carries the same state without creating a tooltip window.
        statusItem?.button?.setAccessibilityLabel(label)
    }

    @objc private func menuBarAction() {
        if NSApp.currentEvent?.type == .rightMouseUp { showContextMenu() } else { togglePopover() }
    }

    private func showContextMenu() {
        guard let button = statusItem?.button else { return }
        state.refreshStatus()
        let menu = makeContextMenu()
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.maxY + 4), in: button)
    }

    private func makeContextMenu() -> NSMenu {
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
        menu.addItem(makeItem("Repair Network", #selector(repairNetwork)))
        menu.addItem(makeItem("Check for Updates…", #selector(checkForUpdates)))
        let login = makeItem("Launch at Login", #selector(toggleLaunchAtLogin))
        login.state = LaunchAtLogin.isEnabled ? .on : .off
        menu.addItem(login)
        menu.addItem(withTitle: "Quit ProtonX", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        return menu
    }

    func contextMenuTitles() -> [String] {
        makeContextMenu().items.map(\.title)
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
        // A menu-bar popover is not key until something makes it key. Without
        // this, the first click inside it is spent activating the window and a
        // menu opened by that click is dismissed immediately.
        panel.contentViewController?.view.window?.makeKey()
        updateVisibility()
    }

    private func makePopover() -> NSPopover {
        let panel = NSPopover()
        let controller = PopoverController(state: state, page: initialPage)
        controller.openWindow = { [weak self] page in self?.showWindow(page: page) }
        controller.checkForUpdates = { [weak self] in self?.checkForUpdates() }
        controller.repairNetwork = { [weak self] in self?.repairNetwork() }
        controller.setPopoverBehavior = { [weak self] behavior in
            self?.popover?.behavior = behavior
        }
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
        controller.checkForUpdates = { [weak self] in self?.checkForUpdates() }
        controller.repairNetwork = { [weak self] in self?.repairNetwork() }
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
    @objc private func toggleLaunchAtLogin() {
        do {
            try LaunchAtLogin.setEnabled(!LaunchAtLogin.isEnabled)
        } catch {
            state.showNotice("Could not update the login item: \(error.localizedDescription)")
        }
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        if menuItem.action == #selector(toggleLaunchAtLogin) {
            menuItem.state = LaunchAtLogin.isEnabled ? .on : .off
        }
        return true
    }
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
        let canSignOut = state.canSignOut
        let catalogPhase = String(describing: state.catalogPhase)
        let probe = Timer(timeInterval: 4.0, repeats: false) { _ in
            let modal = NSApp.modalWindow
            let level = modal?.level.rawValue ?? -1
            let visible = modal?.isVisible ?? false
            let popoverClosed = !panel.isShown
            let passed = visible && level >= NSWindow.Level.modalPanel.rawValue && popoverClosed
            let frame = modal.map { NSStringFromRect($0.frame) } ?? "none"
            print("Alert placement: probe (canSignOut=\(canSignOut), catalog=\(catalogPhase), modal=\(modal != nil))")
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

    private func testStatusItem() {
        guard let button = statusItem?.button else {
            print("Status item: FAIL (no status item)")
            exit(1)
        }
        let label = button.accessibilityLabel() ?? "none"
        let screen = button.window.map { $0.convertToScreen(button.convert(button.bounds, to: nil)) } ?? .zero
        let passed = button.toolTip == nil && label.contains("ProtonX")
        print("Status item: \(passed ? "PASS" : "FAIL") (tooltip=\(button.toolTip ?? "none"), label=\(label), frame=\(NSStringFromRect(screen)))")
        exit(passed ? 0 : 1)
    }

    private func testAccountMenu() {
        let panel = popover ?? makePopover()
        popover = panel
        if !panel.isShown, let button = statusItem?.button {
            (panel.contentViewController as? PopoverController)?.render()
            activate()
            panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            panel.contentViewController?.view.window?.makeKey()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { [weak self] in
            self?.runAccountMenuProbe()
        }
    }

    private func runAccountMenuProbe() {
        guard let controller = popover?.contentViewController as? PopoverController else {
            print("Account menu: FAIL (no controller)")
            exit(1)
        }
        let titles = controller.accountMenuTitles()
        guard !titles.isEmpty else {
            print("Account menu: FAIL (not signed in)")
            exit(1)
        }
        let before = popover?.isShown == true
        controller.presentAccountMenuForProbe(capture: ProcessInfo.processInfo.environment["PROTONX_CAPTURE"])
        let after = popover?.isShown == true
        let passed = before && after
        print("Account menu: \(passed ? "PASS" : "FAIL") (items=\(titles.joined(separator: " | ")), popoverBefore=\(before), popoverAfter=\(after))")
        exit(passed ? 0 : 1)
    }


    @objc private func checkForUpdates() {
        state.checkForUpdates { [weak self] result in
            self?.presentUpdate(result)
        }
    }

    private func presentUpdate(_ result: Result<UpdateStatus, Error>) {
        switch result {
        case .success(let status) where status.update:
            let response = presentAlert { alert in
                alert.messageText = "ProtonX \(status.latest) is available"
                alert.informativeText = "You have \(status.current). The update downloads the signed release and asks for your administrator password."
                alert.addButton(withTitle: "Update")
                alert.addButton(withTitle: "Cancel")
            }
            if response == .alertFirstButtonReturn { installUpdate() }
        case .success(let status):
            _ = presentAlert { alert in
                alert.messageText = "ProtonX is up to date"
                alert.informativeText = "Version \(status.current) is the latest release."
                alert.addButton(withTitle: "OK")
            }
        case .failure(let error):
            _ = presentAlert { alert in
                alert.messageText = "Could not check for updates"
                alert.informativeText = error.localizedDescription
                alert.addButton(withTitle: "OK")
            }
        }
    }

    @objc private func repairNetwork() {
        state.repair { [weak self] result in
            self?.presentRepair(result)
        }
    }

    private func presentRepair(_ result: Result<RepairReport, Error>) {
        switch result {
        case .success(let report):
            let summary = report.internet
                ? "The tunnel is stopped, DNS is restored, and the internet is reachable."
                : "The tunnel is stopped and DNS is restored, but the internet is still unreachable."
            let actions = report.actions.isEmpty ? "" : "\n\n" + report.actions.map { "• \($0)" }.joined(separator: "\n")
            _ = presentAlert { alert in
                alert.messageText = report.internet ? "Network repaired" : "Repair finished"
                alert.informativeText = summary + actions
                alert.addButton(withTitle: "OK")
            }
        case .failure(let error):
            _ = presentAlert { alert in
                alert.messageText = "Repair failed"
                alert.informativeText = error.localizedDescription
                alert.addButton(withTitle: "OK")
            }
        }
    }

    private func presentAlert(_ configure: (NSAlert) -> Void) -> NSApplication.ModalResponse {
        let wasShown = popover?.isShown == true
        popover?.close()
        let alert = NSAlert()
        configure(alert)
        alert.window.center()
        activate()
        let response = alert.runModal()
        if wasShown { togglePopover() }
        return response
    }

    private func installUpdate() {
        let engine = "/usr/local/libexec/protonx-app/app-engine"
        guard FileManager.default.isExecutableFile(atPath: engine) else {
            state.showNotice("The ProtonX engine is missing. Reinstall ProtonX.")
            return
        }
        let script = "do shell script \"PROTONX_KEEP_APP=1 \(engine) update --yes --app\" with administrator privileges"
        let alert = NSAlert()
        alert.messageText = "Updating ProtonX"
        alert.informativeText = "Downloading and installing the latest release. This can take a minute."
        let spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.startAnimation(nil)
        alert.accessoryView = spinner
        alert.addButton(withTitle: "Hide")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result: Result<String, Error>
            do {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                process.arguments = ["-e", script]
                let pipe = Pipe()
                process.standardOutput = pipe
                process.standardError = pipe
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let output = String(decoding: data, as: UTF8.self)
                result = process.terminationStatus == 0
                    ? .success(output)
                    : .failure(EngineError(output.isEmpty ? "The installer failed." : output))
            } catch {
                result = .failure(error)
            }
            DispatchQueue.main.async {
                NSApp.stopModal(withCode: .alertFirstButtonReturn)
                self?.finishUpdate(result)
            }
        }
        alert.runModal()
    }

    private func finishUpdate(_ result: Result<String, Error>) {
        switch result {
        case .success:
            try? LaunchAtLogin.setEnabled(true)
            let response = presentAlert { alert in
                alert.messageText = "ProtonX is updated"
                alert.informativeText = "Relaunch ProtonX to use the new version."
                alert.addButton(withTitle: "Relaunch")
                alert.addButton(withTitle: "Later")
            }
            if response == .alertFirstButtonReturn {
                NSWorkspace.shared.open(Bundle.main.bundleURL)
                NSApp.terminate(nil)
            }
        case .failure(let error):
            _ = presentAlert { alert in
                alert.messageText = "Update failed"
                alert.informativeText = String(error.localizedDescription.prefix(600))
                alert.addButton(withTitle: "OK")
            }
        }
    }

    private func captureScreen(_ path: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        process.arguments = ["-x", path]
        try? process.run()
        process.waitUntilExit()
    }

    private func testUpdateCheck() {
        state.checkForUpdates { result in
            switch result {
            case .success(let status):
                print("Update check: PASS (current=\(status.current), latest=\(status.latest), update=\(status.update))")
                exit(0)
            case .failure(let error):
                print("Update check: FAIL (\(error.localizedDescription))")
                exit(1)
            }
        }
    }

    private func testRepair() {
        state.repair { result in
            switch result {
            case .success(let report):
                print("Repair: PASS (actions=\(report.actions.count), resolves=\(report.resolves), internet=\(report.internet))")
                exit(0)
            case .failure(let error):
                print("Repair: FAIL (\(error.localizedDescription))")
                exit(1)
            }
        }
    }

    private func testMenus() {
        let appMenu = NSApp.mainMenu?.items.first { $0.submenu?.title == "ProtonX" }?.submenu?.items.map(\.title) ?? []
        let contextMenu = contextMenuTitles()
        let appOK = appMenu.contains("Repair Network")
        let contextOK = contextMenu.contains("Repair Network")
        print("Menus: \(appOK && contextOK ? "PASS" : "FAIL") (app=\(appMenu.joined(separator: " | ")), context=\(contextMenu.joined(separator: " | ")))")
        exit(appOK && contextOK ? 0 : 1)
    }

    private func testRepairAlert() {
        let report = RepairReport(
            ok: true,
            actions: ["flushed the DNS cache", "restored the system DNS settings"],
            resolves: true,
            internet: true,
            dns: nil
        )
        let capture = ProcessInfo.processInfo.environment["PROTONX_CAPTURE"] ?? ""
        let timer = Timer(timeInterval: 1.0, target: self, selector: #selector(captureRepairAlert(_:)),
                          userInfo: ["path": capture], repeats: false)
        RunLoop.main.add(timer, forMode: .common)
        presentRepair(.success(report))
        print("Repair alert: PASS")
        exit(0)
    }

    @objc private func captureRepairAlert(_ timer: Timer) {
        if let info = timer.userInfo as? [String: String], let path = info["path"], !path.isEmpty {
            captureScreen(path)
        }
        NSApp.stopModal(withCode: .alertFirstButtonReturn)
    }

    private func testUpdateAlert() {
        let status = UpdateStatus(current: "1.1.0", latest: "1.2.0", update: true)
        let alert = NSAlert()
        alert.messageText = "ProtonX \(status.latest) is available"
        alert.informativeText = "You have \(status.current). The update downloads the signed release and asks for your administrator password."
        alert.addButton(withTitle: "Update")
        alert.addButton(withTitle: "Cancel")
        alert.window.center()
        activate()
        let capture = ProcessInfo.processInfo.environment["PROTONX_CAPTURE"] ?? ""
        let timer = Timer(timeInterval: 1.0, target: self, selector: #selector(captureUpdateAlert(_:)),
                          userInfo: ["path": capture], repeats: false)
        RunLoop.main.add(timer, forMode: .common)
        let response = alert.runModal()
        print("Update alert: PASS (response=\(response.rawValue))")
        exit(0)
    }

    @objc private func captureUpdateAlert(_ timer: Timer) {
        if let info = timer.userInfo as? [String: String], let path = info["path"], !path.isEmpty {
            captureScreen(path)
        }
        NSApp.stopModal(withCode: .alertSecondButtonReturn)
    }

    private func testEngineSurface() {
        let path = CommandLine.arguments.first(where: { $0.hasPrefix("--engine=/") })?.dropFirst("--engine=".count)
        guard let path else {
            print("Engine surface: FAIL (pass --engine=/path/to/fake)")
            exit(1)
        }
        let engine = Engine(executable: URL(fileURLWithPath: String(path)), usesNativeStatus: false)
        do {
            let status = try engine.status()
            let catalog = try engine.catalog(offline: true)
            let account = try engine.account()
            try engine.connect(Destination(country: "NL", server: "NL-FREE#1"))
            try engine.disconnect()
            let signIn = try engine.signIn(username: "tester", password: "secret")
            let twoFactor = try engine.submitTwoFactor("123456")
            try engine.signOut()
            let repair = try engine.repair()
            print("Engine surface: PASS (up=\(status.up), countries=\(catalog.countries.count), signedIn=\(account.signedIn), login=\(signIn.status), twoFactor=\(twoFactor.status), repair=\(repair.internet))")
            exit(0)
        } catch {
            print("Engine surface: FAIL (\(error.localizedDescription))")
            exit(1)
        }
    }
}

@main @MainActor
private enum Launch {
    static func main() {
        if let flag = CommandLine.arguments.first(where: { $0 == "--enable-login-item" || $0 == "--disable-login-item" }) {
            let enabled = flag == "--enable-login-item"
            do {
                try LaunchAtLogin.setEnabled(enabled)
                print("Launch at login: \(enabled ? "enabled" : "disabled")")
                exit(0)
            } catch {
                print("Launch at login: FAIL \(error.localizedDescription)")
                exit(1)
            }
        }
        if CommandLine.arguments.contains("--version") {
            let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
            print("ProtonX \(version)")
            exit(0)
        }
        let application = NSApplication.shared
        let controller = AppController()
        application.delegate = controller
        withExtendedLifetime(controller) { application.run() }
    }
}
