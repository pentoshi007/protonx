import Foundation

protocol EngineAccess: Sendable {
    func status() throws -> Status
    func catalog(offline: Bool) throws -> Catalog
    func account() throws -> Account
    func connect(_ target: Destination) throws
    func disconnect() throws
    func signIn(username: String, password: String) throws -> SignInResult
    func submitTwoFactor(_ code: String) throws -> SignInResult
    func signOut() throws
    func updateCheck() throws -> UpdateStatus
    func repair() throws -> RepairReport
}

private struct DisconnectReport: Decodable {
    let up: Bool
}

private struct HelperReport: Decodable {
    let ok: Bool
    let up: Bool
    let interface: String?
    let address: String?
    let peers: [HelperPeer]
    let server: LastServer?
    let dns: DNSReport?
}

private struct HelperPeer: Decodable {
    let latestHandshake: Int
    let rxBytes: Int64
    let txBytes: Int64
}

struct EngineError: LocalizedError, Decodable, Equatable, Sendable {
    let error: String
    let kind: String?

    init(_ message: String, kind: String = "failed") {
        self.error = message
        self.kind = kind
    }

    var errorDescription: String? { error }
    var needsSignIn: Bool { kind == "session" }
}

struct Engine: EngineAccess {
    let executable: URL
    let usesNativeStatus: Bool

    init(executable: URL = URL(fileURLWithPath: "/usr/local/libexec/protonx-app/app-engine"), usesNativeStatus: Bool = true) {
        self.executable = executable
        self.usesNativeStatus = usesNativeStatus
    }

    func status() throws -> Status {
        if usesNativeStatus, let native = try? nativeStatus() { return native }
        return try decode(Status.self, ["status", "--json"], timeout: 10)
    }

    private func nativeStatus() throws -> Status {
        let report = try HelperSocket.call(#"{"command":"status"}"#)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = try decoder.decode(HelperReport.self, from: report)
        guard decoded.ok else { throw EngineError("The ProtonX helper rejected the status request.") }
        let peer = decoded.peers.first.map {
            Peer(latestHandshake: $0.latestHandshake, rxBytes: $0.rxBytes, txBytes: $0.txBytes)
        }
        return Status(up: decoded.up, interface: decoded.interface, address: decoded.address,
                      peer: peer, server: decoded.server ?? HelperSocket.lastServer(), dns: decoded.dns)
    }

    func catalog(offline: Bool) throws -> Catalog {
        let arguments = ["catalog", "--json"] + (offline ? ["--offline"] : [])
        return try decode(Catalog.self, arguments, timeout: offline ? 8 : 95)
    }

    func account() throws -> Account {
        try decode(Account.self, ["whoami", "--local", "--json"], timeout: 10)
    }

    func connect(_ target: Destination) throws {
        _ = try run(["connect", "--offline", "--country", target.country, "--server", target.server, "--json"], timeout: 78)
    }

    func disconnect() throws {
        let report = try decode(DisconnectReport.self, ["disconnect", "--json"], timeout: 50)
        if report.up { throw EngineError("The tunnel is still active. Try disconnecting again.") }
    }

    func signOut() throws {
        _ = try run(["logout", "--json"], timeout: 20)
    }

    func updateCheck() throws -> UpdateStatus {
        try decode(UpdateStatus.self, ["update", "--check", "--json"], timeout: 30)
    }

    func repair() throws -> RepairReport {
        try decode(RepairReport.self, ["repair", "--json"], timeout: 60)
    }

    func signIn(username: String, password: String) throws -> SignInResult {
        try decode(SignInResult.self, ["login", "--username", username, "--password-stdin", "--json"], input: password)
    }

    func submitTwoFactor(_ code: String) throws -> SignInResult {
        try decode(SignInResult.self, ["login", "--two-factor-stdin", "--json"], input: code)
    }

    private func decode<Value: Decodable>(
        _ type: Value.Type, _ arguments: [String], input: String? = nil, timeout: TimeInterval = 125
    ) throws -> Value {
        let data = try run(arguments, input: input, timeout: timeout)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw EngineError("The engine returned an unreadable response. Reinstall ProtonX if this persists.")
        }
    }

    private func run(_ arguments: [String], input: String? = nil, timeout: TimeInterval) throws -> Data {
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw EngineError("The ProtonX engine is missing. Run install.sh to install it.")
        }
        let process = Process()
        let output = Pipe()
        let stdin = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = output
        process.standardError = output
        process.standardInput = stdin
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        try process.run()
        let deadline = DispatchWorkItem { [weak process] in
            if let process, process.isRunning { process.terminate() }
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: deadline)
        defer { deadline.cancel() }
        if let input {
            try? stdin.fileHandleForWriting.write(contentsOf: Data((input + "\n").utf8))
        }
        try? stdin.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        if process.terminationReason == .uncaughtSignal && process.terminationStatus == SIGTERM {
            throw EngineError("The engine took too long to respond. Try again.")
        }
        guard process.terminationStatus == 0 else { throw failure(from: data) }
        return data
    }

    private func failure(from data: Data) -> EngineError {
        if let report = try? JSONDecoder().decode(EngineError.self, from: data) { return report }
        let message = String(decoding: data, as: UTF8.self).split(whereSeparator: \.isNewline).last
        return EngineError(message.map { String($0.prefix(360)) } ?? "The ProtonX engine did not respond.")
    }
}

enum HelperSocket {
    static let path = "/var/run/protonx/helper.sock"
    private static let lastServerPath = NSHomeDirectory() + "/.config/protonx/last.json"

    static func call(_ request: String, timeout: TimeInterval = 3) throws -> Data {
        let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw EngineError("The ProtonX helper is unavailable.") }
        defer { close(descriptor) }
        var limit = timeval(tv_sec: Int(timeout), tv_usec: 0)
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &limit, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &limit, socklen_t(MemoryLayout<timeval>.size))
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let capacity = MemoryLayout.size(ofValue: address.sun_path)
        guard path.utf8.count < capacity else { throw EngineError("The helper socket path is too long.") }
        withUnsafeMutablePointer(to: &address.sun_path) { field in
            field.withMemoryRebound(to: CChar.self, capacity: capacity) { destination in
                _ = path.withCString { strcpy(destination, $0) }
            }
        }
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else { throw EngineError("The ProtonX helper is not reachable.") }
        try send(Data((request + "\n").utf8), to: descriptor)
        return try receive(from: descriptor)
    }

    static func lastServer() -> LastServer? {
        guard let data = FileManager.default.contents(atPath: lastServerPath) else { return nil }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try? decoder.decode(LastServer.self, from: data)
    }

    private static func send(_ payload: Data, to descriptor: Int32) throws {
        var sent = 0
        while sent < payload.count {
            let written = payload.withUnsafeBytes { buffer in
                write(descriptor, buffer.baseAddress!.advanced(by: sent), payload.count - sent)
            }
            guard written > 0 else { throw EngineError("The ProtonX helper closed the connection.") }
            sent += written
        }
    }

    private static func receive(from descriptor: Int32) throws -> Data {
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while !data.contains(0x0A) {
            let count = read(descriptor, &buffer, buffer.count)
            guard count > 0 else { break }
            data.append(buffer, count: count)
        }
        guard !data.isEmpty else { throw EngineError("The ProtonX helper sent no reply.") }
        return data
    }
}
