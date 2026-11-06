import Foundation

// ARVA.app's native executor (docs/plan-flye-nativo.md, "Contrato implementado"): no port is opened; the app calls
// ARVA's API at localhost with its token, registers itself every register_seconds with what native.py says about
// its Flye, asks for a waiting job every poll_seconds, and runs a claimed job with arva_tools/native.py (argv as a
// list, no shell), which writes Flye's log where the worker reads it (<results>/flye.stderr.log). While it runs, a
// heartbeat every heartbeat_seconds renews the lease and answers whether to stop; at the end the report native.py
// printed goes to the finish endpoint.

/// A job held with a lease.
struct NativeJob: Equatable {
    let id: String
    let leaseId: String
    var leaseSeconds: TimeInterval
    var heartbeatSeconds: TimeInterval

    /// The API's identifiers: a job id ([A-Za-z0-9-], also a file name here) and a lease id (a UUID).
    static func isJobID(_ id: String) -> Bool {
        (1...64).contains(id.count) && id.unicodeScalars.allSatisfy {
            ($0 >= "A" && $0 <= "Z") || ($0 >= "a" && $0 <= "z") || ($0 >= "0" && $0 <= "9") || $0 == "-"
        }
    }

    static func isLeaseID(_ id: String) -> Bool {
        id.count == 36 && id.unicodeScalars.allSatisfy { ($0 >= "0" && $0 <= "9") || ($0 >= "a" && $0 <= "f") || $0 == "-" }
    }
}

/// The lease rules, as a state machine without side effects (the executor performs the actions it returns; the
/// self-test drives it against a stand-in API). idle → launching (claimed) → running (native.py started) →
/// [stopping (cancel, lease lost, quitting)] → finishing (report sent) → idle.
/// - A heartbeat is due every heartbeatSeconds while a job is held (also while stopping and finishing, so the lease
///   is still held when the report arrives).
/// - "cancel": stop the tool, then send its report ("stopped").
/// - 409 native_lease_lost, or no successful heartbeat for leaseSeconds (the API's lease has then expired too): stop
///   the tool and send nothing more.
/// - The report is sent once; a failed request is tried again (finishAttemptsMax in all) while the lease can still
///   be held.
struct NativeLease {
    enum State: Equatable { case idle, launching, running, stopping, finishing }
    enum StopReason: Equatable { case cancelled, leaseLost, quitting }

    enum Action: Equatable {
        case launch(NativeJob)
        case heartbeat(NativeJob)
        case terminate
        case finish(NativeJob)
        case forget
    }

    enum Event: Equatable {
        case claimed(NativeJob)
        case launched
        /// Nothing was run (refused here, or native.py could not start): the report says so.
        case launchFailed
        case tick
        case heartbeatAnswered(cancel: Bool)
        case heartbeatLost
        case heartbeatFailed
        case exited(hasReport: Bool)
        case finishAnswered
        case finishFailed
        case quit
    }

    static let finishAttemptsMax = 5
    static let finishRetrySeconds: TimeInterval = 5

    private(set) var state: State = .idle
    private(set) var job: NativeJob?
    private(set) var stopReason: StopReason?
    /// False once the lease is known to be lost: nothing more is sent for this job.
    private(set) var sendFinish = true
    private var lastHeartbeatSent: Date?
    private var lastHeartbeatOK: Date?
    private var heartbeatInFlight = false
    private var finishInFlight = false
    private var finishAttempts = 0
    private var finishRetryAt: Date?

    var isBusy: Bool { state != .idle }

    private mutating func reset() {
        state = .idle
        job = nil
        stopReason = nil
        sendFinish = true
        lastHeartbeatSent = nil
        lastHeartbeatOK = nil
        heartbeatInFlight = false
        finishInFlight = false
        finishAttempts = 0
        finishRetryAt = nil
    }

    private func leaseExpired(_ now: Date) -> Bool {
        guard let job, let ok = lastHeartbeatOK else { return false }
        return now.timeIntervalSince(ok) > job.leaseSeconds
    }

    private mutating func sendFinishNow(_ now: Date) -> [Action] {
        guard let job else { return [] }
        finishAttempts += 1
        finishInFlight = true
        finishRetryAt = nil
        return [.finish(job)]
    }

    mutating func handle(_ event: Event, now: Date) -> [Action] {
        switch (state, event) {
        case (.idle, .claimed(let claimed)):
            reset()
            job = claimed
            state = .launching
            lastHeartbeatOK = now   // the claim started the lease
            return [.launch(claimed)]

        case (.launching, .launched):
            guard let job else { return [] }
            state = .running
            heartbeatInFlight = true
            lastHeartbeatSent = now
            return [.heartbeat(job)]

        case (.launching, .launchFailed):
            state = .finishing
            return sendFinishNow(now)

        case (.launching, .quit):
            reset()
            return [.forget]

        case (.running, .tick), (.stopping, .tick), (.finishing, .tick):
            guard let job else { return [] }
            if leaseExpired(now) {
                sendFinish = false
                switch state {
                case .running:
                    state = .stopping
                    stopReason = .leaseLost
                    return [.terminate]
                case .finishing where !finishInFlight:
                    reset()
                    return [.forget]
                default:
                    stopReason = .leaseLost
                    return []
                }
            }
            var actions: [Action] = []
            if !heartbeatInFlight, lastHeartbeatSent.map({ now.timeIntervalSince($0) >= job.heartbeatSeconds }) ?? true {
                heartbeatInFlight = true
                lastHeartbeatSent = now
                actions.append(.heartbeat(job))
            }
            if state == .finishing, !finishInFlight, let retry = finishRetryAt, now >= retry {
                actions += sendFinishNow(now)
            }
            return actions

        case (.running, .heartbeatAnswered(let cancel)):
            heartbeatInFlight = false
            lastHeartbeatOK = now
            if cancel {
                state = .stopping
                stopReason = .cancelled
                return [.terminate]
            }
            return []

        case (.stopping, .heartbeatAnswered), (.finishing, .heartbeatAnswered):
            heartbeatInFlight = false
            lastHeartbeatOK = now
            return []

        case (.running, .heartbeatLost):
            heartbeatInFlight = false
            sendFinish = false
            state = .stopping
            stopReason = .leaseLost
            return [.terminate]

        case (.stopping, .heartbeatLost):
            heartbeatInFlight = false
            sendFinish = false
            stopReason = .leaseLost
            return []

        case (.finishing, .heartbeatLost):
            heartbeatInFlight = false
            sendFinish = false
            if finishInFlight { return [] }
            reset()
            return [.forget]

        case (.running, .heartbeatFailed), (.stopping, .heartbeatFailed), (.finishing, .heartbeatFailed):
            heartbeatInFlight = false
            return []

        case (.running, .quit):
            state = .stopping
            stopReason = .quitting
            return [.terminate]

        case (.launching, .exited(let hasReport)), (.running, .exited(let hasReport)), (.stopping, .exited(let hasReport)):
            if hasReport && sendFinish && !leaseExpired(now) {
                state = .finishing
                return sendFinishNow(now)
            }
            reset()
            return [.forget]

        case (.finishing, .finishAnswered):
            reset()
            return [.forget]

        case (.finishing, .finishFailed):
            finishInFlight = false
            if finishAttempts >= NativeLease.finishAttemptsMax || !sendFinish || leaseExpired(now) {
                reset()
                return [.forget]
            }
            finishRetryAt = now.addingTimeInterval(NativeLease.finishRetrySeconds)
            return []

        default:
            return []
        }
    }
}

/// The answer to one request to the API.
struct NativeHTTPResult {
    let status: Int?
    let json: Any?

    var object: [String: Any]? { json as? [String: Any] }
    var code: String? { object?["code"] as? String }
}

/// The API's native endpoints, with the token (Authorization: Bearer). Requests go to localhost only, never through
/// a proxy; completions run on the main queue (or on the session's queue for `postSync`).
final class NativeAPIClient {
    static let base = URL(string: "http://localhost:8080/api/v1/")!
    let token: String
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.connectionProxyDictionary = [:]
        config.httpCookieAcceptPolicy = .never
        config.httpShouldSetCookies = false
        return URLSession(configuration: config)
    }()

    init(token: String) { self.token = token }

    /// The request for one native endpoint ("native/executor", "native/jobs/<id>/heartbeat", ...), or nil for a path
    /// that is not one of them.
    static func request(_ path: String, body: [String: Any], token: String) -> URLRequest? {
        guard path.hasPrefix("native/"), !path.contains(".."), !path.contains("?"),
              let url = URL(string: path, relativeTo: base)?.absoluteURL,
              url.host == "localhost", url.port == 8080, url.path.hasPrefix("/api/v1/native/"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = data
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private static func result(_ data: Data?, _ response: URLResponse?) -> NativeHTTPResult {
        let status = (response as? HTTPURLResponse)?.statusCode
        let json = data.flatMap { $0.isEmpty ? nil : try? JSONSerialization.jsonObject(with: $0) }
        return NativeHTTPResult(status: status, json: json)
    }

    func post(_ path: String, _ body: [String: Any], completion: @escaping (NativeHTTPResult) -> Void) {
        guard let request = Self.request(path, body: body, token: token) else {
            DispatchQueue.main.async { completion(NativeHTTPResult(status: nil, json: nil)) }
            return
        }
        session.dataTask(with: request) { data, response, _ in
            let result = Self.result(data, response)
            DispatchQueue.main.async { completion(result) }
        }.resume()
    }

    /// The same request, waited for (at most `timeout` seconds): only when the app quits.
    func postSync(_ path: String, _ body: [String: Any], timeout: TimeInterval) -> NativeHTTPResult {
        guard let request = Self.request(path, body: body, token: token) else { return NativeHTTPResult(status: nil, json: nil) }
        var result = NativeHTTPResult(status: nil, json: nil)
        let done = DispatchSemaphore(value: 0)
        session.dataTask(with: request) { data, response, _ in
            result = Self.result(data, response)
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + timeout)
        return result
    }
}

/// The report native.py prints (its last line), made safe to send as is: the API refuses a `detail` longer than
/// 2000 characters.
enum NativeReport {
    static func parse(_ stdout: String) -> [String: Any]? {
        for line in stdout.components(separatedBy: "\n").reversed() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("{"),
                  var object = try? JSONSerialization.jsonObject(with: Data(trimmed.utf8)) as? [String: Any],
                  NativeTool.named(object["tool"] as? String) != nil, object["outcome"] is String else { continue }
            if let detail = object["detail"] as? String, detail.count > 2000 {
                object["detail"] = String(detail.prefix(1990)) + " […]"
            }
            return object
        }
        return nil
    }

    /// A report for a job that was never handed to native.py (refused by the app's own checks, or native.py could
    /// not be started): nothing ran, so there is no argv.
    static func notRun(outcome: String, code: String, detail: String, executable: String,
                       tool: String = "flye") -> [String: Any] {
        ["tool": tool, "outcome": outcome, "exit_code": NSNull(), "argv": NSNull(), "executable": executable,
         "outputs": [String](), "started_at": NSNull(), "finished_at": NSNull(), "duration_seconds": NSNull(),
         "code": code, "detail": String(detail.prefix(1990))]
    }
}

/// One process as ps lists it.
struct NativeProcessEntry: Equatable, Codable {
    let pid: Int32
    let command: String
}

/// Processes and their command lines (ps -ww: never cut), to kill exactly the processes recorded and never another
/// one that got the same number since.
enum NativeProcesses {
    static func table() -> [pid_t: (ppid: pid_t, command: String)] {
        guard let result = NativeCommand.run("/bin/ps", ["-A", "-ww", "-o", "pid=,ppid=,command="],
                                             environment: ["PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"], timeout: 10),
              result.status == 0 else { return [:] }
        var table: [pid_t: (ppid: pid_t, command: String)] = [:]
        for line in result.stdout.split(separator: "\n") {
            let fields = line.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
            guard fields.count >= 2, let pid = pid_t(fields[0]), let ppid = pid_t(fields[1]) else { continue }
            table[pid] = (ppid, fields.count == 3 ? String(fields[2]) : "")
        }
        return table
    }

    /// A process and its descendants, with their command lines.
    static func tree(root: pid_t) -> [NativeProcessEntry] {
        let all = table()
        guard let rootEntry = all[root] else { return [] }
        var parents: [pid_t: pid_t] = [:]
        for (pid, entry) in all { parents[pid] = entry.ppid }
        let descendants = ProcessTree.descendants(of: root, in: parents)
        return [NativeProcessEntry(pid: root, command: rootEntry.command)]
            + descendants.compactMap { pid in all[pid].map { NativeProcessEntry(pid: pid, command: $0.command) } }
    }

    /// Kills the recorded processes that still run the same command (and contain one of `markers`), with SIGTERM
    /// and, after `grace` seconds, SIGKILL. Returns how many were signalled. Never on the main thread.
    @discardableResult
    static func kill(_ recorded: [NativeProcessEntry], markers: [String], grace: TimeInterval = 5) -> Int {
        let now = table()
        let targets = recorded.filter { entry in
            guard entry.pid > 1, entry.pid != getpid(), let current = now[entry.pid] else { return false }
            return current.command == entry.command && markers.contains { !$0.isEmpty && entry.command.contains($0) }
        }
        for entry in targets { Darwin.kill(entry.pid, SIGTERM) }
        let deadline = Date().addingTimeInterval(grace)
        while Date() < deadline && targets.contains(where: { ProcessTree.isAlive($0.pid) }) { usleep(100_000) }
        for entry in targets where ProcessTree.isAlive(entry.pid) { Darwin.kill(entry.pid, SIGKILL) }
        return targets.count
    }
}

/// The record of the job running now, in the app's support folder (running.json): native.py's process and its
/// descendants as last seen. When the app is opened again after it quit or crashed during a run, these processes
/// (which macOS does not stop with the app) are killed before anything else; the API's lease expires on its own and
/// the worker keeps Flye's folder for a resume.
struct NativeRunningRecord: Codable, Equatable {
    var jobId: String
    var leaseId: String
    var startedAt: Date
    var processes: [NativeProcessEntry]

    /// What a process of a native run looks like: the bundled native.py or a program of a native tool's environment.
    static var markers: [String] { ["arva_tools/native.py"] + NativeTool.all.map { $0.envPrefix.path + "/" } }

    static func load(from url: URL = NativePaths.runningRecord) -> NativeRunningRecord? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(NativeRunningRecord.self, from: data)
    }

    func save(to url: URL = NativePaths.runningRecord) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(self) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        try? data.write(to: url, options: .atomic)
    }

    static func clear(at url: URL = NativePaths.runningRecord) {
        try? FileManager.default.removeItem(at: url)
    }

    /// Kills what a previous run of the app left running (never on the main thread). Returns the processes stopped.
    @discardableResult
    static func killOrphans(at url: URL = NativePaths.runningRecord, markers: [String] = NativeRunningRecord.markers) -> Int {
        guard let record = load(from: url) else { return 0 }
        let count = NativeProcesses.kill(record.processes, markers: markers)
        clear(at: url)
        return count
    }
}

/// native.py running for one job: argv as a list (no shell), standard output (the report) kept, standard error
/// (Python's own messages; Flye's log goes to <results>/flye.stderr.log) to a log file.
final class NativeRun {
    let process = Process()
    private let stdoutPipe = Pipe()
    private var stdoutData = Data()
    private let lock = NSLock()
    /// Left once the standard output was read to its end (any number of waiters).
    private let reading = DispatchGroup()
    /// native.py's process and descendants as last seen (snapshot()).
    private(set) var processes: [NativeProcessEntry] = []
    /// Called once on the main queue with the exit status and the standard output.
    var onExit: ((Int32, String) -> Void)?

    init(executable: String, arguments: [String], environment: [String: String], directory: URL, stderrLog: URL) throws {
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.environment = environment
        process.currentDirectoryURL = directory
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdoutPipe
        let fm = FileManager.default
        try fm.createDirectory(at: stderrLog.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard fm.createFile(atPath: stderrLog.path, contents: nil) else {
            throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: stderrLog.path])
        }
        process.standardError = try FileHandle(forWritingTo: stderrLog)
    }

    var pid: pid_t { process.processIdentifier }
    var isRunning: Bool { process.isRunning }

    func start() throws {
        process.terminationHandler = { [weak self] proc in
            guard let self else { return }
            DispatchQueue.global().async {
                _ = self.reading.wait(timeout: .now() + 10)
                self.lock.lock()
                let text = String(decoding: self.stdoutData, as: UTF8.self)
                self.lock.unlock()
                if let log = self.process.standardError as? FileHandle { try? log.close() }
                let status = proc.terminationStatus
                DispatchQueue.main.async { self.onExit?(status, text) }
            }
        }
        reading.enter()
        do {
            try process.run()
        } catch {
            reading.leave()
            throw error
        }
        let handle = stdoutPipe.fileHandleForReading
        DispatchQueue.global().async { [weak self] in
            let data = handle.readDataToEndOfFile()
            if let self {
                self.lock.lock()
                self.stdoutData = data
                self.lock.unlock()
                self.reading.leave()
            }
        }
    }

    /// Records the process tree as it is now (never on the main thread).
    @discardableResult
    func snapshot() -> [NativeProcessEntry] {
        guard isRunning else { return processes }
        let tree = NativeProcesses.tree(root: pid)
        lock.lock()
        if !tree.isEmpty { processes = tree }
        let current = processes
        lock.unlock()
        return current
    }

    /// Asks native.py to stop (SIGTERM: it kills Flye's process group and prints a "stopped" report); after `grace`
    /// seconds, the whole tree is stopped and killed. Then any recorded descendant still running is killed. Never on
    /// the main thread.
    func stop(grace: TimeInterval) {
        snapshot()
        let root = pid
        if isRunning, root > 1 { kill(root, SIGTERM) }
        let deadline = Date().addingTimeInterval(grace)
        while isRunning && Date() < deadline { usleep(100_000) }
        if isRunning { ProcessTree.terminate(root: root, grace: 5) }
        cleanup()
    }

    /// Kills recorded descendants (Flye, its helpers) that outlived native.py.
    func cleanup() {
        lock.lock()
        let recorded = processes.filter { $0.pid != pid }
        lock.unlock()
        NativeProcesses.kill(recorded, markers: recorded.map(\.command), grace: 3)
    }

    /// For the self-test and for quitting: waits (polling) until the process has exited and its output was read.
    func waitForExit(timeout: TimeInterval) -> (status: Int32, stdout: String)? {
        let deadline = Date().addingTimeInterval(timeout)
        while isRunning && Date() < deadline { usleep(50_000) }
        guard !isRunning else { return nil }
        _ = reading.wait(timeout: .now() + max(0.5, deadline.timeIntervalSinceNow))
        lock.lock()
        let text = String(decoding: stdoutData, as: UTF8.self)
        lock.unlock()
        return (process.terminationStatus, text)
    }
}

/// The executor itself (main thread): registration, claim, the run, heartbeats, the report. Started when ARVA
/// answers and "Flye for this Mac" or "Bakta for this Mac" is installed; shut down (the tool stopped, its report sent)
/// when the app quits.
final class NativeExecutor {
    enum Phase: Equatable {
        /// Not started, not Apple silicon, or Flye for this Mac is not installed.
        case off
        /// ARVA keeps its data in a Docker volume, or the data folder is not reachable: Flye cannot run here.
        case noMacFolder
        /// ARVA does not answer, or answered with an error (the code).
        case waiting(String?)
        /// Registered, but the API says this Flye cannot run jobs (its reason).
        case notReady(String)
        case ready
        case running(String)
    }

    var onChange: (() -> Void)?
    private(set) var phase: Phase = .off {
        didSet { if phase != oldValue { onChange?() } }
    }

    private var lease = NativeLease()
    private var client: NativeAPIClient?
    private var timer: Timer?
    /// The facts of each installed tool, by its id (what is registered).
    private var toolFacts: [String: NativeFacts] = [:]
    private var facts: NativeFacts? { toolFacts["flye"] }
    private var factsProblem: String?
    private var factsLoading = false
    private var lastFactsAttempt: Date?
    private var registered = false
    /// The tools the API said this executor may run now.
    private var readyTools: Set<String> = []
    private var flyeReady: Bool { !readyTools.isEmpty }
    /// The tool of the job running now (its name in the status texts).
    private var runningTool: NativeTool?
    private var registerSeconds: TimeInterval = 20
    private var pollSeconds: TimeInterval = 5
    private var lastRegister: Date?
    private var lastPoll: Date?
    private var registering = false
    private var claiming = false
    private var dataDir: String?
    private var storageId: String?
    /// The database folders of arva.conf as last registered (NativePaths.databaseDirs).
    private var databaseDirs: [String] = []
    private var run: NativeRun?
    private var work: [String: Any]?
    private var report: [String: Any]?
    private var workFile: URL?
    private var idleWaiters: [() -> Void] = []

    /// Generated once and kept (UserDefaults): the API knows this app by it.
    static var executorId: String {
        let defaults = UserDefaults.standard
        if let saved = defaults.string(forKey: NativePaths.executorIDKey), (8...64).contains(saved.count),
           NativeJob.isJobID(saved) {
            return saved
        }
        let made = UUID().uuidString.lowercased()
        defaults.set(made, forKey: NativePaths.executorIDKey)
        return made
    }

    var isBusy: Bool { lease.isBusy }
    var lastFactsProblem: String? { factsProblem }
    var installedFacts: NativeFacts? { facts }

    /// Starts the executor (again): a new token, then the registration loop. Nothing happens without Flye for this
    /// Mac installed on Apple silicon.
    func start() {
        guard timer == nil else { return }
        guard NativePaths.platformSupported, NativePaths.anyInstalled else {
            phase = .off
            return
        }
        let token = NativeToken.make()
        do {
            try NativeToken.write(token, to: NativePaths.tokenFile())
        } catch {
            phase = .waiting("token_not_written")
            return
        }
        client = NativeAPIClient(token: token)
        registered = false
        lastRegister = nil
        timer = commonTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
        reloadFacts()
    }

    /// After installing or removing a native tool for this Mac.
    func reloadFacts() {
        toolFacts = [:]
        factsProblem = nil
        registered = false
        lastRegister = nil
        if !NativePaths.anyInstalled {
            if !lease.isBusy { stopTimer() }
            phase = .off
            return
        }
        // Not started (ARVA does not answer yet, or nothing was installed when it did): start() loads them.
        guard timer != nil, !factsLoading else { return }
        factsLoading = true
        lastFactsAttempt = Date()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var loaded: [String: NativeFacts] = [:]
            var problems: [String] = []
            for tool in NativeTool.all where tool.isInstalled {
                let (facts, problem) = NativeFacts.load(tool: tool)
                if let facts { loaded[tool.id] = facts } else { problems.append(problem ?? "\(tool.id) facts") }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.factsLoading = false
                self.toolFacts = loaded
                self.factsProblem = problems.isEmpty ? nil : problems.joined(separator: "; ")
                if loaded.isEmpty { self.phase = .waiting("facts_unreadable") }
            }
        }
    }

    /// While Flye for this Mac is being installed or removed (never while a job runs): no registration, no claim.
    /// start() resumes.
    func suspend() {
        guard !lease.isBusy else { return }
        stopTimer()
        toolFacts = [:]
        registered = false
        readyTools = []
        lastRegister = nil
        phase = .off
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    // MARK: The loop (every second)

    private func tick() {
        let now = Date()
        perform(lease.handle(.tick, now: now))
        guard !toolFacts.isEmpty else {
            // Read again every minute when they could not be read (Flye's --help timed out, for example).
            if !factsLoading, lastFactsAttempt.map({ now.timeIntervalSince($0) >= 60 }) ?? true { reloadFacts() }
            return
        }
        if lastRegister.map({ now.timeIntervalSince($0) >= registerSeconds }) ?? true, !registering {
            register(now)
        }
        if !lease.isBusy, registered, flyeReady, !claiming,
           lastPoll.map({ now.timeIntervalSince($0) >= pollSeconds }) ?? true {
            claim(now)
        }
    }

    /// The data folder on this Mac (ARVA_DATA_DIR in arva.conf) and the storage id in its marker, read again at each
    /// registration (the disk may have been connected since).
    private static func location() -> (dataDir: String, storageId: String)? {
        guard let dir = ArvaConfig.load(from: AppPaths.configFile())?.dataDir, dir.hasPrefix("/"),
              let data = try? Data(contentsOf: URL(fileURLWithPath: dir).appendingPathComponent(".arva-storage")),
              let marker = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = marker["id"] as? String,
              id.range(of: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", options: .regularExpression) != nil
        else { return nil }
        return (dir, id)
    }

    private func register(_ now: Date) {
        guard let client, let facts = toolFacts["flye"] ?? toolFacts.values.first else { return }
        lastRegister = now
        guard let place = Self.location() else {
            registered = false
            readyTools = []
            if !lease.isBusy { phase = .noMacFolder }
            return
        }
        dataDir = place.dataDir
        storageId = place.storageId
        databaseDirs = NativePaths.databaseDirs(ArvaConfig.load(from: AppPaths.configFile()))
        let version = AppInfo.version.range(of: "^[A-Za-z0-9._+-]{1,64}$", options: .regularExpression) != nil ? AppInfo.version : "0"
        let body: [String: Any] = [
            "executor_id": Self.executorId, "app_version": version, "platform": "osx-arm64",
            "macos": facts.json["macos"] ?? NSNull(), "chip": facts.json["chip"] ?? NSNull(),
            "memory_bytes": facts.json["memory_bytes"] ?? NSNull(),
            "data_dir": place.dataDir, "storage_id": place.storageId, "database_dirs": databaseDirs,
            "tools": toolFacts.mapValues { $0.json },
        ]
        registering = true
        client.post("native/executor", body) { [weak self] result in
            guard let self else { return }
            self.registering = false
            guard result.status == 200, let object = result.object else {
                self.registered = false
                self.readyTools = []
                if !self.lease.isBusy { self.phase = .waiting(result.code ?? result.status.map { "http_\($0)" }) }
                return
            }
            self.registered = true
            if let s = object["register_seconds"] as? Double, (5...300).contains(s) { self.registerSeconds = s }
            if let s = object["poll_seconds"] as? Double, (1...120).contains(s) { self.pollSeconds = s }
            let ready = object["ready"] as? [String: Any] ?? [:]
            var tools: Set<String> = []
            var reason: String?
            for tool in NativeTool.all {
                guard let entry = ready[tool.id] as? [String: Any] else { continue }
                if entry["ready"] as? Bool ?? false { tools.insert(tool.id) } else if reason == nil {
                    reason = entry["reason"] as? String
                }
            }
            self.readyTools = tools
            if !self.lease.isBusy {
                self.phase = !tools.isEmpty ? .ready : .notReady(reason ?? "unknown")
            }
        }
    }

    private func claim(_ now: Date) {
        guard let client else { return }
        lastPoll = now
        claiming = true
        client.post("native/jobs/claim", ["executor_id": Self.executorId, "tools": readyTools.sorted()]) { [weak self] result in
            guard let self else { return }
            self.claiming = false
            if result.status == 409, result.code == "native_executor_unknown" || result.code == "native_not_ready" {
                self.registered = false
                self.lastRegister = nil
                return
            }
            guard result.status == 200, let object = result.object, !self.lease.isBusy, self.timer != nil,
                  let jobId = object["job_id"] as? String, NativeJob.isJobID(jobId),
                  let leaseId = object["lease_id"] as? String, NativeJob.isLeaseID(leaseId),
                  let tool = object["tool"] as? String, self.readyTools.contains(tool),
                  let work = object["work"] as? [String: Any], work["tool"] as? String == tool else { return }
            let leaseSeconds = (object["lease_seconds"] as? Double).flatMap { (30...3600).contains($0) ? $0 : nil } ?? 120
            let heartbeat = (object["heartbeat_seconds"] as? Double).flatMap { (2...600).contains($0) ? $0 : nil } ?? 15
            self.work = work
            self.report = nil
            self.perform(self.lease.handle(.claimed(NativeJob(id: jobId, leaseId: leaseId, leaseSeconds: leaseSeconds,
                                                                 heartbeatSeconds: min(heartbeat, leaseSeconds / 3))),
                                           now: Date()))
        }
    }

    // MARK: Actions

    private func perform(_ actions: [NativeLease.Action]) {
        for action in actions {
            switch action {
            case .launch(let job): launch(job)
            case .heartbeat(let job): heartbeat(job)
            case .terminate: terminate()
            case .finish(let job): finish(job)
            case .forget: forget()
            }
        }
    }

    private func launch(_ job: NativeJob) {
        phase = .running(job.id)
        let tool = NativeTool.named(work?["tool"] as? String) ?? .flye
        runningTool = tool
        let executable = tool.executable
        guard let work, let dataDir else {
            report = NativeReport.notRun(outcome: "refused", code: "work_incomplete", detail: "no work record",
                                         executable: executable, tool: tool.id)
            return perform(lease.handle(.launchFailed, now: Date()))
        }
        if let problem = NativeWorkCheck.problem(work, dataDir: dataDir, executable: executable,
                                                 databaseDirs: databaseDirs) {
            report = NativeReport.notRun(outcome: "refused", code: problem.code, detail: problem.detail,
                                         executable: executable, tool: tool.id)
            return perform(lease.handle(.launchFailed, now: Date()))
        }
        guard let script = NativePaths.bundled(NativePaths.nativeScriptRel) else {
            report = NativeReport.notRun(outcome: "not_started", code: "tool_not_started",
                                         detail: "native.py is missing from ARVA.app", executable: executable,
                                         tool: tool.id)
            return perform(lease.handle(.launchFailed, now: Date()))
        }
        do {
            let file = NativePaths.workDirEnsured.appendingPathComponent("work-\(job.id).json")
            let data = try JSONSerialization.data(withJSONObject: work)
            unlink(file.path)
            let fd = open(file.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
            guard fd >= 0 else { throw CocoaError(.fileWriteNoPermission) }
            let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
            try handle.write(contentsOf: data)
            try handle.close()
            workFile = file
            // Bakta reads its databases only from the database folders of arva.conf (each given to native.py).
            let databases = tool == .bakta ? databaseDirs.flatMap { ["--database-dir", $0] } : []
            let run = try NativeRun(executable: tool.python,
                                    arguments: ["-I", "-B", script.path, tool.id, "run", "--work", file.path,
                                                "--data-dir", dataDir, "--executable", executable] + databases,
                                    environment: NativeCommand.environment(home: AppPaths.home.path),
                                    directory: NativePaths.workDir,
                                    stderrLog: NativePaths.logsDir.appendingPathComponent("run-\(job.id).log"))
            run.onExit = { [weak self, weak run] _, stdout in
                guard let self, let run, self.run === run else { return }
                self.exited(stdout: stdout)
            }
            try run.start()
            self.run = run
        } catch {
            report = NativeReport.notRun(outcome: "not_started", code: "tool_not_started",
                                         detail: error.localizedDescription, executable: executable, tool: tool.id)
            return perform(lease.handle(.launchFailed, now: Date()))
        }
        recordRunning(job)
        perform(lease.handle(.launched, now: Date()))
    }

    /// running.json, with native.py's process tree as it is now (looked up off the main thread).
    private func recordRunning(_ job: NativeJob) {
        guard let run else { return }
        let started = Date()
        DispatchQueue.global(qos: .utility).async {
            let processes = run.snapshot()
            guard run.isRunning else { return }
            NativeRunningRecord(jobId: job.id, leaseId: job.leaseId, startedAt: started, processes: processes).save()
        }
    }

    private func heartbeat(_ job: NativeJob) {
        guard let client else { return }
        var body: [String: Any] = ["executor_id": Self.executorId, "lease_id": job.leaseId]
        if let run, run.isRunning, run.pid > 1 {
            body["pid"] = Int(run.pid)
            recordRunning(job)
        }
        client.post("native/jobs/\(job.id)/heartbeat", body) { [weak self] result in
            guard let self, self.lease.job?.id == job.id else { return }
            let event: NativeLease.Event
            if result.status == 200, let object = result.object {
                event = .heartbeatAnswered(cancel: object["cancel"] as? Bool ?? false)
            } else if result.status == 409 && result.code == "native_lease_lost" {
                event = .heartbeatLost
            } else {
                event = .heartbeatFailed
            }
            self.perform(self.lease.handle(event, now: Date()))
        }
    }

    private func terminate() {
        guard let run, run.isRunning else { return }
        DispatchQueue.global(qos: .userInitiated).async { run.stop(grace: 30) }
    }

    private func exited(stdout: String) {
        if report == nil { report = NativeReport.parse(stdout) }
        let finished = run
        DispatchQueue.global(qos: .utility).async { finished?.cleanup() }
        NativeRunningRecord.clear()
        if let workFile { try? FileManager.default.removeItem(at: workFile) }
        workFile = nil
        perform(lease.handle(.exited(hasReport: report != nil), now: Date()))
    }

    private func finish(_ job: NativeJob) {
        guard let client, let report else {
            return perform(lease.handle(.finishAnswered, now: Date()))
        }
        let body: [String: Any] = ["executor_id": Self.executorId, "lease_id": job.leaseId, "report": report]
        client.post("native/jobs/\(job.id)/finish", body) { [weak self] result in
            guard let self, self.lease.job?.id == job.id else { return }
            // 200: accepted. 409 (already finished, lease lost) and 422 (refused: the job fails with that reason)
            // are final answers too; only no answer, or a server error, is tried again.
            let final = result.status.map { $0 < 500 } ?? false
            self.perform(self.lease.handle(final ? .finishAnswered : .finishFailed, now: Date()))
        }
    }

    private func forget() {
        if let run, run.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { run.stop(grace: 10) }
        }
        run = nil
        work = nil
        report = nil
        if let workFile { try? FileManager.default.removeItem(at: workFile) }
        workFile = nil
        NativeRunningRecord.clear()
        runningTool = nil
        phase = registered && flyeReady ? .ready : (registered ? phase : .waiting(nil))
        if case .running = phase { phase = .waiting(nil) }
        let waiters = idleWaiters
        idleWaiters = []
        for waiter in waiters { waiter() }
        if !NativePaths.anyInstalled { stopTimer() }
    }

    // MARK: Quitting

    /// Stops a running Flye and sends its report ("stopped": the worker keeps Flye's folder for a resume), then calls
    /// `completion` on the main queue (at once when nothing runs; at most about 45 seconds).
    func shutdown(completion: @escaping () -> Void) {
        guard lease.isBusy else {
            stopTimer()
            completion()
            return
        }
        var called = false
        let once = { [weak self] in
            guard !called else { return }
            called = true
            self?.stopTimer()
            completion()
        }
        idleWaiters.append(once)
        perform(lease.handle(.quit, now: Date()))
        DispatchQueue.main.asyncAfter(deadline: .now() + 45) { once() }
    }

    /// The same, waited for, when the app is about to end (applicationWillTerminate): native.py is asked to stop, then
    /// the tree is killed; the report is sent when it came in time.
    func shutdownNow() {
        stopTimer()
        guard let run else {
            NativeRunningRecord.clear()
            return
        }
        let job = lease.job
        _ = lease.handle(.quit, now: Date())
        if run.isRunning, run.pid > 1 {
            run.snapshot()
            kill(run.pid, SIGTERM)
        }
        let output = run.waitForExit(timeout: 15)
        if run.isRunning { ProcessTree.terminate(root: run.pid, grace: 3) }
        run.cleanup()
        let finalReport = report ?? output.flatMap { NativeReport.parse($0.stdout) }
        if let job, let client, let finalReport, lease.sendFinish {
            _ = client.postSync("native/jobs/\(job.id)/finish",
                                ["executor_id": Self.executorId, "lease_id": job.leaseId, "report": finalReport],
                                timeout: 5)
        }
        if let workFile { try? FileManager.default.removeItem(at: workFile) }
        NativeRunningRecord.clear()
        self.run = nil
    }

    // MARK: Texts

    /// The status line shown while Flye or Bakta runs on this Mac (app menu); nil otherwise.
    var statusText: String? {
        if case .running = phase {
            let name = runningTool?.name ?? "Flye"
            return L("\(name) is running on this Mac (native)", "\(name) se está ejecutando en esta Mac (nativo)")
        }
        return nil
    }

    /// The executor's state in one sentence, for the "Flye for This Mac" dialog.
    var phaseText: String {
        switch phase {
        case .off:
            return L("Not started.", "No iniciado.")
        case .noMacFolder:
            return L("ARVA keeps its data in a Docker volume (or its data folder is not reachable now): Flye can run on this Mac only when ARVA's data folder is a folder of this Mac (ARVA → Set Up Again…).",
                     "ARVA guarda sus datos en un volumen de Docker (o su carpeta de datos no está accesible ahora): Flye solo puede ejecutarse en esta Mac cuando la carpeta de datos de ARVA es una carpeta de esta Mac (ARVA → Volver a configurar…).")
        case .waiting(let code):
            return Self.reasonText(code ?? "not_answering")
        case .notReady(let reason):
            return L("Installed, but ARVA cannot use it now: ", "Instalado, pero ARVA no puede usarlo ahora: ") + Self.reasonText(reason)
        case .ready:
            let names = NativeTool.all.filter { readyTools.contains($0.id) }.map(\.name).joined(separator: ", ")
            return L("Ready (\(names)): when Docker has too little memory for one of them, its dialog offers “Run on this Mac (native)”.",
                     "Listo (\(names)): cuando Docker tiene poca memoria para una de ellas, su diálogo ofrece “Ejecutar en esta Mac (nativo)”.")
        case .running:
            let name = runningTool?.name ?? "Flye"
            return L("Running \(name) on this Mac now.", "Ejecutando ahora \(name) en esta Mac.")
        }
    }

    /// The API's readiness reasons (app.services.native.flye_readiness) and the app's own, in words.
    static func reasonText(_ code: String) -> String {
        switch code {
        case "platform_unsupported":
            return L("this Mac is not Apple silicon.", "esta Mac no es Apple silicon.")
        case "unsafe_path":
            return L("the data folder or Flye's path is not a plain absolute path.", "la carpeta de datos o la ruta de Flye no es una ruta absoluta simple.")
        case "path_has_spaces":
            return L("the path of ARVA's data folder contains spaces, which Flye refuses.", "la ruta de la carpeta de datos de ARVA tiene espacios, que Flye rechaza.")
        case "storage_mismatch":
            return L("the data folder this app sees is not the one ARVA's containers use (or it is not ready).", "la carpeta de datos que ve esta aplicación no es la que usan los contenedores de ARVA (o no está lista).")
        case "other_data_dir":
            return L("ARVA was started with another data folder.", "ARVA se inició con otra carpeta de datos.")
        case "lock_mismatch":
            return L("it was installed from another lock than this ARVA's: install it again.", "se instaló desde otro lock que el de este ARVA: vuelve a instalarlo.")
        case "build_mismatch":
            return L("the installed Flye build is not the one ARVA expects: install it again.", "la compilación de Flye instalada no es la que ARVA espera: vuelve a instalarla.")
        case "version_mismatch":
            return L("the installed Flye is not version 2.9.6.", "el Flye instalado no es la versión 2.9.6.")
        case "help_incomplete":
            return L("Flye's --help lacks options ARVA needs.", "al --help de Flye le faltan opciones que ARVA necesita.")
        case "samtools_missing":
            return L("flye-samtools is not beside flye.", "flye-samtools no está junto a flye.")
        case "no_database_folders":
            return L("arva.conf names no database folder (ARVA_DATABASES_DIR, ARVA_ADD_DATABASES): Bakta reads its databases only from those.",
                     "arva.conf no nombra ninguna carpeta de bases de datos (ARVA_DATABASES_DIR, ARVA_ADD_DATABASES): Bakta lee sus bases solo desde ahí.")
        case "tool_mismatch":
            return L("the facts sent for a tool are another tool's (install it again).", "los datos enviados para una herramienta son de otra (vuelve a instalarla).")
        case "native_token_missing":
            return L("ARVA cannot read this app's token: ARVA uses it only when its data is in a folder of this Mac (and was started by this app).",
                     "ARVA no puede leer el token de esta aplicación: ARVA lo usa solo cuando sus datos están en una carpeta de esta Mac (y lo inició esta aplicación).")
        case "native_token_refused":
            return L("ARVA refused this app's token (another ARVA.app may be open).", "ARVA rechazó el token de esta aplicación (puede haber otra ARVA.app abierta).")
        case "token_not_written":
            return L("the token for ARVA could not be written in ~/.config/arva/host.", "no se pudo escribir el token para ARVA en ~/.config/arva/host.")
        case "facts_unreadable":
            return L("the installed Flye could not be checked (install it again).", "no se pudo comprobar el Flye instalado (vuelve a instalarlo).")
        case "not_answering":
            return L("waiting for ARVA to answer.", "esperando a que ARVA responda.")
        default:
            return L("ARVA answered \(code).", "ARVA respondió \(code).")
        }
    }
}
