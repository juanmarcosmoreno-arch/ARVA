import Foundation

/// The environment the launcher scripts and docker run with. An app opened from Finder gets a minimal PATH and no
/// LANG, so Docker Desktop's usual places are added (as ARVA.command does), the language is passed on, and the
/// Compose project is named explicitly: docker-compose.yml already says `name: arva`, and COMPOSE_PROJECT_NAME=arva
/// makes sure no other value from the environment changes it, so an ARVA started before from ~/ARVA (or with
/// ARVA.command) is the same project, with the same volumes. The app's stand-ins for git and open
/// (LauncherShims) come first on the PATH, and ARVA_APP_COMMIT is the commit the app was built from.
enum ShellEnvironment {
    static var dockerPaths: [String] {
        let home = AppPaths.home.path
        return ["/usr/local/bin", "\(home)/.docker/bin", "/Applications/Docker.app/Contents/Resources/bin",
                "/opt/homebrew/bin"]
    }

    static func make(base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        var env = base
        var path = (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin").split(separator: ":").map(String.init)
        for extra in dockerPaths where !path.contains(extra) { path.append(extra) }
        // The app's own small stand-ins for git and open come first (LauncherShims says why).
        path.removeAll { $0 == AppPaths.shimDir.path }
        path.insert(AppPaths.shimDir.path, at: 0)
        env["PATH"] = path.joined(separator: ":")
        env["LANG"] = Lang.posixLocale
        env.removeValue(forKey: "LC_ALL")
        env.removeValue(forKey: "LC_MESSAGES")
        env["COMPOSE_PROJECT_NAME"] = "arva"
        env["ARVA_APP_COMMIT"] = AppInfo.commit
        if env["HOME"] == nil { env["HOME"] = AppPaths.home.path }
        return env
    }

    /// The first executable called `name` on the launcher's PATH.
    static func which(_ name: String, env: [String: String] = make()) -> String? {
        for dir in (env["PATH"] ?? "").split(separator: ":") {
            let candidate = "\(dir)/\(name)"
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        return nil
    }
}

/// Text from a process, without terminal escape sequences, carriage returns or other control characters (the
/// first-run log is a terminal recording).
func cleanOutput(_ text: String) -> String {
    var out = text
    for pattern in ["\\x{1B}\\][^\\x{07}\\x{1B}]*(\\x{07}|\\x{1B}\\\\)",   // OSC (window titles)
                    "\\x{1B}\\[[0-9;?]*[ -/]*[@-~]",                      // CSI (colours, cursor)
                    "\\x{1B}[()][0-9A-Za-z]|\\x{1B}[=>78]"] {           // character sets, keypad
        out = out.replacingOccurrences(of: pattern, with: "", options: .regularExpression)
    }
    out = out.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
    out = out.replacingOccurrences(of: "[\\x{00}-\\x{08}\\x{0B}-\\x{1F}\\x{7F}]", with: "", options: .regularExpression)
    return out
}

/// A child process whose standard output and error go to a log file (one file for both, so they keep their order),
/// read back as it grows. A file, not a pipe: when the app quits while the launcher is still starting ARVA ("Quit
/// without stopping"), the launcher and docker compose keep writing there and finish their work, where a pipe with
/// nobody reading would stop them half way (SIGPIPE). Standard input is /dev/null: the launcher never waits for an
/// answer.
final class ShellTask {
    let process = Process()
    private let logURL: URL
    private let queue = DispatchQueue(label: "org.arva.ARVA.shell")
    private var reader: FileHandle?
    private var writer: FileHandle?
    private var timer: DispatchSourceTimer?
    private var pending = Data()
    private var captured = ""
    private var lastOutput = Date()
    private var finished = false

    /// Called on the main queue with each chunk of complete lines.
    var onOutput: ((String) -> Void)?
    /// Called once on the main queue with the exit status and everything the process printed.
    var onExit: ((Int32, String) -> Void)?

    init(executable: String, arguments: [String], directory: URL, environment: [String: String], logFile: URL) {
        logURL = logFile
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.currentDirectoryURL = directory
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
    }

    var output: String { queue.sync { captured } }
    /// When the process last printed something (for the inactivity timeout).
    var lastOutputDate: Date { queue.sync { lastOutput } }
    var isRunning: Bool { process.isRunning }

    func start() throws {
        let fm = FileManager.default
        try fm.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard fm.createFile(atPath: logURL.path, contents: nil) else {
            throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: logURL.path])
        }
        let writer = try FileHandle(forWritingTo: logURL)
        let reader = try FileHandle(forReadingFrom: logURL)
        self.reader = reader
        self.writer = writer
        process.standardOutput = writer
        process.standardError = writer
        process.terminationHandler = { [weak self] _ in
            guard let self else { return }
            self.queue.async { self.finish() }
        }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 0.3, repeating: 0.3)
        timer.setEventHandler { [weak self] in self?.drain(final: false) }
        self.timer = timer
        timer.resume()
        do {
            try process.run()
        } catch {
            timer.cancel()
            try? writer.close()
            try? reader.close()
            throw error
        }
    }

    /// Called on `queue`: reads what was added to the log since the last time.
    private func drain(final: Bool) {
        guard let reader else { return }
        if let data = try? reader.readToEnd(), !data.isEmpty {
            pending.append(data)
            lastOutput = Date()
        }
        flush(final: final)
    }

    /// Called on `queue` once the process has exited.
    private func finish() {
        guard !finished else { return }
        finished = true
        timer?.cancel()
        timer = nil
        drain(final: true)
        try? reader?.close()
        reader = nil
        try? writer?.close()
        writer = nil
        let status = process.terminationStatus
        let text = captured
        DispatchQueue.main.async { self.onExit?(status, text) }
    }

    /// Called on `queue`: hands on the complete lines read so far (everything at the end).
    private func flush(final: Bool) {
        var chunk = Data()
        if final {
            chunk = pending
            pending = Data()
        } else if let newline = pending.lastIndex(of: 0x0A) {
            chunk = pending.subdata(in: pending.startIndex..<pending.index(after: newline))
            pending.removeSubrange(pending.startIndex..<pending.index(after: newline))
        }
        guard !chunk.isEmpty else { return }
        let text = cleanOutput(String(decoding: chunk, as: UTF8.self))
        captured += text
        if captured.count > 400_000 { captured = String(captured.suffix(300_000)) }
        DispatchQueue.main.async { self.onOutput?(text) }
    }

    /// Stops the process and everything it started (docker compose pull or up, which would otherwise go on alone),
    /// then calls `completion` on the main queue once they are gone.
    func terminateAll(completion: (() -> Void)? = nil) {
        let root = process.processIdentifier
        guard process.isRunning, root > 0 else {
            if let completion { DispatchQueue.main.async(execute: completion) }
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            ProcessTree.terminate(root: root)
            if let completion { DispatchQueue.main.async(execute: completion) }
        }
    }

    /// Runs a short command and waits for it (never on the main thread): its exit status and output, or nil when it
    /// could not start or ran longer than `timeout` seconds (it is then stopped).
    static func run(_ executable: String, _ arguments: [String], directory: URL? = nil,
                    environment: [String: String] = ShellEnvironment.make(),
                    timeout: TimeInterval) -> (status: Int32, output: String)? {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        if let directory { process.currentDirectoryURL = directory }
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = pipe
        process.standardError = pipe
        let done = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in done.signal() }
        var data = Data()
        let read = DispatchSemaphore(value: 0)
        do { try process.run() } catch { return nil }
        DispatchQueue.global().async {
            data = pipe.fileHandleForReading.readDataToEndOfFile()
            read.signal()
        }
        if done.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            _ = done.wait(timeout: .now() + 2)
            return nil
        }
        _ = read.wait(timeout: .now() + 2)
        return (process.terminationStatus, cleanOutput(String(decoding: data, as: UTF8.self)))
    }
}

/// A process and all its descendants, found with ps (a shell script's children are not in a process group of their
/// own, so signalling the script alone would leave docker compose running).
enum ProcessTree {
    /// Every process's parent, or an empty table when ps cannot run.
    static func parents() -> [pid_t: pid_t] {
        guard let result = ShellTask.run("/bin/ps", ["-A", "-o", "pid=,ppid="], environment: ["PATH": "/usr/bin:/bin"],
                                         timeout: 10), result.status == 0 else { return [:] }
        var table: [pid_t: pid_t] = [:]
        for line in result.output.split(separator: "\n") {
            let fields = line.split(separator: " ", omittingEmptySubsequences: true)
            if fields.count >= 2, let pid = pid_t(fields[0]), let ppid = pid_t(fields[1]) { table[pid] = ppid }
        }
        return table
    }

    static func descendants(of root: pid_t, in table: [pid_t: pid_t]) -> [pid_t] {
        var children: [pid_t: [pid_t]] = [:]
        for (pid, ppid) in table where pid != ppid { children[ppid, default: []].append(pid) }
        var found: [pid_t] = []
        var queue = [root]
        while let next = queue.popLast() {
            for child in children[next] ?? [] where child != root && !found.contains(child) {
                found.append(child)
                queue.append(child)
            }
        }
        return found
    }

    static func isAlive(_ pid: pid_t) -> Bool {
        kill(pid, 0) == 0 || errno == EPERM
    }

    /// Freezes the tree (so nothing new starts while it is listed), asks every process to stop (SIGTERM), and kills
    /// what is left after `grace` seconds. Never on the main thread.
    static func terminate(root: pid_t, grace: TimeInterval = 10) {
        guard root > 1, isAlive(root) else { return }
        kill(root, SIGSTOP)
        var all: [pid_t] = [root]
        for _ in 0..<4 {
            let new = descendants(of: root, in: parents()).filter { !all.contains($0) }
            if new.isEmpty { break }
            for pid in new { kill(pid, SIGSTOP) }
            all += new
        }
        for pid in all { kill(pid, SIGTERM) }
        for pid in all { kill(pid, SIGCONT) }
        let deadline = Date().addingTimeInterval(grace)
        while Date() < deadline && all.contains(where: isAlive) { usleep(200_000) }
        for pid in all where isAlive(pid) { kill(pid, SIGKILL) }
    }
}
