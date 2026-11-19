import AppKit

@MainActor
final class DirectoryCell: NSTableCellView {
    static let reuse = NSUserInterfaceItemIdentifier("directory-cell")

    private let marker = text("", 18, .medium)
    private let markerTile = Surface(Theme.field, radius: 8)
    private let name = text("", 13, .semibold)
    private let detail = text("", 11, color: Theme.secondary)
    private let meter = LoadMeter()
    private let amount = mono("", 11)
    private let value = mono("", 11)
    private let more = text("›", 20, .medium, color: Theme.secondary)
    private let save = ConsoleButton("Save server", symbol: "star", style: .icon, height: 30)
    private let connect = ConsoleButton("Connect", style: .quiet, height: 29)
    private let serverTools: NSStackView
    private let countryTools: NSStackView

    override init(frame: NSRect) {
        serverTools = line([line([meter, amount], spacing: 5), save, connect], spacing: 7)
        countryTools = line([value, more], spacing: 13)
        super.init(frame: frame)
        identifier = Self.reuse
        configureLayout()
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    private func configureLayout() {
        let label = column([name, detail], spacing: 2, fill: false)
        marker.alignment = .center
        marker.translatesAutoresizingMaskIntoConstraints = false
        markerTile.addSubview(marker)
        NSLayoutConstraint.activate([
            marker.centerXAnchor.constraint(equalTo: markerTile.centerXAnchor),
            marker.centerYAnchor.constraint(equalTo: markerTile.centerYAnchor),
            markerTile.widthAnchor.constraint(equalToConstant: 35),
            markerTile.heightAnchor.constraint(equalToConstant: 33),
            amount.widthAnchor.constraint(equalToConstant: 32),
            connect.widthAnchor.constraint(equalToConstant: 77),
        ])
        amount.alignment = .right
        let body = line([markerTile, label, space(), countryTools, serverTools], spacing: 9)
        install(body, in: self, x: 10, y: 6)
    }

    func render(_ row: DirectoryRow, state: AppState) {
        switch row {
        case .country(let code, let title, let count):
            markerTile.isHidden = false
            marker.stringValue = flag(code)
            name.stringValue = title
            detail.stringValue = code
            value.stringValue = count.formatted()
            value.setAccessibilityLabel("\(count) online servers")
            countryTools.isHidden = false
            serverTools.isHidden = true
        case .server(let target, let location, let server):
            markerTile.isHidden = true
            countryTools.isHidden = true
            serverTools.isHidden = false
            name.stringValue = target.server
            detail.stringValue = server.map { $0.city.isEmpty ? location : $0.city } ?? "\(location) · Not listed"
            amount.stringValue = server.map { "\($0.load)%" } ?? "—"
            amount.setAccessibilityLabel(server.map { "Server load \($0.load) percent" } ?? "Load unavailable")
            meter.update(server?.load)
            updateActions(target: target, available: server != nil, state: state)
        }
    }

    private func updateActions(target: Destination, available: Bool, state: AppState) {
        let saved = state.savedRoutes.contains(target)
        save.setContent(saved ? "Remove \(target.server) from saved" : "Save \(target.server)",
                        symbol: saved ? "star.fill" : "star", active: saved)
        save.handler = { [weak state] in state?.toggleSaved(target) }
        connect.setContent(actionTitle(target, state: state), active: state.activeDestination == target)
        connect.handler = { [weak state] in state?.connect(target) }
        connect.isEnabled = available && state.canConnect && state.activeDestination != target
        connect.toolTip = available ? nil : "This server isn’t in the current free directory."
    }

    private func actionTitle(_ target: Destination, state: AppState) -> String {
        if state.operation?.destination == target { return "Working…" }
        if state.activeDestination == target { return "In use" }
        return state.isUp ? "Switch" : "Connect"
    }
}

@MainActor
final class DirectoryLine: NSTableRowView {
    override var isEmphasized: Bool {
        get { false }
        set { }
    }

    override func drawBackground(in dirtyRect: NSRect) {
        Theme.rule.setFill()
        NSRect(x: 9, y: bounds.maxY - 1, width: bounds.width - 18, height: 1).fill()
    }

    override func drawSelection(in dirtyRect: NSRect) {
        Theme.field.setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 3, dy: 2), xRadius: 7, yRadius: 7).fill()
    }
}

@MainActor
private final class LoadMeter: NSView {
    private var load: Int?
    override var intrinsicContentSize: NSSize { NSSize(width: 29, height: 7) }

    func update(_ value: Int?) {
        guard load != value else { return }
        load = value
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        let clamped = CGFloat(max(0, min(100, load ?? 0))) / 100
        let day = (load ?? 0) < 85 ? Theme.accent : Theme.error
        Theme.rule.setFill()
        NSBezierPath(roundedRect: NSRect(x: 0, y: 2, width: bounds.width, height: 3), xRadius: 1.5, yRadius: 1.5).fill()
        guard clamped > 0 else { return }
        day.setFill()
        let width = max(3, bounds.width * clamped)
        NSBezierPath(roundedRect: NSRect(x: 0, y: 2, width: width, height: 3), xRadius: 1.5, yRadius: 1.5).fill()
    }
}
