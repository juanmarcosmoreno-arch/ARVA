import Foundation

/// The saved locations in arva.conf, read the way scripts/lib/arva-locations.sh reads them (KEY=VALUE lines, never
/// run): the app only uses them to tell, in plain words, which disk to connect when ARVA cannot start.
/// scripts/start.sh stays the authority: it checks every folder again at each start.
struct ArvaConfig: Equatable {
    var dataDir: String?
    var dataMount: String?
    var databasesDir: String?
    var databasesMount: String?
    var importDir: String?
    var platform: String?
    var extraDatabases: [String] = []
    /// Line numbers that are not KEY=VALUE or have an unknown key (the launcher ignores them with a warning).
    var ignoredLines: [Int] = []

    static func parse(_ text: String) -> ArvaConfig {
        var cfg = ArvaConfig()
        for (index, raw) in text.components(separatedBy: "\n").enumerated() {
            var line = raw
            if line.unicodeScalars.last == "\r" { line.removeLast() }
            if line.isEmpty || line.hasPrefix("#") { continue }
            guard let eq = line.firstIndex(of: "=") else {
                cfg.ignoredLines.append(index + 1)
                continue
            }
            let key = String(line[..<eq])
            let value = String(line[line.index(after: eq)...])
            switch key {
            case "ARVA_DATA_DIR": cfg.dataDir = value
            case "ARVA_DATA_DIR_MOUNT": cfg.dataMount = value
            case "ARVA_DATABASES_DIR": cfg.databasesDir = value
            case "ARVA_DATABASES_DIR_MOUNT": cfg.databasesMount = value
            case "ARVA_IMPORT_DIR": cfg.importDir = value
            case "ARVA_PLATFORM":
                if value == "linux/amd64" || value == "linux/arm64" { cfg.platform = value } else { cfg.ignoredLines.append(index + 1) }
            case "ARVA_ADD_DATABASES":
                if !value.isEmpty && !cfg.extraDatabases.contains(value) { cfg.extraDatabases.append(value) }
            default:
                cfg.ignoredLines.append(index + 1)
            }
        }
        // An empty value is no location (the launcher treats it the same way).
        if cfg.dataDir == "" { cfg.dataDir = nil }
        if cfg.databasesDir == "" { cfg.databasesDir = nil }
        if cfg.importDir == "" { cfg.importDir = nil }
        return cfg
    }

    static func load(from url: URL) -> ArvaConfig? {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        return parse(text)
    }

    /// The external disk (/Volumes/<name>) a folder is on: the saved mount point when it is one, else the path's own.
    static func volume(of path: String?, savedMount: String?) -> String? {
        for candidate in [savedMount, path] {
            guard let candidate, candidate.hasPrefix("/Volumes/") else { continue }
            let parts = candidate.split(separator: "/", omittingEmptySubsequences: true)
            if parts.count >= 2 { return "/Volumes/" + parts[1] }
        }
        return nil
    }

    /// The names of the disks that hold the data or database folder and are not connected now: without them ARVA does
    /// not start (scripts/start.sh refuses, so nothing is written to the internal disk instead).
    func missingDisks(exists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> [String] {
        var names: [String] = []
        for volume in [ArvaConfig.volume(of: dataDir, savedMount: dataMount),
                       ArvaConfig.volume(of: databasesDir, savedMount: databasesMount)] {
            guard let volume, !exists(volume) else { continue }
            let name = (volume as NSString).lastPathComponent
            if !names.contains(name) { names.append(name) }
        }
        return names
    }
}
