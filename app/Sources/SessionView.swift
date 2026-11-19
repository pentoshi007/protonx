import AppKit

@MainActor
final class SessionView: NSView {
    private let state: AppState
    private let markTile = Surface(Theme.ink, radius: 13)
    private let markImage = NSImageView()
    private let spinner = InlineSpinner()
    private let heading = text("", 22, .semibold)
    private let subheading = wrapped("", color: Theme.secondary, lines: 3)
    private let username = FieldRow("USERNAME", placeholder: "Proton username or email")
    private let password = FieldRow("PASSWORD", placeholder: "Password", secure: true)
    private let code = FieldRow("CODE", placeholder: "Six-digit code")
    private let submit = ConsoleButton("Sign in", style: .filled, height: 40)
    private let retry = ConsoleButton("Try again", symbol: "arrow.clockwise", height: 34)
    private let noteRow = NSView()
    private var requiresCode = false

    init(state: AppState) {
        self.state = state
        super.init(frame: .zero)
        assemble()
        submit.handler = { [weak self] in self?.submitInput() }
        retry.handler = { [weak state] in state?.retrySession() }
        for row in [username, password, code] {
            row.onChange = { [weak self] in self?.updateSubmit() }
            row.onSubmit = { [weak self] in self?.submitInput() }
        }
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    private func assemble() {
        let markRow = NSView()
        markTile.translatesAutoresizingMaskIntoConstraints = false
        markImage.image = routeMark(connected: true)
        markImage.contentTintColor = Theme.signal
        markImage.imageScaling = .scaleNone
        markImage.translatesAutoresizingMaskIntoConstraints = false
        markTile.addSubview(markImage)
        markTile.addSubview(spinner)
        markRow.addSubview(markTile)
        NSLayoutConstraint.activate([
            markRow.heightAnchor.constraint(equalToConstant: 46),
            markTile.centerXAnchor.constraint(equalTo: markRow.centerXAnchor),
            markTile.centerYAnchor.constraint(equalTo: markRow.centerYAnchor),
            markTile.widthAnchor.constraint(equalToConstant: 46),
            markTile.heightAnchor.constraint(equalToConstant: 46),
            markImage.centerXAnchor.constraint(equalTo: markTile.centerXAnchor),
            markImage.centerYAnchor.constraint(equalTo: markTile.centerYAnchor),
            spinner.centerXAnchor.constraint(equalTo: markTile.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: markTile.centerYAnchor),
        ])
        heading.alignment = .center
        subheading.alignment = .center
        subheading.preferredMaxLayoutWidth = 330
        configureNote()
        let form = column([markRow, heading, subheading, username, password, code, submit, retry, noteRow], spacing: 12, fill: false)
        form.setCustomSpacing(16, after: markRow)
        form.setCustomSpacing(6, after: heading)
        form.setCustomSpacing(20, after: subheading)
        form.setCustomSpacing(14, after: submit)
        form.translatesAutoresizingMaskIntoConstraints = false
        addSubview(form)
        for item in [markRow, heading, subheading, username, password, code, submit, retry, noteRow] {
            item.widthAnchor.constraint(equalToConstant: 330).isActive = true
        }
        NSLayoutConstraint.activate([
            noteRow.heightAnchor.constraint(equalToConstant: 16),
            submit.heightAnchor.constraint(equalToConstant: 40),
            retry.heightAnchor.constraint(equalToConstant: 34),
            form.centerXAnchor.constraint(equalTo: centerXAnchor),
            form.centerYAnchor.constraint(equalTo: centerYAnchor, constant: -12),
            form.topAnchor.constraint(greaterThanOrEqualTo: topAnchor),
            form.bottomAnchor.constraint(lessThanOrEqualTo: bottomAnchor),
        ])
    }

    private func configureNote() {
        let lock = NSImageView(image: NSImage(systemSymbolName: "lock.fill", accessibilityDescription: nil) ?? NSImage())
        lock.contentTintColor = Theme.secondary
        lock.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 9, weight: .semibold)
        lock.translatesAutoresizingMaskIntoConstraints = false
        let note = text("Your password is used locally and never stored.", 11, color: Theme.secondary)
        note.alignment = .center
        let row = line([lock, note], spacing: 5)
        row.translatesAutoresizingMaskIntoConstraints = false
        noteRow.addSubview(row)
        NSLayoutConstraint.activate([
            row.centerXAnchor.constraint(equalTo: noteRow.centerXAnchor),
            row.topAnchor.constraint(equalTo: noteRow.topAnchor),
            row.bottomAnchor.constraint(equalTo: noteRow.bottomAnchor),
            row.leadingAnchor.constraint(greaterThanOrEqualTo: noteRow.leadingAnchor),
            row.trailingAnchor.constraint(lessThanOrEqualTo: noteRow.trailingAnchor),
        ])
    }

    func render(presented: Bool) {
        switch state.session {
        case .checking:
            showStatus("Checking your session…", "Reading your ProtonX session from this Mac.", canRetry: false)
        case .unavailable(let reason):
            showStatus("Session unavailable", reason, canRetry: true)
        case .ready(let account):
            if !account.signedIn { showForm(account) }
        }
        spinner.setRunning(presented && (state.session == .checking || state.authBusy))
    }

    func clearSensitiveFields() {
        password.field.stringValue = ""
        code.field.stringValue = ""
        updateSubmit()
    }

    private func showStatus(_ title: String, _ detail: String, canRetry: Bool) {
        heading.stringValue = title
        subheading.stringValue = detail
        setFieldsVisible(false)
        submit.isHidden = true
        retry.isHidden = !canRetry
        noteRow.isHidden = true
        markImage.isHidden = canRetry
        spinner.isHidden = !canRetry
    }

    private func showForm(_ account: Account) {
        requiresCode = account.pending
        if username.field.stringValue.isEmpty, let hint = account.username { username.field.stringValue = hint }
        heading.stringValue = requiresCode ? "Two-factor code" : "Sign in to Proton"
        subheading.stringValue = requiresCode
            ? "Enter the six-digit code from your authenticator app."
            : "ProtonX keeps its own session, so this is the only time you sign in."
        username.isHidden = requiresCode
        password.isHidden = requiresCode
        code.isHidden = !requiresCode
        submit.isHidden = false
        retry.isHidden = true
        noteRow.isHidden = false
        markImage.isHidden = false
        spinner.isHidden = !state.authBusy
        for row in [username, password, code] { row.field.isEnabled = !state.authBusy }
        updateSubmit()
    }

    private func setFieldsVisible(_ visible: Bool) {
        username.isHidden = !visible
        password.isHidden = !visible
        code.isHidden = true
    }

    private func updateSubmit() {
        let pin = code.field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let valid = requiresCode
            ? pin.utf8.count == 6 && pin.utf8.allSatisfy { (48...57).contains($0) }
            : !username.field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !password.field.stringValue.isEmpty
        let action = requiresCode ? "Verify code" : "Sign in"
        submit.setContent(state.authBusy ? "Checking…" : action)
        submit.isEnabled = valid && !state.authBusy
    }

    private func submitInput() {
        guard submit.isEnabled, !submit.isHidden else { return }
        let secret = requiresCode ? code.field.stringValue : password.field.stringValue
        let name = username.field.stringValue
        clearSensitiveFields()
        if requiresCode { state.submitTwoFactor(secret) } else { state.signIn(username: name, password: secret) }
    }
}
