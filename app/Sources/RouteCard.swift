import AppKit

@MainActor
final class RouteCard: NSView {
    private let badge = mono("", 10, color: Theme.mist)
    private let title = text("", 27, .semibold, color: Theme.chalk)
    private let detail = text("", 12, .medium, color: Theme.mist)
    private let local = mono("", 10, color: Theme.mist)
    private let metrics = mono("", 10, color: Theme.signal)
    private let primary = ConsoleButton("Connect", style: .routePrimary)
    private let secondary = ConsoleButton("Disconnect", style: .routeQuiet)
    private let repair = ConsoleButton("Repair Network", symbol: "wrench.and.screwdriver", style: .routeQuiet)
    private let spinner = InlineSpinner()
    private let diagram = RouteDiagram()
    private let byteCount = ByteCountFormatter()

    override init(frame: NSRect) {
        super.init(frame: frame)
        let surface = Surface(Theme.ink, radius: 15, border: Theme.inkRule)
        install(surface, in: self)
        byteCount.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        assemble(surface)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    private func assemble(_ surface: NSView) {
        let body = column([badge, title, detail], spacing: 3, fill: false)
        let top = line([body, space(), diagram], spacing: 10)
        let actions = line([primary, secondary, repair, spinner, space()], spacing: 7)
        let divider = Surface(Theme.inkRule)
        divider.heightAnchor.constraint(equalToConstant: 1).isActive = true
        let lower = line([local, space(), metrics])
        let contents = column([top, actions, divider, lower], spacing: 8)
        contents.setCustomSpacing(7, after: divider)
        install(contents, in: surface, x: 15, y: 12)
        actions.heightAnchor.constraint(equalToConstant: 30).isActive = true
        badge.setContentHuggingPriority(.required, for: .vertical)
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    }

    func render(_ state: AppState, visible: Bool) {
        primary.isHidden = true
        secondary.isHidden = true
        repair.isHidden = true
        repair.isEnabled = state.operation == nil
        repair.handler = { [weak state] in state?.repair() }
        spinner.setRunning(visible && state.operation != nil)
        spinner.isHidden = state.operation == nil
        metrics.stringValue = ""
        if let operation = state.operation {
            renderOperation(operation, state: state)
        } else if let status = state.status, status.up {
            renderOnline(status, state: state)
        } else if state.status == nil {
            renderUnknown(state)
        } else {
            renderOffline(state)
        }
        repair.isHidden = !(state.dnsStale || state.statusError != nil)
    }

    private func renderOperation(_ operation: TunnelOperation, state: AppState) {
        switch operation {
        case .signingOut:
            update("SIGNING OUT", title: "Ending your session", detail: "Disconnecting and clearing your local sign-in", code: nil, mode: .working)
        case .disconnecting:
            update("DISCONNECTING", title: "Closing tunnel", detail: "Restoring the Mac’s network settings", code: nil, mode: .working)
        case .repairing:
            update("REPAIRING", title: "Restoring network", detail: "Stopping the tunnel and restoring DNS", code: nil, mode: .working)
        case .switching(let target):
            update("SWITCHING", title: countryName(target.country, in: state), detail: target.server, code: target.country, mode: .working)
        case .connecting(let target):
            update("CONNECTING", title: countryName(target.country, in: state), detail: target.server, code: target.country, mode: .working)
        }
        local.stringValue = "WireGuard"
    }

    private func renderOnline(_ status: Status, state: AppState) {
        let active = status.server
        let country = active.map { countryName($0.country, in: state) } ?? "Active tunnel"
        let detail = active.map { routeDescription($0.city, $0.label) } ?? "WireGuard"
        let handshake = status.peer?.latestHandshake ?? 0
        update(handshake > 0 ? "CONNECTED" : "AWAITING HANDSHAKE", title: country, detail: detail,
               code: active?.country, mode: handshake > 0 ? .online : .working)
        secondary.setContent("Disconnect", symbol: "stop.fill")
        secondary.isHidden = false
        secondary.handler = { [weak state] in state?.disconnect() }
        let endpoint = [status.address, status.interface].compactMap { $0 }.joined(separator: " / ")
        let last = handshakeText(handshake)
        local.stringValue = [endpoint, last].filter { !$0.isEmpty }.joined(separator: " · ")
        local.toolTip = handshake > 0 ? "Last handshake: \(Date(timeIntervalSince1970: TimeInterval(handshake)).formatted())" : "No handshake yet"
        if let peer = status.peer {
            let received = byteCount.string(fromByteCount: peer.rxBytes)
            let sent = byteCount.string(fromByteCount: peer.txBytes)
            metrics.stringValue = "↓ \(received)  ↑ \(sent)"
            metrics.setAccessibilityLabel("Received \(received), sent \(sent)")
        }
    }

    private func renderUnknown(_ state: AppState) {
        let failed = state.statusError != nil
        update(failed ? "STATUS UNAVAILABLE" : "CHECKING TUNNEL", title: failed ? "Status unavailable" : "Checking route…",
               detail: failed ? "Refresh to check the local tunnel." : "Reading the local tunnel state", code: nil, mode: .idle)
        local.stringValue = "WireGuard"
        local.toolTip = state.statusError
        if failed {
            secondary.setContent("Check again", symbol: "arrow.clockwise")
            secondary.isHidden = false
            secondary.handler = { [weak state] in state?.refreshStatus() }
        }
    }

    private func renderOffline(_ state: AppState) {
        let last = state.lastServer
        let recent = last.flatMap { state.server(for: $0.destination) == nil ? nil : $0.destination }
        let best = state.catalog?.bestDestination(in: nil)
        let heading = last.map { countryName($0.country, in: state) } ?? "Choose a route"
        let subtitle = last.map { "Last used · " + routeDescription($0.city, $0.label) } ?? "Pick a location or connect by server load."
        update("DISCONNECTED", title: heading, detail: subtitle, code: last?.country, mode: .idle)
        local.stringValue = "No active tunnel"
        local.toolTip = nil
        if let recent { setConnect(primary, title: "Reconnect", symbol: "arrow.counterclockwise", to: recent, state: state) }
        if let best, best != recent {
            setConnect(recent == nil ? primary : secondary, title: "Quick connect", symbol: "bolt.fill", to: best, state: state)
        }
    }

    private func setConnect(_ button: ConsoleButton, title: String, symbol: String, to target: Destination, state: AppState) {
        button.setContent(title, symbol: symbol)
        button.isHidden = false
        button.isEnabled = state.canConnect
        button.toolTip = "\(countryName(target.country, in: state)) · \(target.server)"
        button.handler = { [weak state] in state?.connect(target) }
    }

    private func update(_ phase: String, title heading: String, detail subtitle: String, code: String?, mode: RouteDiagram.Mode) {
        badge.stringValue = "●  " + phase
        switch mode {
        case .idle: badge.textColor = Theme.mist
        case .online: badge.textColor = Theme.signal
        case .working: badge.textColor = Theme.amber
        }
        title.stringValue = heading
        detail.stringValue = subtitle
        diagram.update(code: code, mode: mode)
    }

    private func countryName(_ code: String, in state: AppState) -> String {
        state.catalog?.country(code)?.name ?? Locale.current.localizedString(forRegionCode: code) ?? code
    }

    private func handshakeText(_ stamp: Int) -> String {
        guard stamp > 0 else { return "No handshake" }
        let seconds = max(0, Int(Date().timeIntervalSince1970) - stamp)
        if seconds < 60 { return "HS \(seconds)s" }
        if seconds < 3600 { return "HS \(seconds / 60)m" }
        return "HS \(seconds / 3600)h"
    }

    private func routeDescription(_ city: String, _ name: String) -> String {
        city.isEmpty || city == "-" ? name : "\(city)  /  \(name)"
    }
}

@MainActor
private final class RouteDiagram: NSView {
    enum Mode { case idle, working, online }

    private var mode = Mode.idle
    private var code: String?

    override var intrinsicContentSize: NSSize { NSSize(width: 106, height: 68) }

    func update(code: String?, mode: Mode) {
        guard code != self.code || mode != self.mode else { return }
        self.code = code
        self.mode = mode
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        let start = NSPoint(x: 9, y: 27)
        let end = NSPoint(x: 95, y: 52)
        drawGrid()
        let route = NSBezierPath()
        route.move(to: start)
        route.curve(to: end, controlPoint1: NSPoint(x: 61, y: 27), controlPoint2: NSPoint(x: 40, y: 52))
        let stroke = mode == .online ? Theme.signal : (mode == .working ? Theme.amber : Theme.mist)
        stroke.setStroke()
        route.lineWidth = 1.35
        if mode != .online { route.setLineDash([2.5, 3], count: 2, phase: 0) }
        route.stroke()
        drawNode(at: start, color: Theme.mist, emphasized: false)
        drawNode(at: end, color: stroke, emphasized: mode == .online)
        drawCode("MAC", at: NSPoint(x: 5, y: 7))
        drawCode(code ?? "—", at: NSPoint(x: 83, y: 7))
    }

    private func drawGrid() {
        Theme.inkRule.setFill()
        let points = NSBezierPath()
        for x in stride(from: 9, through: 101, by: 10) {
            for y in stride(from: 22, through: 66, by: 10) {
                points.appendOval(in: NSRect(x: x, y: y, width: 1, height: 1))
            }
        }
        points.fill()
    }

    private func drawNode(at point: NSPoint, color: NSColor, emphasized: Bool) {
        let frame = NSRect(x: point.x - 3.5, y: point.y - 3.5, width: 7, height: 7)
        let ring = NSBezierPath(ovalIn: frame)
        (emphasized ? color : Theme.ink).setFill()
        ring.fill()
        color.setStroke()
        ring.lineWidth = 1.25
        ring.stroke()
        if emphasized {
            color.withAlphaComponent(0.30).setStroke()
            NSBezierPath(ovalIn: frame.insetBy(dx: -3.5, dy: -3.5)).stroke()
        }
    }

    private func drawCode(_ text: String, at point: NSPoint) {
        (text as NSString).draw(at: point, withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 10, weight: .semibold), .foregroundColor: Theme.mist,
        ])
    }
}
