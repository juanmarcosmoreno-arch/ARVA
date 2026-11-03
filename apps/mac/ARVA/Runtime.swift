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

    /// The app's stand-ins for git and open, first on the launcher's PATH (LauncherShims).
    static var shimDir: URL { supportDir.appendingPathComponent("bin", isDirectory: true) }

    /// What the launcher printed the last time it started or stopped ARVA (what "Copy details" copies).
    static var logsDir: URL { supportDir.appendingPathComponent("logs", isDirectory: true) }

    /// An ARVA installed before from its code folder (docs/guia-mac.md): its .env, if any, is used too.
    static var legacyInstall: URL { home.appendingPathComponent("ARVA", isDirectory: true) }

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

/// Small stand-ins the app puts first on the launcher's PATH (in ~/Library/Application Support/ARVA/bin, never
/// anywhere else), so that a Mac with only Docker Desktop installed gets no surprise:
/// - git: scripts/start.sh asks git which commit it runs from. The app's copy of the launcher is no git checkout,
///   and on a Mac without the Command Line Tools /usr/bin/git only opens a window offering to install them, at
///   every start. The stand-in answers with the commit the app was built from (ARVA_APP_COMMIT) and otherwise
///   passes on to the real git only when the Command Line Tools are installed.
/// - open: after the first-run questions scripts/start.sh opens http://localhost:8080 in the browser; the app shows
///   ARVA in its own window, so that one address is not opened again (anything else goes to /usr/bin/open).
enum LauncherShims {
    static let git = """
    #!/bin/sh
    # Written by ARVA.app (first on the PATH of the ARVA launcher it runs, nowhere else). The launcher asks git for the
    # commit it runs from: this answers with the commit ARVA.app was built from, so that a Mac without the Command Line
    # Tools never shows their install window. Anything else goes to git only when those tools are installed.
    case " $* " in
      *" rev-parse "*)
        case "${ARVA_APP_COMMIT:-}" in '' | *[!0-9a-f]*) exit 1 ;; esac
        printf '%s\\n' "$ARVA_APP_COMMIT"
        exit 0
        ;;
    esac
    if /usr/bin/xcode-select -p >/dev/null 2>&1; then exec /usr/bin/git "$@"; fi
    exit 1

    """

    static let open = """
    #!/bin/sh
    # Written by ARVA.app (first on the PATH of the ARVA launcher it runs, nowhere else). ARVA.app shows ARVA in its
    # own window, so the launcher does not also open http://localhost:8080 in the browser; anything else is opened.
    if [ "$#" = 1 ]; then
      case "$1" in http://localhost:8080 | http://localhost:8080/*) exit 0 ;; esac
    fi
    exec /usr/bin/open "$@"

    """

    static func install(in dir: URL = AppPaths.shimDir) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        for (name, text) in [("git", git), ("open", open)] {
            let target = dir.appendingPathComponent(name)
            let data = Data(text.utf8)
            if (try? Data(contentsOf: target)) != data { try data.write(to: target, options: .atomic) }
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: target.path)
        }
    }
}

/// Docker Compose reads .env from its project directory, which for the app is the runtime folder. Someone who had
/// ARVA in ~/ARVA may have set variables there (docs/installation.md: ARVA_DB_PASSWORD, for example), and the same
/// Compose project with the same database volume needs the same values, so the runtime folder gets a link to that
/// file when it has no .env of its own. A .env the person put in the runtime folder is never touched.
enum EnvLink {
    static let name = ".env"

    /// Returns a line for Details when something changed, nil otherwise.
    static func ensure(runtime: URL = AppPaths.runtimeDir, legacy: URL = AppPaths.legacyInstall) -> String? {
        let fm = FileManager.default
        let link = runtime.appendingPathComponent(name)
        let source = legacy.appendingPathComponent(name)
        let attributes = try? fm.attributesOfItem(atPath: link.path)
        let isLink = (attributes?[.type] as? FileAttributeType) == .typeSymbolicLink
        if isLink {
            // A link the app made earlier: kept while it leads somewhere, removed when that file is gone.
            if fm.fileExists(atPath: link.path) { return nil }
            try? fm.removeItem(at: link)
            return L("The link to \(source.path) was removed (that file is gone).\n",
                     "Se quitó el enlace a \(source.path) (ese archivo ya no existe).\n")
        }
        if fm.fileExists(atPath: link.path) || !fm.fileExists(atPath: source.path) { return nil }
        do {
            try fm.createSymbolicLink(at: link, withDestinationURL: source)
        } catch {
            return L("Could not use \(source.path): \(error.localizedDescription)\n",
                     "No se pudo usar \(source.path): \(error.localizedDescription)\n")
        }
        return L("Using the settings in \(source.path) (the same as when ARVA was started from there).\n",
                 "Se usan los ajustes de \(source.path) (los mismos que cuando ARVA se iniciaba desde allí).\n")
    }
}

/// A shell word: the text in single quotes.
func shellQuote(_ text: String) -> String {
    "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

/// The first-run wizard (scripts/start.sh --setup) asks its questions in a terminal, so for a new person (and for
/// ARVA → Set Up Again) the app writes this small .command file next to the synced launcher and opens it in
/// Terminal. It records its process id in .first-run-pid (so the app knows when the window was closed, and can stop
/// it on Cancel), what the window shows in .first-run.log (through script(1), which keeps it a terminal: the
/// "Copy details" text), and how it ended in .first-run-status: the exit status, "declined" when the person chose
/// not to save the answers (start.sh then exits 0 without starting ARVA), or "interrupted" (Ctrl-C, the window
/// closed, or Cancel in the app).
enum FirstRunCommand {
    static let statusFile = ".first-run-status"
    static let pidFile = ".first-run-pid"
    static let logFile = ".first-run.log"
    static let innerStatusFile = ".first-run-inner"

    static var fileName: String { L("Set up ARVA.command", "Configurar ARVA.command") }
    static let fileNames = ["Set up ARVA.command", "Configurar ARVA.command"]

    enum Status: Equatable {
        case succeeded
        case failed(Int32)
        case declined
        case interrupted
    }

    static func contents(locale: String = Lang.posixLocale, config: URL = AppPaths.configFile(),
                         shims: URL = AppPaths.shimDir, commit: String = AppInfo.commit) -> String {
        let done = L("ARVA is ready: it opens in the ARVA app. This window can be closed.",
                     "ARVA está listo: se abre en la aplicación ARVA. Esta ventana se puede cerrar.")
        let failed = L("ARVA did not start. What happened is above, in this window; the ARVA app has the same text (Copy details) to send to whoever helps you.",
                       "ARVA no se inició. Lo que pasó está arriba, en esta ventana; la aplicación ARVA tiene el mismo texto (Copiar detalles) para enviarlo a quien te ayuda.")
        let declined = L("Nothing was saved and ARVA did not start. The ARVA app can show the questions again.",
                         "No se guardó nada y ARVA no se inició. La aplicación ARVA puede mostrar de nuevo las preguntas.")
        let enter = L("Press Enter to close this window. ", "Presionar Enter para cerrar esta ventana. ")
        let safeCommit = commit.allSatisfy { $0.isHexDigit } && !commit.isEmpty ? commit : "unknown"
        return """
        #!/bin/sh
        # Written by ARVA.app for the first-run questions (scripts/start.sh --setup) in Terminal; ARVA then starts and
        # the app opens it. Replaced the next time; safe to delete.
        cd "$(dirname "$0")" || exit 1
        PATH=\(shellQuote(shims.path)):$PATH:/usr/local/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:/opt/homebrew/bin
        COMPOSE_PROJECT_NAME=arva
        LANG=\(locale)
        ARVA_APP_COMMIT=\(safeCommit)
        export PATH COMPOSE_PROJECT_NAME LANG ARVA_APP_COMMIT
        unset LC_ALL LC_MESSAGES
        config=\(shellQuote(config.path))
        rm -f \(statusFile) \(innerStatusFile) \(logFile)
        printf '%s\\n' "$$" > \(pidFile)
        trap 'printf "%s\\n" interrupted > \(statusFile); exit 130' INT HUP TERM
        if [ -x /usr/bin/script ]; then
          /usr/bin/script -q \(logFile) /bin/sh -c 'sh scripts/start.sh --setup; printf "%s\\n" "$?" > \(innerStatusFile)'
          status=$(cat \(innerStatusFile) 2>/dev/null) || status=interrupted
          [ -n "$status" ] || status=interrupted
        else
          sh scripts/start.sh --setup
          status=$?
        fi
        # start.sh also exits 0 when the person chose not to save the answers: then nothing was saved or started
        # (a start always ends by printing ARVA's address).
        if [ "$status" = 0 ]; then
          if [ ! -f "$config" ]; then
            status=declined
          elif [ -f \(logFile) ] && ! grep -q 'http://localhost:8080' \(logFile); then
            status=declined
          fi
        fi
        trap - INT HUP TERM
        printf '%s\\n' "$status" > \(statusFile)
        printf '\\n'
        case "$status" in
          0) printf '%s\\n' \(shellQuote(done)) ;;
          declined) printf '%s\\n' \(shellQuote(declined)) ;;
          *) printf '%s\\n' \(shellQuote(failed)) ;;
        esac
        printf '%s' \(shellQuote(enter))
        read -r _ || true
        [ "$status" = 0 ] || [ "$status" = declined ]

        """
    }

    static func write(in runtime: URL) throws -> URL {
        let url = runtime.appendingPathComponent(fileName)
        for name in [statusFile, pidFile, logFile, innerStatusFile] {
            try? FileManager.default.removeItem(at: runtime.appendingPathComponent(name))
        }
        try contents().write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return url
    }

    /// How the wizard ended, or nil while it runs.
    static func status(in runtime: URL) -> Status? {
        guard let text = try? String(contentsOf: runtime.appendingPathComponent(statusFile), encoding: .utf8)
        else { return nil }
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        switch value {
        case "": return nil
        case "0": return .succeeded
        case "declined": return .declined
        case "interrupted": return .interrupted
        default: return .failed(Int32(value) ?? 1)
        }
    }

    /// The wizard's process id, once it has started.
    static func pid(in runtime: URL) -> pid_t? {
        guard let text = try? String(contentsOf: runtime.appendingPathComponent(pidFile), encoding: .utf8),
              let pid = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1 else { return nil }
        return pid
    }

    /// Whether the wizard's process is still there: nil before it has started, false once its window was closed.
    /// The process id is only trusted while it still runs this command file (ps), never another process.
    static func isRunning(in runtime: URL) -> Bool? {
        guard let pid = pid(in: runtime) else { return nil }
        guard ProcessTree.isAlive(pid),
              let result = ShellTask.run("/bin/ps", ["-p", String(pid), "-o", "command="],
                                         environment: ["PATH": "/usr/bin:/bin"], timeout: 10),
              result.status == 0 else { return false }
        return fileNames.contains { result.output.contains($0) }
    }

    /// Stops the wizard and everything it started (Cancel, or quitting with Stop). Never on the main thread.
    static func stop(in runtime: URL) {
        guard isRunning(in: runtime) == true, let pid = pid(in: runtime) else { return }
        ProcessTree.terminate(root: pid)
    }
}

/// Follows a growing text file (the first-run log): each call returns what was added since the last one.
final class LogTail {
    private let url: URL
    private var offset: UInt64 = 0

    init(url: URL) { self.url = url }

    func read() -> String {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return "" }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        if size < offset { offset = 0 }
        guard size > offset else { return "" }
        try? handle.seek(toOffset: offset)
        guard let data = try? handle.readToEnd() else { return "" }
        // Only whole lines (the rest is read next time), unless a line is unusually long.
        var usable = data
        if let newline = data.lastIndex(of: 0x0A) {
            usable = data.subdata(in: data.startIndex..<data.index(after: newline))
        } else if data.count < 4096 {
            return ""
        }
        offset += UInt64(usable.count)
        return cleanOutput(String(decoding: usable, as: UTF8.self))
    }
}

/// The folder ARVA imports sequencing runs from (/import in its containers), for File → Open the Import Folder.
enum ImportFolder {
    enum Answer {
        case folder(URL)
        /// The chosen import folder is not reachable now (its disk is not connected, most likely).
        case unavailable(String)
    }

    /// What the running ARVA mounts at /import when it can be asked (never on the main thread); otherwise the folder
    /// chosen in the first-run questions; otherwise the import/ folder next to the app's launcher.
    static func current() -> Answer {
        let fm = FileManager.default
        if let mounted = mountedSource(), fm.fileExists(atPath: mounted) {
            return .folder(URL(fileURLWithPath: mounted, isDirectory: true))
        }
        if let chosen = ArvaConfig.load(from: AppPaths.configFile())?.importDir {
            return fm.fileExists(atPath: chosen) ? .folder(URL(fileURLWithPath: chosen, isDirectory: true)) : .unavailable(chosen)
        }
        let folder = AppPaths.runtimeDir.appendingPathComponent("import", isDirectory: true)
        try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
        return .folder(folder)
    }

    /// The host folder mounted at /import in ARVA's api container, when it runs.
    static func mountedSource() -> String? {
        guard let docker = DockerDesktop.cli,
              let ids = ShellTask.run(docker, ["ps", "-q", "--filter", "label=com.docker.compose.project=arva",
                                               "--filter", "label=com.docker.compose.service=api"], timeout: 10),
              ids.status == 0,
              let id = ids.output.split(separator: "\n").first.map(String.init), !id.isEmpty,
              let mounts = ShellTask.run(docker, ["inspect", "--format",
                                                  "{{range .Mounts}}{{if eq .Destination \"/import\"}}{{.Source}}{{end}}{{end}}", id],
                                         timeout: 10),
              mounts.status == 0 else { return nil }
        var source = mounts.output.trimmingCharacters(in: .whitespacesAndNewlines)
        // Older Docker Desktop versions name host folders under /host_mnt.
        if source.hasPrefix("/host_mnt/") { source.removeFirst("/host_mnt".count) }
        return source.hasPrefix("/") ? source : nil
    }
}
