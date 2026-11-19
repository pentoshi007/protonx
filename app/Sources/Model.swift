import Foundation

struct Catalog: Decodable, Equatable, Sendable {
    static let lifetime: TimeInterval = 600

    let fetchedAt: TimeInterval
    let countries: [Country]

    var isFresh: Bool {
        let age = Date().timeIntervalSince1970 - fetchedAt
        return age >= 0 && age < Self.lifetime
    }

    func country(_ code: String) -> Country? {
        countries.first { $0.code == code }
    }

    func bestDestination(in code: String?) -> Destination? {
        if let code, let server = country(code)?.servers.first {
            return Destination(country: code, server: server.name)
        }
        guard code == nil else { return nil }
        let country = countries.filter { !$0.servers.isEmpty }.min {
            ($0.servers[0].load, $0.code) < ($1.servers[0].load, $1.code)
        }
        guard let country, let server = country.servers.first else { return nil }
        return Destination(country: country.code, server: server.name)
    }
}

struct Country: Decodable, Equatable, Sendable {
    let code: String
    let name: String
    let servers: [Server]
}

struct Server: Decodable, Equatable, Sendable {
    let name: String
    let city: String
    let load: Int
}

struct Destination: Codable, Hashable, Sendable {
    let country: String
    let server: String
}

struct Peer: Decodable, Equatable, Sendable {
    let latestHandshake: Int
    let rxBytes: Int64
    let txBytes: Int64
}

struct LastServer: Decodable, Equatable, Sendable {
    let country: String
    let server: String
    let label: String
    let city: String
    let connectedAt: TimeInterval?

    var destination: Destination { Destination(country: country, server: server) }
}

struct Status: Decodable, Equatable, Sendable {
    let up: Bool
    let interface: String?
    let address: String?
    let peer: Peer?
    let server: LastServer?
}

struct Account: Decodable, Equatable, Sendable {
    let signedIn: Bool
    let username: String?
    let pending: Bool
}

struct SignInResult: Decodable, Sendable {
    let status: String
    let username: String?
}

struct UpdateStatus: Decodable, Equatable, Sendable {
    let current: String
    let latest: String
    let update: Bool
}

enum SessionPhase: Equatable {
    case checking
    case ready(Account)
    case unavailable(String)

    var signedIn: Bool {
        guard case .ready(let account) = self else { return false }
        return account.signedIn
    }
}

enum CatalogPhase: Equatable {
    case idle
    case readingCache
    case refreshing
    case current
    case saved(String?)
    case unavailable(String)

    var isLoading: Bool { self == .readingCache || self == .refreshing }
}

enum TunnelOperation: Equatable, Sendable {
    case connecting(Destination)
    case switching(Destination)
    case disconnecting
    case signingOut

    var destination: Destination? {
        switch self {
        case .connecting(let target), .switching(let target): return target
        case .disconnecting, .signingOut: return nil
        }
    }
}
