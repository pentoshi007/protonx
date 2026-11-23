import AppKit

/// One selectable line in the account panel.
@MainActor
final class AccountRow: NSView {
    private let iconView = NSImageView()
    private let titleLabel: NSTextField
    private let checkView = NSImageView()
    private let active: Bool
    private var hovered = false
    var handler: (() -> Void)?

    init(title: String, symbol: String, checked: Bool = false, destructive: Bool = false, active: Bool = true) {
        self.active = active
        titleLabel = text(title, 12, .medium, color: destructive ? Theme.error : Theme.title)
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        let tint = destructive ? Theme.error : Theme.secondary
        iconView.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?
            .withSymbolConfiguration(.init(pointSize: 11, weight: .medium))
        iconView.contentTintColor = active ? tint : tint.withAlphaComponent(0.55)
        iconView.translatesAutoresizingMaskIntoConstraints = false
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        if !active { titleLabel.textColor = Theme.secondary }
        checkView.image = NSImage(systemSymbolName: "checkmark", accessibilityDescription: nil)?
            .withSymbolConfiguration(.init(pointSize: 10, weight: .bold))
        checkView.contentTintColor = Theme.accent
        checkView.isHidden = !checked
        checkView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(iconView)
        addSubview(titleLabel)
        addSubview(checkView)
        NSLayoutConstraint.activate([
            heightAnchor.constraint(equalToConstant: 28),
            iconView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 11),
            iconView.centerYAnchor.constraint(equalTo: centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 15),
            titleLabel.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 9),
            titleLabel.centerYAnchor.constraint(equalTo: centerYAnchor),
            checkView.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -11),
            checkView.centerYAnchor.constraint(equalTo: centerYAnchor),
            titleLabel.trailingAnchor.constraint(lessThanOrEqualTo: checkView.leadingAnchor, constant: -6),
        ])
        setAccessibilityElement(true)
        setAccessibilityRole(.menuItem)
        setAccessibilityLabel(title)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    // The popover window is not key when it first appears, so the first click
    // must reach this row instead of being spent on window activation.
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .inVisibleRect, .activeInKeyWindow], owner: self))
    }

    override func mouseEntered(with event: NSEvent) { hovered = true; needsDisplay = true }
    override func mouseExited(with event: NSEvent) { hovered = false; needsDisplay = true }

    override func mouseDown(with event: NSEvent) {
        guard active else { return }
        handler?()
    }

    override func draw(_ dirtyRect: NSRect) {
        if hovered && active {
            Theme.hover.setFill()
            NSBezierPath(roundedRect: bounds.insetBy(dx: 5, dy: 1), xRadius: 6, yRadius: 6).fill()
        }
        super.draw(dirtyRect)
    }
}

/// The account options, drawn inside the popover.
///
/// This is deliberately not an `NSMenu`. `NSMenu.popUp` runs a blocking modal
/// tracking loop, and AppKit tears that loop down when the window's key/active
/// state settles — which is exactly what the first click on the account button
/// causes. A plain view has no tracking loop, so nothing outside this file can
/// dismiss it.
@MainActor
final class AccountPanel: NSView {
    struct Model {
        let username: String
        let version: String
        let launchAtLogin: Bool
        let canSignOut: Bool
        let canUpdate: Bool
        let canRepair: Bool
    }

    private(set) var rowTitles: [String] = []
    var onDismiss: (() -> Void)?

    init(model: Model,
         onUpdates: @escaping () -> Void,
         onLaunchAtLogin: @escaping () -> Void,
         onRepair: @escaping () -> Void,
         onSignOut: @escaping () -> Void) {
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        wantsLayer = true
        layer?.shadowColor = NSColor.black.cgColor
        layer?.shadowOpacity = 0.16
        layer?.shadowRadius = 12
        layer?.shadowOffset = CGSize(width: 0, height: -4)

        let header = makeHeader(name: model.username, version: model.version)

        let updates = row("Check for Updates…", "arrow.triangle.2.circlepath", active: model.canUpdate, action: onUpdates)
        let login = row("Launch at Login", "power", checked: model.launchAtLogin, action: onLaunchAtLogin)
        let repair = row("Repair Network", "wrench.and.screwdriver", active: model.canRepair, action: onRepair)
        let signOut = row("Sign Out…", "rectangle.portrait.and.arrow.right", destructive: true, active: model.canSignOut, action: onSignOut)

        let stack = column([header, rule(), updates, login, repair, rule(), signOut], spacing: 0)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 10, yRadius: 10)
        Theme.paper.setFill()
        path.fill()
        Theme.rule.setStroke()
        path.lineWidth = 1
        path.stroke()
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        needsDisplay = true
    }

    private func makeHeader(name: String, version: String) -> NSView {
        let header = NSView()
        header.translatesAutoresizingMaskIntoConstraints = false
        let title = text(name, 12, .semibold)
        let build = text("ProtonX \(version)", 11, color: Theme.secondary)
        for label in [title, build] {
            label.translatesAutoresizingMaskIntoConstraints = false
            header.addSubview(label)
        }
        // Align the account name with the row titles, not with the icons.
        NSLayoutConstraint.activate([
            header.heightAnchor.constraint(equalToConstant: 44),
            title.leadingAnchor.constraint(equalTo: header.leadingAnchor, constant: 35),
            title.trailingAnchor.constraint(lessThanOrEqualTo: header.trailingAnchor, constant: -11),
            title.topAnchor.constraint(equalTo: header.topAnchor, constant: 10),
            build.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            build.trailingAnchor.constraint(lessThanOrEqualTo: header.trailingAnchor, constant: -11),
            build.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 1),
        ])
        return header
    }

    private func row(_ title: String, _ symbol: String, checked: Bool = false,
                     destructive: Bool = false, active: Bool = true,
                     action: @escaping () -> Void) -> AccountRow {
        rowTitles.append(title)
        let item = AccountRow(title: title, symbol: symbol, checked: checked, destructive: destructive, active: active)
        item.handler = { [weak self] in
            self?.onDismiss?()
            action()
        }
        return item
    }

    private func rule() -> NSView {
        let line = Hairline()
        line.translatesAutoresizingMaskIntoConstraints = false
        line.heightAnchor.constraint(equalToConstant: 1).isActive = true
        return line
    }
}

/// A one-point separator. `Surface` insets its fill by half a point on every
/// edge, which erases a 1 pt view, so the hairline fills its bounds directly.
@MainActor
final class Hairline: NSView {
    override func draw(_ dirtyRect: NSRect) {
        Theme.rule.setFill()
        bounds.fill()
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        needsDisplay = true
    }
}
