import Foundation

enum DirectoryPage: Equatable {
    case locations
    case saved
    case country(String)
}

enum DirectoryRow: Equatable {
    case country(code: String, name: String, count: Int)
    case server(Destination, location: String, data: Server?)
}

struct DirectoryInput: Equatable {
    let page: DirectoryPage
    let catalog: Catalog?
    let saved: Set<Destination>
    let query: String

    var rows: [DirectoryRow] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        switch page {
        case .locations:
            return (catalog?.countries ?? []).flatMap { locationRows($0, matching: needle) }
        case .country(let code):
            guard let country = catalog?.country(code) else { return [] }
            return country.servers.filter { matches($0, needle) }.map { row(for: $0, in: country) }
        case .saved:
            return saved.sorted { ($0.country, $0.server) < ($1.country, $1.server) }.compactMap { savedRow($0, matching: needle) }
        }
    }

    private func locationRows(_ country: Country, matching needle: String) -> [DirectoryRow] {
        if needle.isEmpty || country.code.caseInsensitiveCompare(needle) == .orderedSame || country.name.localizedStandardContains(needle) {
            return [.country(code: country.code, name: country.name, count: country.servers.count)]
        }
        return country.servers.filter { matches($0, needle) }.map { row(for: $0, in: country) }
    }

    private func matches(_ server: Server, _ needle: String) -> Bool {
        needle.isEmpty || server.name.localizedStandardContains(needle) || server.city.localizedStandardContains(needle)
    }

    private func row(for server: Server, in country: Country) -> DirectoryRow {
        .server(Destination(country: country.code, server: server.name), location: country.name, data: server)
    }

    private func savedRow(_ target: Destination, matching needle: String) -> DirectoryRow? {
        let country = catalog?.country(target.country)
        let server = country?.servers.first { $0.name == target.server }
        let name = country?.name ?? Locale.current.localizedString(forRegionCode: target.country) ?? target.country
        let terms = [target.server, target.country, name, server?.city ?? ""]
        guard needle.isEmpty || terms.contains(where: { $0.localizedStandardContains(needle) }) else { return nil }
        return .server(target, location: name, data: server)
    }
}
