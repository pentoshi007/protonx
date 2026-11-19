import AppKit

@MainActor
final class DirectoryView: NSView, NSTableViewDataSource, NSTableViewDelegate, NSSearchFieldDelegate {
    private let state: AppState
    private let search = NSSearchField()
    private let searchShell = Surface(Theme.field, radius: 8)
    private let table = DirectoryTable()
    private let scroll = NSScrollView()
    private let all = ConsoleButton("Locations", symbol: "globe", height: 32)
    private let saved = ConsoleButton("Saved", symbol: "star", height: 32)
    private let tabs = NSStackView()
    private let back = ConsoleButton("All locations", symbol: "chevron.left", style: .icon, height: 32)
    private let countryTitle = text("", 17, .semibold)
    private let best = ConsoleButton("Lowest load", symbol: "bolt.fill", height: 32)
    private let section = mono("", 10)
    private let count = mono("", 10)
    private let legend = line([])
    private let placeholder = NSView()
    private let blankTitle = text("", 15, .semibold)
    private let blankDetail = wrapped("", lines: 4)
    private let blankAction = ConsoleButton("Refresh", symbol: "arrow.clockwise")
    private let spinner = InlineSpinner()

    private var input: DirectoryInput?
    private var controls: RowControls?
    private var rows: [DirectoryRow] = []
    private var isPresented = false
    private(set) var page = DirectoryPage.locations

    init(state: AppState, page: DirectoryPage) {
        self.state = state
        self.page = page
        super.init(frame: .zero)
        assemble()
        configureSearch()
        configureTable()
        configureHandlers()
    }

    required init?(coder: NSCoder) { fatalError("unsupported") }

    private func assemble() {
        tabs.orientation = .horizontal
        tabs.spacing = 6
        tabs.addArrangedSubview(all)
        tabs.addArrangedSubview(saved)
        let header = line([tabs, back, countryTitle, space(), best], spacing: 6)
        legend.addArrangedSubview(section)
        legend.addArrangedSubview(space())
        legend.addArrangedSubview(count)
        legend.edgeInsets = NSEdgeInsets(top: 0, left: 10, bottom: 0, right: 12)
        let panel = Surface(Theme.paper, radius: 10, border: Theme.rule)
        configurePlaceholder()
        install(scroll, in: panel, x: 2, y: 2)
        install(placeholder, in: panel, x: 10, y: 2)
        let contents = column([header, searchShell, legend, panel], spacing: 9)
        contents.setCustomSpacing(6, after: legend)
        install(contents, in: self)
        search.translatesAutoresizingMaskIntoConstraints = false
        searchShell.addSubview(search)
        NSLayoutConstraint.activate([
            searchShell.heightAnchor.constraint(equalToConstant: 30),
            search.leadingAnchor.constraint(equalTo: searchShell.leadingAnchor, constant: 8),
            search.trailingAnchor.constraint(equalTo: searchShell.trailingAnchor, constant: -8),
            search.centerYAnchor.constraint(equalTo: searchShell.centerYAnchor),
        ])
        panel.heightAnchor.constraint(greaterThanOrEqualToConstant: 128).isActive = true
        setContentHuggingPriority(.defaultLow, for: .vertical)
    }

    private func configurePlaceholder() {
        blankTitle.alignment = .center
        blankDetail.alignment = .center
        blankDetail.preferredMaxLayoutWidth = 280
        let center = column([spinner, blankTitle, blankDetail, blankAction], spacing: 8, fill: false)
        center.alignment = .centerX
        center.translatesAutoresizingMaskIntoConstraints = false
        placeholder.addSubview(center)
        NSLayoutConstraint.activate([
            center.centerYAnchor.constraint(equalTo: placeholder.centerYAnchor),
            center.centerXAnchor.constraint(equalTo: placeholder.centerXAnchor),
            center.leadingAnchor.constraint(greaterThanOrEqualTo: placeholder.leadingAnchor, constant: 8),
            center.trailingAnchor.constraint(lessThanOrEqualTo: placeholder.trailingAnchor, constant: -8),
            blankDetail.widthAnchor.constraint(lessThanOrEqualToConstant: 280),
        ])
    }

    private func configureSearch() {
        search.font = .systemFont(ofSize: 13)
        search.textColor = Theme.title
        search.placeholderAttributedString = placeholderText("Find a country, city, or server")
        search.isBordered = false
        search.drawsBackground = false
        search.focusRingType = .none
        search.delegate = self
        search.sendsSearchStringImmediately = true
        search.target = self
        search.action = #selector(searchChanged)
        search.setAccessibilityLabel("Search servers and locations")
    }

    private func configureTable() {
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.contentInsets = .init(top: 0, left: 0, bottom: 0, right: 0)
        let tableColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("route"))
        tableColumn.resizingMask = .autoresizingMask
        table.addTableColumn(tableColumn)
        table.headerView = nil
        table.style = .plain
        table.backgroundColor = .clear
        table.rowHeight = 47
        table.intercellSpacing = .zero
        table.columnAutoresizingStyle = .lastColumnOnlyAutoresizingStyle
        table.delegate = self
        table.dataSource = self
        table.target = self
        table.action = #selector(rowClicked)
        table.setAccessibilityLabel("Server directory")
        scroll.documentView = table
    }

    private func configureHandlers() {
        for button in [all, saved, back, best] { button.refusesFirstResponder = true }
        all.handler = { [weak self] in self?.navigate(.locations) }
        saved.handler = { [weak self] in self?.navigate(.saved) }
        back.handler = { [weak self] in self?.navigate(.locations) }
        blankAction.handler = { [weak state] in state?.refresh() }
        table.activateRow = { [weak self] row in self?.activate(row) }
    }

    func navigate(_ destination: DirectoryPage) {
        guard page != destination else { return }
        page = destination
        search.stringValue = ""
        render(presented: isPresented)
        window?.makeFirstResponder(rows.isEmpty ? search : table)
    }

    func focusSearch() {
        window?.makeFirstResponder(search)
        search.selectText(nil)
    }

    func focusList() {
        window?.makeFirstResponder(table)
    }

    func render(presented: Bool) {
        isPresented = presented
        let source = DirectoryInput(page: page, catalog: state.catalog, saved: state.savedRoutes, query: search.stringValue)
        let actions = RowControls(active: state.activeDestination, canConnect: state.canConnect, operation: state.operation)
        let didChange = source != input
        if didChange { applyRows(source) }
        if didChange || actions != controls {
            controls = actions
            renderVisibleRows()
        }
        renderHeader()
        renderPlaceholder(searching: !source.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private func applyRows(_ source: DirectoryInput) {
        let resetScroll = source.page != input?.page || source.query != input?.query
        input = source
        let next = source.rows
        guard next != rows || resetScroll else { return }
        rows = next
        table.reloadData()
        if resetScroll { table.deselectAll(nil) }
        if resetScroll, !rows.isEmpty { table.scrollRowToVisible(0) }
    }

    private func renderHeader() {
        let savedCount = state.savedRoutes.count
        all.setContent("Locations", symbol: "globe", active: page == .locations)
        saved.setContent(savedCount > 0 ? "Saved \(savedCount)" : "Saved", symbol: "star", active: page == .saved)
        if case .country(let code) = page {
            renderCountryHeader(code)
        } else {
            tabs.isHidden = false
            back.isHidden = true
            countryTitle.isHidden = true
            best.isHidden = true
            search.placeholderAttributedString = placeholderText(page == .saved ? "Search saved servers" : "Find a country, city, or server")
            section.stringValue = page == .saved ? "SAVED SERVERS" : "FREE DIRECTORY"
        }
        legend.isHidden = rows.isEmpty
        count.stringValue = countLabel()
    }

    private func renderCountryHeader(_ code: String) {
        let name = state.catalog?.country(code)?.name ?? Locale.current.localizedString(forRegionCode: code) ?? code
        tabs.isHidden = true
        back.isHidden = false
        countryTitle.isHidden = false
        countryTitle.stringValue = name
        best.isHidden = false
        let target = state.catalog?.bestDestination(in: code)
        best.isEnabled = state.canConnect && target != nil && target != state.activeDestination
        best.toolTip = target.map { "Select \($0.server) by reported server load" }
        best.handler = { [weak state] in if let target { state?.connect(target) } }
        search.placeholderAttributedString = placeholderText("Find a city or server in \(name)")
        section.stringValue = "SORTED BY LOAD"
    }

    private func countLabel() -> String {
        if input?.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != true {
            return rows.count == 1 ? "1 RESULT" : "\(rows.count) RESULTS"
        }
        let label = page == .locations ? "LOCATION" : "SERVER"
        return "\(rows.count) \(label)\(rows.count == 1 ? "" : "S")"
    }

    private func renderPlaceholder(searching: Bool) {
        let empty = rows.isEmpty
        placeholder.isHidden = !empty
        scroll.isHidden = empty
        let loading = empty && state.catalog == nil && state.catalogPhase.isLoading && page != .saved
        spinner.setRunning(isPresented && loading)
        spinner.isHidden = !loading
        guard empty else { return }
        let message = emptyMessage(loading: loading, searching: searching)
        blankTitle.stringValue = message.title
        blankDetail.stringValue = message.detail
        blankAction.isHidden = !message.canRefresh
    }

    private func emptyMessage(loading: Bool, searching: Bool) -> (title: String, detail: String, canRefresh: Bool) {
        if loading { return ("Loading servers…", "You can browse as soon as the free directory is ready.", false) }
        if page == .saved, !searching { return ("No saved servers", "Select the star next to a server to keep it here.", false) }
        if case .unavailable(let reason) = state.catalogPhase { return ("Server list unavailable", reason, true) }
        if searching { return ("No matches", "Try a different country, city, or server name.", false) }
        if state.catalog == nil { return ("Server directory", "Refresh to download available free servers.", true) }
        return ("No online servers", "Refresh to check for newly available routes.", true)
    }

    private func renderVisibleRows() {
        table.enumerateAvailableRowViews { _, index in
            guard rows.indices.contains(index), let cell = table.view(atColumn: 0, row: index, makeIfNecessary: false) as? DirectoryCell else { return }
            cell.render(rows[index], state: state)
        }
    }

    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }

    func tableView(_ tableView: NSTableView, rowViewForRow row: Int) -> NSTableRowView? { DirectoryLine() }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let view = (tableView.makeView(withIdentifier: DirectoryCell.reuse, owner: self) as? DirectoryCell) ?? DirectoryCell()
        view.render(rows[row], state: state)
        return view
    }

    func controlTextDidChange(_ notification: Notification) { searchChanged() }
    @objc private func searchChanged() { render(presented: isPresented) }

    @objc private func rowClicked() {
        let index = table.clickedRow
        guard rows.indices.contains(index), case .country = rows[index] else { return }
        activate(index)
    }

    private func activate(_ index: Int) {
        guard rows.indices.contains(index) else { return }
        switch rows[index] {
        case .country(let code, _, _): navigate(.country(code))
        case .server(let target, _, _): state.connect(target)
        }
    }
}

@MainActor
private final class DirectoryTable: NSTableView {
    var activateRow: ((Int) -> Void)?

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 || event.keyCode == 76 {
            activateRow?(selectedRow)
            return
        }
        super.keyDown(with: event)
    }
}

private struct RowControls: Equatable {
    let active: Destination?
    let canConnect: Bool
    let operation: TunnelOperation?
}
