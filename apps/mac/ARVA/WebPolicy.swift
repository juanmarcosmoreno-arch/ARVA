import Foundation
import UniformTypeIdentifiers

/// The rules the app's web view follows, kept apart from the view so the self-test can check them.
enum WebPolicy {
    enum Kind: Equatable {
        /// ARVA itself (http://localhost:8080 or http://127.0.0.1:8080): shown in the app.
        case local
        /// about:, blob: and data: (frames ARVA writes itself, exports made in the page): shown or downloaded.
        case inert
        /// Any other web page or a mail link: opened in the default browser or mail app.
        case external
        /// Everything else (file:, custom schemes): never opened.
        case blocked
    }

    static func classify(_ url: URL) -> Kind {
        let scheme = url.scheme?.lowercased() ?? ""
        switch scheme {
        case "http", "https":
            let host = url.host?.lowercased() ?? ""
            let port = url.port ?? (scheme == "https" ? 443 : 80)
            if scheme == "http" && (host == "localhost" || host == "127.0.0.1") && port == 8080 { return .local }
            return host.isEmpty ? .blocked : .external
        case "about", "blob", "data":
            return .inert
        case "mailto":
            return .external
        default:
            return .blocked
        }
    }

    /// The file types an <input type=file accept="..."> allows, for NSOpenPanel; nil allows every file (no accept,
    /// a wildcard, or an entry this Mac cannot map: better to show every file than to hide the right one).
    static func contentTypes(forAccept accept: String) -> [UTType]? {
        var types: [UTType] = []
        for raw in accept.split(separator: ",") {
            let token = raw.trimmingCharacters(in: .whitespaces).lowercased()
            if token.isEmpty { continue }
            if token.hasPrefix(".") {
                // ".fastq.gz" names the .gz type (NSOpenPanel matches the last extension).
                let ext = token.split(separator: ".").last.map(String.init) ?? ""
                guard !ext.isEmpty, let type = UTType(filenameExtension: ext) else { return nil }
                types.append(type)
            } else if token == "*/*" || token == "*" {
                return nil
            } else if token.hasSuffix("/*") {
                switch String(token.dropLast(2)) {
                case "image": types.append(.image)
                case "text": types.append(.text)
                case "audio": types.append(.audio)
                case "video": types.append(.movie)
                default: return nil
                }
            } else if let type = UTType(mimeType: token) {
                types.append(type)
            } else {
                return nil
            }
        }
        return types.isEmpty ? nil : types
    }

    private static let compressed: Set<String> = ["gz", "bz2", "xz", "zst", "zip"]

    /// A file name for a download: only its last path component, without characters Finder or the shell trip on.
    static func safeFileName(_ suggested: String) -> String {
        var name = (suggested as NSString).lastPathComponent
        name = name.replacingOccurrences(of: ":", with: "_").replacingOccurrences(of: "/", with: "_")
        name = String(String.UnicodeScalarView(name.unicodeScalars.filter { $0.value >= 0x20 && $0.value != 0x7F }))
        while name.hasPrefix(".") { name.removeFirst() }
        name = name.trimmingCharacters(in: .whitespaces)
        if name.isEmpty { name = L("download", "descarga") }
        if name.utf8.count > 200 { name = String(name.prefix(150)) }
        return name
    }

    /// The download's destination in `directory`: the suggested name, or "name (2).ext" and so on when it is taken
    /// (a compressed file keeps both extensions: "reads (2).fastq.gz").
    static func uniqueDestination(in directory: URL, suggested: String,
                                  exists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> URL {
        let name = safeFileName(suggested)
        var stem = (name as NSString).deletingPathExtension
        var ext = (name as NSString).pathExtension
        if compressed.contains(ext.lowercased()) {
            let inner = (stem as NSString).pathExtension
            if !inner.isEmpty && inner.count <= 8 {
                ext = inner + "." + ext
                stem = (stem as NSString).deletingPathExtension
            }
        }
        if stem.isEmpty {
            stem = name
            ext = ""
        }
        var candidate = directory.appendingPathComponent(name)
        var n = 2
        while exists(candidate.path) && n < 10_000 {
            let file = ext.isEmpty ? "\(stem) (\(n))" : "\(stem) (\(n)).\(ext)"
            candidate = directory.appendingPathComponent(file)
            n += 1
        }
        return candidate
    }
}
