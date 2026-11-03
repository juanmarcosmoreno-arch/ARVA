import Foundation

/// The environment the launcher scripts and docker run with. An app opened from Finder gets a minimal PATH and no
/// LANG, so Docker Desktop's usual places are added (as ARVA.command does), the language is passed on, and the
/// Compose project is named explicitly: docker-compose.yml already says `name: arva`, and COMPOSE_PROJECT_NAME=arva
/// makes sure no other value from the environment changes it, so an ARVA started before from ~/ARVA (or with
/// ARVA.command) is the same project, with the same volumes.
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
        env["PATH"] = path.joined(separator: ":")
        env["LANG"] = Lang.posixLocale
        env.removeValue(forKey: "LC_ALL")
        env.removeValue(forKey: "LC_MESSAGES")
        env["COMPOSE_PROJECT_NAME"] = "arva"
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

/// Text from a process, without terminal escape sequences or carriage returns.
func cleanOutput(_ text: String) -> String {
    var out = text.replacingOccurrences(of: "\u{1B}\\[[0-9;?]*[ -/]*[@-~]", with: "", options: .regularExpression)
    out = out.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
    return out
}

/// A child process whose standard output and error are read as they come (one pipe for both, so they keep their
/// order). Standard input is /dev/null: the launcher never waits for an answer.
final class ShellTask {
    let process = Process()
    private let pipe = Pipe()
    private let queue = DispatchQueue(label: "org.arva.ARVA.shell")
    private var pending = Data()
    private var captured = ""
    private let group = DispatchGroup()
    private var lastOutput = Date()

    /// Called on the main queue with each chunk of complete lines.
    var onOutput: ((String) -> Void)?
    /// Called once on the main queue with the exit status and everything the process printed.
    var onExit: ((Int32, String) -> Void)?

    init(executable: String, arguments: [String], directory: URL, environment: [String: String]) {
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.currentDirectoryURL = directory
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = pipe
        process.standardError = pipe
    }

    var output: String { queue.sync { captured } }
    /// When the process last printed something (for the inactivity timeout).
    var lastOutputDate: Date { queue.sync { lastOutput } }
    var isRunning: Bool { process.isRunning }

    private var eof = false
    private var finished = false

    func start() throws {
        group.enter()
        group.enter()
        let reader = pipe.fileHandleForReading
        reader.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard let self else { return }
            self.queue.async {
                if data.isEmpty {
                    self.closeOutput()
                } else {
                    self.pending.append(data)
                    self.lastOutput = Date()
                    self.flush(final: false)
                }
            }
        }
        process.terminationHandler = { [weak self] _ in
            guard let self else { return }
            self.group.leave()
            // A child process that outlives the script and keeps the pipe open must not hold the result back.
            self.queue.asyncAfter(deadline: .now() + 3) { self.closeOutput() }
        }
        group.notify(queue: queue) { [weak self] in self?.finish() }
        do {
            try process.run()
        } catch {
            reader.readabilityHandler = nil
            throw error
        }
    }

    /// Called on `queue`, once the pipe is closed (or no longer waited for).
    private func closeOutput() {
        guard !eof else { return }
        eof = true
        pipe.fileHandleForReading.readabilityHandler = nil
        flush(final: true)
        group.leave()
    }

    /// Called on `queue` once the process has exited and its output is read.
    private func finish() {
        guard !finished else { return }
        finished = true
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

    func terminate() {
        if process.isRunning { process.terminate() }
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
