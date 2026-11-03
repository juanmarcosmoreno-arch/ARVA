import Foundation

/// Where things live. The launcher files travel inside the app (Contents/Resources/runtime, copied there by
/// scripts/build-mac-app.sh) and run from a copy in ~/Library/Application Support/ARVA/runtime, which is also Docker
/// Compose's project directory: its import/ folder and the generated files stay outside the app bundle, so the app
/// can be replaced (a new version, or moved) without touching them.
enum AppPaths {
    static var home: URL { FileManager.default.homeDirectoryForCurrentUser }

    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? home.appendingPathComponent("Library/Application Support", isDirectory: true)
        return base.appendingPathComponent("ARVA", isDirectory: true)
    }

    static var runtimeDir: URL { supportDir.appendingPathComponent("runtime", isDirectory: true) }

    static var bundledRuntime: URL? {
        Bundle.main.resourceURL?.appendingPathComponent("runtime", isDirectory: true)
    }

    /// The same file scripts/lib/arva-locations.sh reads: ${XDG_CONFIG_HOME:-$HOME/.config}/arva/arva.conf.
    static func configFile(environment: [String: String] = ProcessInfo.processInfo.environment) -> URL {
        if let xdg = environment["XDG_CONFIG_HOME"], xdg.hasPrefix("/") {
            return URL(fileURLWithPath: xdg, isDirectory: true).appendingPathComponent("arva/arva.conf")
        }
        return home.appendingPathComponent(".config/arva/arva.conf")
    }

    static var downloads: URL {
        FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? home.appendingPathComponent("Downloads", isDirectory: true)
    }
}

enum RuntimeError: LocalizedError {
    case missingBundle(String)
    case copyFailed(String, String)

    var errorDescription: String? {
        switch self {
        case .missingBundle(let what):
            return L("The app is incomplete (\(what) is missing). Download ARVA.app again.",
                     "La aplicación está incompleta (falta \(what)). Vuelve a descargar ARVA.app.")
        case .copyFailed(let path, let reason):
            return L("Could not prepare \(path): \(reason)", "No se pudo preparar \(path): \(reason)")
        }
    }
}

/// Copies the bundled launcher files into the runtime folder, only when the bundled version (the build's
/// .arva-runtime-id, a checksum of every file) differs from the one installed there or a file is missing.
/// Only files the app itself installed are ever replaced or removed (.arva-runtime-files lists them); anything else
/// in that folder, such as sequencing runs in import/, is never touched.
enum RuntimeSync {
    static let idFile = ".arva-runtime-id"
    static let manifestFile = ".arva-runtime-files"

    /// What the launcher needs; the self-test checks that every one is in the bundle.
    static let requiredFiles = [
        "docker-compose.yml",
        "scripts/start.sh",
        "scripts/stop.sh",
        "scripts/metadata-backup.sh",
        "scripts/lib/arva-locations.sh",
        "scripts/lib/arva-firstrun.sh",
        "import/README.md",
        "apps/api/app/__init__.py",
        "ARVA.command",
        "Detener ARVA.command",
    ]

    static func bundledID(_ src: URL) throws -> String {
        guard let id = try? String(contentsOf: src.appendingPathComponent(idFile), encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines), !id.isEmpty else {
            throw RuntimeError.missingBundle(idFile)
        }
        return id
    }

    /// The regular files under `src`, as relative paths, without the two bookkeeping files.
    static func bundledFiles(_ src: URL) -> [String] {
        guard let walker = FileManager.default.enumerator(atPath: src.path) else { return [] }
        var files: [String] = []
        while let rel = walker.nextObject() as? String {
            let type = walker.fileAttributes?[.type] as? FileAttributeType
            if type == .typeRegular && rel != idFile && rel != manifestFile { files.append(rel) }
        }
        return files.sorted()
    }

    static func isSafeRelative(_ rel: String) -> Bool {
        !rel.isEmpty && !rel.hasPrefix("/") && !rel.split(separator: "/").contains("..")
    }

    static func mode(for rel: String) -> Int {
        (rel.hasSuffix(".sh") || rel.hasSuffix(".command")) ? 0o755 : 0o644
    }

    /// Returns true when files were copied.
    @discardableResult
    static func sync(from src: URL, to dst: URL) throws -> Bool {
        let fm = FileManager.default
        let id = try bundledID(src)
        let files = bundledFiles(src)
        for required in requiredFiles where !files.contains(required) {
            throw RuntimeError.missingBundle(required)
        }
        let installedID = (try? String(contentsOf: dst.appendingPathComponent(idFile), encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if installedID == id && files.allSatisfy({ fm.fileExists(atPath: dst.appendingPathComponent($0).path) }) {
            return false
        }
        do {
            try fm.createDirectory(at: dst, withIntermediateDirectories: true)
            let manifest = dst.appendingPathComponent(manifestFile)
            let previous = ((try? String(contentsOf: manifest, encoding: .utf8)) ?? "")
                .components(separatedBy: "\n").filter(isSafeRelative)
            let current = Set(files)
            for rel in previous where !current.contains(rel) {
                try? fm.removeItem(at: dst.appendingPathComponent(rel))
            }
            for rel in files {
                let target = dst.appendingPathComponent(rel)
                try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                let data = try Data(contentsOf: src.appendingPathComponent(rel))
                // Written in place (same file), so a container that has the file bind-mounted keeps seeing it.
                if (try? Data(contentsOf: target)) != data {
                    try data.write(to: target)
                }
                try fm.setAttributes([.posixPermissions: mode(for: rel)], ofItemAtPath: target.path)
            }
            try (files.joined(separator: "\n") + "\n").write(to: manifest, atomically: true, encoding: .utf8)
            try (id + "\n").write(to: dst.appendingPathComponent(idFile), atomically: true, encoding: .utf8)
        } catch {
            throw RuntimeError.copyFailed(dst.path, error.localizedDescription)
        }
        return true
    }

    /// The version in apps/api/app/__init__.py (`__version__ = "x.y.z"`), which scripts/start.sh uses as the image tag.
    static func version(in runtime: URL) -> String? {
        guard let text = try? String(contentsOf: runtime.appendingPathComponent("apps/api/app/__init__.py"),
                                     encoding: .utf8) else { return nil }
        for line in text.components(separatedBy: "\n") where line.hasPrefix("__version__") {
            let parts = line.components(separatedBy: "\"")
            if parts.count >= 3 { return parts[1] }
        }
        return nil
    }
}

/// The first-run wizard (scripts/start.sh --setup) asks its questions in a terminal, so for a new person the app
/// writes this small .command file next to the synced launcher and opens it in Terminal; it records the exit status
/// in .first-run-status for the app, which meanwhile waits for ARVA to answer.
enum FirstRunCommand {
    static let statusFile = ".first-run-status"

    static var fileName: String { L("Set up ARVA.command", "Configurar ARVA.command") }

    static func contents(locale: String = Lang.posixLocale) -> String {
        let done = L("ARVA is ready: it opens in the ARVA app. This window can be closed.",
                     "ARVA está listo: se abre en la aplicación ARVA. Esta ventana se puede cerrar.")
        let failed = L("ARVA did not start. The ARVA app shows what happened (Copy details).",
                       "ARVA no se inició. La aplicación ARVA muestra qué pasó (Copiar detalles).")
        let enter = L("Press Enter to close this window. ", "Presionar Enter para cerrar esta ventana. ")
        return """
        #!/bin/sh
        # Written by ARVA.app at each first run: ARVA's first-run questions (scripts/start.sh --setup) in Terminal,
        # then ARVA starts; the app waits for it and opens it. Replaced the next time; safe to delete.
        cd "$(dirname "$0")" || exit 1
        PATH=$PATH:/usr/local/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:/opt/homebrew/bin
        COMPOSE_PROJECT_NAME=arva
        LANG=\(locale)
        export PATH COMPOSE_PROJECT_NAME LANG
        unset LC_ALL LC_MESSAGES
        rm -f \(statusFile)
        sh scripts/start.sh --setup
        status=$?
        printf '%s\\n' "$status" > \(statusFile)
        printf '\\n'
        if [ "$status" = 0 ]; then
          printf '%s\\n' '\(done)'
        else
          printf '%s\\n' '\(failed)'
        fi
        printf '%s' '\(enter)'
        read -r _ || true
        exit "$status"

        """
    }

    static func write(in runtime: URL) throws -> URL {
        let url = runtime.appendingPathComponent(fileName)
        try? FileManager.default.removeItem(at: runtime.appendingPathComponent(statusFile))
        try contents().write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return url
    }

    /// The wizard's exit status once it has finished, or nil while it runs.
    static func status(in runtime: URL) -> Int32? {
        guard let text = try? String(contentsOf: runtime.appendingPathComponent(statusFile), encoding: .utf8)
        else { return nil }
        return Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}
