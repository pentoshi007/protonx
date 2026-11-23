import AppKit

enum Theme {
    static let background = adaptive(0xF0F4F2, 0x101D22)
    static let paper = adaptive(0xFCFEFD, 0x17292F)
    static let field = adaptive(0xE4EEEA, 0x20373D)
    static let hover = adaptive(0xDAE9E3, 0x2A444A)
    static let title = adaptive(0x183036, 0xECF5F1)
    static let secondary = adaptive(0x4D6366, 0xACC2C1)
    static let placeholder = adaptive(0x5A7073, 0x9FB7B5)
    static let rule = adaptive(0xD1E0DB, 0x345057)
    static let accent = adaptive(0x065D50, 0xA4E3CC)
    static let onAccent = adaptive(0xFFFFFF, 0x142D32)
    static let error = adaptive(0x902F28, 0xFFB0A3)
    static let errorFill = adaptive(0xFAE8E2, 0x422C2A)
    static let ink = rgb(0x142F36)
    static let inkField = rgb(0x29474D)
    static let inkHover = rgb(0x37575C)
    static let inkRule = rgb(0x36545A)
    static let chalk = rgb(0xEFF8F4)
    static let mist = rgb(0xACC9C6)
    static let signal = rgb(0xA4E3CC)
    static let amber = rgb(0xF1D391)

    nonisolated static func rgb(_ hex: UInt32) -> NSColor {
        let red = CGFloat((hex >> 16) & 255) / 255
        let green = CGFloat((hex >> 8) & 255) / 255
        let blue = CGFloat(hex & 255) / 255
        return NSColor(srgbRed: red, green: green, blue: blue, alpha: 1)
    }

    private static func adaptive(_ light: UInt32, _ dark: UInt32) -> NSColor {
        NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return rgb(isDark ? dark : light)
        }
    }
}

@MainActor
func text(_ value: String = "", _ size: CGFloat = 13, _ weight: NSFont.Weight = .regular,
          color: NSColor = Theme.title, font: NSFont? = nil) -> NSTextField {
    let label = NSTextField(labelWithString: value)
    label.font = font ?? .systemFont(ofSize: size, weight: weight)
    label.textColor = color
    label.lineBreakMode = .byTruncatingTail
    label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    return label
}

@MainActor
func mono(_ value: String = "", _ size: CGFloat = 11, color: NSColor = Theme.secondary) -> NSTextField {
    text(value, color: color, font: .monospacedSystemFont(ofSize: size, weight: .medium))
}

@MainActor
func placeholderText(_ value: String, size: CGFloat = 13) -> NSAttributedString {
    NSAttributedString(string: value, attributes: [
        .foregroundColor: Theme.placeholder,
        .font: NSFont.systemFont(ofSize: size),
    ])
}

@MainActor
func wrapped(_ value: String = "", color: NSColor = Theme.secondary, lines: Int = 3) -> NSTextField {
    let label = text(value, 12, color: color)
    label.usesSingleLineMode = false
    label.lineBreakMode = .byWordWrapping
    label.maximumNumberOfLines = lines
    return label
}

@MainActor
func column(_ children: [NSView], spacing: CGFloat = 8, fill: Bool = true) -> NSStackView {
    let stack = NSStackView(views: children)
    stack.orientation = .vertical
    stack.alignment = fill ? .width : .leading
    stack.spacing = spacing
    stack.detachesHiddenViews = true
    return stack
}

@MainActor
func line(_ children: [NSView], spacing: CGFloat = 8) -> NSStackView {
    let stack = NSStackView(views: children)
    stack.orientation = .horizontal
    stack.alignment = .centerY
    stack.spacing = spacing
    stack.detachesHiddenViews = true
    return stack
}

@MainActor
func install(_ child: NSView, in parent: NSView, x: CGFloat = 0, y: CGFloat = 0) {
    child.translatesAutoresizingMaskIntoConstraints = false
    parent.addSubview(child)
    NSLayoutConstraint.activate([
        child.leadingAnchor.constraint(equalTo: parent.leadingAnchor, constant: x),
        child.trailingAnchor.constraint(equalTo: parent.trailingAnchor, constant: -x),
        child.topAnchor.constraint(equalTo: parent.topAnchor, constant: y),
        child.bottomAnchor.constraint(equalTo: parent.bottomAnchor, constant: -y),
    ])
}

@MainActor
func space() -> NSView {
    let view = NSView()
    view.setContentHuggingPriority(.defaultLow, for: .horizontal)
    return view
}

@MainActor
func flag(_ code: String) -> String {
    let scalars = code.uppercased().unicodeScalars
    guard scalars.count == 2, scalars.allSatisfy({ (65...90).contains($0.value) }) else { return "◎" }
    return scalars.compactMap { UnicodeScalar($0.value + 127397).map(String.init) }.joined()
}

@MainActor
final class Surface: NSView {
    private let color: NSColor
    private let radius: CGFloat
    var border: NSColor? {
        didSet { needsDisplay = true }
    }
    var borderWidth: CGFloat = 1 {
        didSet { needsDisplay = true }
    }

    init(_ color: NSColor, radius: CGFloat = 0, border: NSColor? = nil) {
        self.color = color
        self.radius = radius
        self.border = border
        super.init(frame: .zero)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }
    override var isOpaque: Bool { radius == 0 }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: radius, yRadius: radius)
        color.setFill()
        path.fill()
        guard let border else { return }
        border.setStroke()
        path.lineWidth = borderWidth
        path.stroke()
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        needsDisplay = true
    }
}

@MainActor
final class FieldRow: NSView, NSTextFieldDelegate {
    let field: NSTextField
    var onChange: (() -> Void)?
    var onSubmit: (() -> Void)?
    private let shell: Surface
    private let caption: NSTextField

    init(_ caption: String, placeholder: String, secure: Bool = false) {
        field = secure ? NSSecureTextField() : NSTextField()
        shell = Surface(Theme.field, radius: 8, border: Theme.rule)
        self.caption = text(caption, 9.5, .semibold, color: Theme.secondary)
        super.init(frame: .zero)
        self.caption.attributedStringValue = NSAttributedString(string: caption, attributes: [
            .font: NSFont.systemFont(ofSize: 9.5, weight: .semibold),
            .foregroundColor: Theme.secondary,
            .kern: 0.7,
        ])
        field.placeholderAttributedString = placeholderText(placeholder)
        field.setAccessibilityLabel(placeholder)
        field.font = .systemFont(ofSize: 13)
        field.textColor = Theme.title
        field.isBordered = false
        field.drawsBackground = false
        field.focusRingType = .none
        field.usesSingleLineMode = true
        field.delegate = self
        field.target = self
        field.action = #selector(fireSubmit)
        addSubview(self.caption)
        addSubview(shell)
        shell.addSubview(field)
        setContentHuggingPriority(.required, for: .vertical)
        setContentCompressionResistancePriority(.required, for: .vertical)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: 57)
    }

    override func layout() {
        super.layout()
        caption.frame = NSRect(x: 2, y: bounds.height - 16, width: max(0, bounds.width - 2), height: 16)
        shell.frame = NSRect(x: 0, y: 0, width: bounds.width, height: 36)
        let fieldHeight = max(17, field.intrinsicContentSize.height)
        field.frame = NSRect(x: 10, y: (36 - fieldHeight) / 2, width: max(0, bounds.width - 20), height: fieldHeight)
    }

    func controlTextDidBeginEditing(_ notification: Notification) {
        shell.border = Theme.accent
        shell.borderWidth = 1.5
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        shell.border = Theme.rule
        shell.borderWidth = 1
    }

    func controlTextDidChange(_ notification: Notification) {
        onChange?()
    }

    @objc private func fireSubmit() {
        onSubmit?()
    }
}

@MainActor
final class ConsoleButton: NSButton {
    enum Style { case filled, quiet, icon, routePrimary, routeQuiet }

    private let style: Style
    private let height: CGFloat
    private var label = ""
    private var symbol = ""
    private var indicated = false
    private var hovered = false
    var handler: (() -> Void)?

    init(_ title: String, symbol: String = "", style: Style = .quiet, height: CGFloat = 30) {
        self.style = style
        self.height = height
        super.init(frame: .zero)
        setButtonType(.momentaryPushIn)
        isBordered = false
        imageHugsTitle = true
        focusRingType = .exterior
        target = self
        action = #selector(performAction)
        setContent(title, symbol: symbol)
        setContentHuggingPriority(.defaultHigh, for: .horizontal)
        setContentCompressionResistancePriority(.required, for: .horizontal)
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    override var intrinsicContentSize: NSSize {
        if style == .icon { return NSSize(width: height, height: height) }
        return NSSize(width: max(60, super.intrinsicContentSize.width + 18), height: height)
    }

    override var isEnabled: Bool {
        didSet { if isEnabled != oldValue { applyContent() } }
    }

    func setContent(_ title: String, symbol: String = "", active: Bool = false) {
        guard label != title || self.symbol != symbol || indicated != active else { return }
        label = title
        self.symbol = symbol
        indicated = active
        applyContent()
    }

    private var ink: NSColor {
        switch style {
        case .routePrimary: return Theme.ink
        case .routeQuiet: return Theme.chalk
        case .filled: return Theme.onAccent
        case .quiet, .icon: return indicated ? Theme.accent : Theme.title
        }
    }

    private var fill: NSColor {
        switch style {
        case .routePrimary: return Theme.signal
        case .routeQuiet: return hovered ? Theme.inkHover : Theme.inkField
        case .filled: return Theme.accent
        case .quiet: return indicated || hovered ? Theme.hover : Theme.field
        case .icon: return indicated || hovered ? Theme.hover : .clear
        }
    }

    private func applyContent() {
        let foreground = isEnabled ? ink : (style == .filled ? Theme.secondary : ink.withAlphaComponent(0.82))
        title = style == .icon ? "" : label
        attributedTitle = NSAttributedString(string: title, attributes: [
            .font: NSFont.systemFont(ofSize: 12, weight: .semibold), .foregroundColor: foreground,
        ])
        image = symbol.isEmpty ? nil : NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?
            .withSymbolConfiguration(.init(pointSize: style == .icon ? 13 : 11, weight: .semibold))
        image?.isTemplate = true
        imagePosition = style == .icon ? .imageOnly : .imageLeading
        contentTintColor = foreground
        toolTip = style == .icon ? label : nil
        setAccessibilityLabel(label)
        invalidateIntrinsicContentSize()
        needsDisplay = true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .inVisibleRect, .activeInKeyWindow], owner: self))
    }

    override func mouseEntered(with event: NSEvent) { hovered = true; needsDisplay = true }
    override func mouseExited(with event: NSEvent) { hovered = false; needsDisplay = true }
    // The menu-bar popover is usually not key when it first appears. Without
    // this, the first click only activates its window and the control never
    // fires; the second click works, which is the reported symptom.
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func viewDidChangeEffectiveAppearance() { super.viewDidChangeEffectiveAppearance(); applyContent() }

    private var resolvedFill: NSColor {
        guard !isEnabled else { return fill }
        switch style {
        case .filled: return Theme.field
        case .routePrimary: return Theme.signal.withAlphaComponent(0.55)
        case .routeQuiet: return Theme.inkField.withAlphaComponent(0.7)
        case .quiet, .icon: return Theme.field.withAlphaComponent(0.7)
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        let opacity: CGFloat = cell?.isHighlighted == true ? 0.74 : 1
        resolvedFill.withAlphaComponent(resolvedFill.alphaComponent * opacity).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 7, yRadius: 7).fill()
        super.draw(dirtyRect)
    }

    override var focusRingMaskBounds: NSRect { bounds }
    override func drawFocusRingMask() { NSBezierPath(roundedRect: bounds, xRadius: 7, yRadius: 7).fill() }

    @objc private func performAction() { handler?() }
}

@MainActor
final class InlineSpinner: NSProgressIndicator {
    private var running = false

    init() {
        super.init(frame: .zero)
        style = .spinning
        controlSize = .small
        isIndeterminate = true
        isDisplayedWhenStopped = false
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: 17).isActive = true
        heightAnchor.constraint(equalToConstant: 17).isActive = true
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    func setRunning(_ value: Bool) {
        guard value != running else { return }
        running = value
        if value { startAnimation(nil) } else { stopAnimation(nil) }
    }
}
