import AppKit

/// Opt-in tracing for the popover and account panel. Writes only when
/// PROTONX_MENU_DIAG names a log path, so a normal launch does no I/O.
enum MenuDiag {
    private static let logPath = ProcessInfo.processInfo.environment["PROTONX_MENU_DIAG"]
    static var enabled: Bool { logPath != nil }

    static func log(_ message: String) {
        guard let path = logPath else { return }
        let stamp = String(format: "%.3f", Date().timeIntervalSince1970)
        guard let data = "[\(stamp)] \(message)\n".data(using: .utf8) else { return }
        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            handle.closeFile()
        } else {
            FileManager.default.createFile(atPath: path, contents: data)
        }
    }
}
