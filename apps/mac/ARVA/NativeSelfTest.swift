import Foundation

/// The self-test of "Flye for this Mac" (part of `ARVA --self-test`): the bundled files, the lease state machine
/// against a stand-in for the API (its rules as app/services/native.py has them), the path checks, the token, the
/// report, and stopping a fake process tree, the way a cancelled or orphaned Flye is stopped. Nothing is
/// downloaded, no Flye is run and ARVA's API is not called.
enum NativeSelfTest {
    typealias Check = (String, Bool, String) -> Void

    /// Where each check's result goes (SelfTest's own check, which counts the failures).
    private static var sink: Check = { _, _, _ in }

    private static func check(_ name: String, _ ok: Bool, _ detail: String = "") {
        sink(name, ok, detail)
    }

    static func run(_ report: @escaping Check) {
        sink = report
        bundle()
        lease()
        paths()
        workRecord()
        token()
        reports()
        processes()
        texts()
    }

    // MARK: The bundle

    private static func bundle() {
        let fm = FileManager.default
        for rel in NativePaths.bundledFiles {
            check("native: bundled \(rel)", NativePaths.bundled(rel).map { fm.fileExists(atPath: $0.path) } ?? false, "")
        }
        let lockText = NativePaths.bundled(NativePaths.lockRel).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        let pin = NativeLockPin.parse(lockText)
        check("native: the lock pins Flye 2.9.6 for osx-arm64", pin?.version == "2.9.6" && (pin?.build.isEmpty == false),
              String(describing: pin))
        check("native: every line of the lock is an exact package with its sha256",
              lockText.components(separatedBy: "\n").filter { $0.hasPrefix("https://") }.allSatisfy {
                  $0.hasPrefix("https://conda.anaconda.org/") && $0.range(of: "#sha256:[0-9a-f]{64}$", options: .regularExpression) != nil
              } && lockText.contains("@EXPLICIT"), "")
        let help = NativePaths.bundled(NativePaths.helpRel).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        let options = NativeHelp.options(help)
        check("native: Flye 2.9.6's --help options read",
              ["--nano-hq", "--out-dir", "--threads", "--iterations", "--resume", "--genome-size"].allSatisfy(options.contains),
              "\(options.count) options")
        check("native: a word inside another is not an option", NativeHelp.options("x--meta --meta-x a-b --keep") == ["--meta-x", "--keep"],
              "\(NativeHelp.options("x--meta --meta-x a-b --keep"))")
        let script = NativePaths.bundled(NativePaths.micromambaRel).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        check("native: micromamba for osx-arm64 is pinned by its sha256",
              script.range(of: "SUBDIR=\"osx-arm64\"; SHA256=\"[0-9a-f]{64}\"", options: .regularExpression) != nil, "")
        check("native: the environment's path has no spaces (Flye refuses them)",
              !NativeRelPath.hasWhitespace(NativePaths.flye) || NativeRelPath.hasWhitespace(AppPaths.home.path), NativePaths.flye)
        check("native: the token goes where the API reads it",
              NativePaths.tokenFile(environment: ["XDG_CONFIG_HOME": "/tmp/xdg"]).path == "/tmp/xdg/arva/host/native-executor.token",
              NativePaths.tokenFile(environment: ["XDG_CONFIG_HOME": "/tmp/xdg"]).path)

        // The checks made after an installation, on constructed facts.
        let sample = NativeLockPin(version: "2.9.6", build: "py313h05f0e27_1", sha256: String(repeating: "a", count: 64))
        let good = NativeFacts(json: ["tool": "flye", "version": "2.9.6-b1802", "lock_sha256": String(repeating: "b", count: 64),
                                      "package": ["build": "py313h05f0e27_1", "sha256": String(repeating: "a", count: 64)],
                                      "help_options": Array(options), "samtools_helper": true])
        check("native: facts matching the lock and the help pass",
              good.problems(pin: sample, lockSha256: String(repeating: "b", count: 64), helpText: help).isEmpty,
              good.problems(pin: sample, lockSha256: String(repeating: "b", count: 64), helpText: help).joined(separator: "; "))
        var other = good.json
        other["help_options"] = Array(options.subtracting(["--resume"]))
        other["package"] = ["build": "py313h05f0e27_0", "sha256": String(repeating: "c", count: 64)]
        let bad = NativeFacts(json: other).problems(pin: sample, lockSha256: String(repeating: "b", count: 64), helpText: help)
        check("native: another build and a different --help are refused", bad.count == 3, bad.joined(separator: "; "))
        check("native: facts read from native.py's output",
              NativeFacts.parse("warning\n{\"tool\": \"flye\", \"version\": \"2.9.6-b1802\"}\n")?.version == "2.9.6-b1802")
        baktaBundle()
    }

    /// Bakta for this Mac: its lock (Bakta itself is noarch), its --help, and the checks after an installation.
    private static func baktaBundle() {
        let tool = NativeTool.bakta
        let lockText = NativePaths.bundled(tool.lockRel).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        let pin = NativeLockPin.parse(lockText, tool: tool)
        check("native: the lock pins Bakta 1.12.2 (noarch) for osx-arm64", pin?.version == "1.12.2" && pin?.build == "pyhdfd78af_0",
              String(describing: pin))
        check("native: Bakta's lock has DIAMOND, BLAST+ and AMRFinderPlus for osx-arm64",
              ["diamond-2.2.8-", "blast-2.17.0-", "ncbi-amrfinderplus-4.2.7-"].allSatisfy { name in
                  lockText.contains("https://conda.anaconda.org/bioconda/osx-arm64/" + name)
              }, "")
        let help = NativePaths.bundled(tool.helpRel).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        let options = NativeHelp.options(help)
        check("native: Bakta 1.12.2's --help options read",
              ["--db", "--output", "--tmp-dir", "--locus-tag-increment", "--skip-cds"].allSatisfy(options.contains), "\(options.count) options")
        let sample = NativeLockPin(version: "1.12.2", build: "pyhdfd78af_0", sha256: String(repeating: "a", count: 64))
        // native.py bakta facts lists short and long options; only the long ones are compared.
        let good = NativeFacts(json: ["tool": "bakta", "version": "bakta 1.12.2", "lock_sha256": String(repeating: "b", count: 64),
                                      "package": ["build": "pyhdfd78af_0", "sha256": String(repeating: "a", count: 64)],
                                      "help_options": Array(options) + ["-d", "-o"]])
        let problems = good.problems(pin: sample, lockSha256: String(repeating: "b", count: 64), helpText: help, tool: tool)
        check("native: Bakta facts matching the lock and the help pass", problems.isEmpty, problems.joined(separator: "; "))
        var other = good.json
        other["version"] = "bakta 1.11.4"
        let bad = NativeFacts(json: other).problems(pin: sample, lockSha256: String(repeating: "b", count: 64), helpText: help, tool: tool)
        check("native: another Bakta version is refused", bad.count == 1, bad.joined(separator: "; "))
        check("native: Bakta facts read from native.py's output",
              NativeFacts.parse("{\"tool\": \"bakta\", \"version\": \"bakta 1.12.2\"}\n", tool: "bakta")?.version == "bakta 1.12.2"
              && NativeFacts.parse("{\"tool\": \"bakta\"}\n") == nil)
        check("native: Bakta's environment is beside Flye's", tool.executable.hasSuffix("/.arva-tools/conda/bakta/bin/bakta"), tool.executable)
        let config = ArvaConfig.parse("ARVA_DATABASES_DIR=/Volumes/JM/ARVA/databases\nARVA_ADD_DATABASES=/Volumes/JM/BioInf/bakta\nARVA_ADD_DATABASES=relative\n")
        let dirs = NativePaths.databaseDirs(config)
        check("native: the database folders of arva.conf (absolute ones only)",
              dirs == ["/Volumes/JM/ARVA/databases", "/Volumes/JM/BioInf/bakta"], dirs.joined(separator: ", "))
    }

    // MARK: The lease, against a stand-in API

    /// The API's rules (app/services/native.py): one lease per job, created only when none is held (SET NX); it
    /// expires leaseSeconds after the last heartbeat; a heartbeat answers cancel when the user cancelled; the report is
    /// taken once, and only while the lease is held, with the argv the API built.
    final class MockAPI {
        var now = Date(timeIntervalSince1970: 2_000_000_000)
        let leaseSeconds: TimeInterval = 120
        var queue: [String] = []
        var argv: [String: [String]] = [:]
        struct Held {
            var id: String
            var executor: String
            var expires: Date
        }
        var leases: [String: Held] = [:]
        var cancelled: Set<String> = []
        var results: [String: [String: Any]] = [:]
        var heartbeats = 0

        func claim(executor: String) -> NativeJob? {
            for job in queue {
                if let held = leases[job], held.expires > now { continue }
                if cancelled.contains(job) || results[job] != nil { continue }
                let id = UUID().uuidString.lowercased()
                leases[job] = Held(id: id, executor: executor, expires: now.addingTimeInterval(leaseSeconds))
                return NativeJob(id: job, leaseId: id, leaseSeconds: leaseSeconds, heartbeatSeconds: 15)
            }
            return nil
        }

        private func held(_ job: NativeJob, _ executor: String) -> Bool {
            guard let lease = leases[job.id] else { return false }
            return lease.id == job.leaseId && lease.executor == executor && lease.expires > now
        }

        /// nil: 409 native_lease_lost.
        func heartbeat(_ job: NativeJob, executor: String) -> Bool? {
            heartbeats += 1
            guard held(job, executor) else { return nil }
            leases[job.id]?.expires = now.addingTimeInterval(leaseSeconds)
            return cancelled.contains(job.id)
        }

        /// The HTTP status of the finish request.
        func finish(_ job: NativeJob, executor: String, report: [String: Any]) -> Int {
            guard held(job, executor) else { return 409 }
            guard results[job.id] == nil else { return 409 }
            let ran = ["exited", "stopped"].contains(report["outcome"] as? String ?? "")
            if ran, report["argv"] as? [String] != argv[job.id] {
                results[job.id] = ["outcome": "rejected"]
                return 422
            }
            results[job.id] = report
            return 200
        }
    }

    /// A stand-in for native.py: started, then it exits with a report (on its own or when asked to stop).
    final class Driver {
        let api: MockAPI
        let executor: String
        var lease = NativeLease()
        var processRunning = false
        var launches = 0
        var terminations = 0
        var finishes = 0
        var networkDown = false
        var launchFails = false
        var reportFor: (Bool) -> [String: Any]   // stopped?
        private var report: [String: Any]?

        init(api: MockAPI, executor: String, report: @escaping (Bool) -> [String: Any]) {
            self.api = api
            self.executor = executor
            self.reportFor = report
        }

        func send(_ event: NativeLease.Event) {
            var pending = [event]
            while !pending.isEmpty {
                let next = pending.removeFirst()
                for action in lease.handle(next, now: api.now) {
                    pending += perform(action)
                }
            }
        }

        private func perform(_ action: NativeLease.Action) -> [NativeLease.Event] {
            switch action {
            case .launch:
                launches += 1
                if launchFails {
                    report = NativeReport.notRun(outcome: "not_started", code: "tool_not_started", detail: "test", executable: "/x/bin/flye")
                    return [.launchFailed]
                }
                processRunning = true
                return [.launched]
            case .heartbeat(let job):
                if networkDown { return [.heartbeatFailed] }
                switch api.heartbeat(job, executor: executor) {
                case .none: return [.heartbeatLost]
                case .some(let cancel): return [.heartbeatAnswered(cancel: cancel)]
                }
            case .terminate:
                terminations += 1
                guard processRunning else { return [] }
                processRunning = false
                report = reportFor(true)
                return [.exited(hasReport: true)]
            case .finish(let job):
                finishes += 1
                if networkDown { return [.finishFailed] }
                guard let report else { return [.finishAnswered] }
                _ = api.finish(job, executor: executor, report: report)
                return [.finishAnswered]
            case .forget:
                report = nil
                return []
            }
        }

        /// native.py ends on its own (Flye finished).
        func processExits() {
            guard processRunning else { return }
            processRunning = false
            report = reportFor(false)
            send(.exited(hasReport: true))
        }

        /// The executor's one-second loop, for `seconds` seconds of the stand-in's clock.
        func advance(_ seconds: Int) {
            for _ in 0..<seconds {
                api.now = api.now.addingTimeInterval(1)
                send(.tick)
            }
        }
    }

    private static func lease() {
        let argv = ["/Users/x/.arva-tools/conda/flye/bin/flye", "--nano-hq", "/Volumes/JM/ARVA/data/r/01.fastq.gz"]
        func report(stopped: Bool, ran: [String]) -> [String: Any] {
            ["tool": "flye", "outcome": stopped ? "stopped" : "exited", "exit_code": stopped ? -15 : 0, "argv": ran,
             "executable": ran[0], "outputs": [String]()]
        }

        // A run that ends on its own: claimed, heartbeats, report accepted once.
        let api = MockAPI()
        api.queue = ["job-1"]
        api.argv["job-1"] = argv
        let app = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        guard let job = api.claim(executor: "mac-1") else {
            check("lease: the stand-in hands out a waiting job", false, "")
            return
        }
        check("lease: a second claim of the same job gets nothing while the lease is held (SET NX)",
              api.claim(executor: "mac-2") == nil, "")
        app.send(.claimed(job))
        check("lease: claimed → native.py started, first heartbeat at once",
              app.lease.state == .running && app.launches == 1 && api.heartbeats == 1, "\(app.lease.state)")
        app.advance(14)
        check("lease: no heartbeat before heartbeat_seconds", api.heartbeats == 1, "\(api.heartbeats)")
        app.advance(1)
        check("lease: a heartbeat every heartbeat_seconds", api.heartbeats == 2, "\(api.heartbeats)")
        app.advance(300)
        check("lease: the lease is renewed while Flye runs (5 minutes)", app.lease.state == .running
              && (api.leases["job-1"]?.expires ?? .distantPast) > api.now, "")
        app.processExits()
        check("lease: Flye ended: its report was sent and accepted", app.lease.state == .idle && app.finishes == 1
              && api.results["job-1"]?["outcome"] as? String == "exited", "\(app.lease.state)")
        check("lease: a finished job is not claimed again", api.claim(executor: "mac-1") == nil, "")
        check("lease: nothing more is sent once idle", { () -> Bool in
            let before = api.heartbeats
            app.advance(60)
            return api.heartbeats == before
        }(), "")

        // The user cancels: the next heartbeat says so, Flye is stopped, its "stopped" report is sent.
        api.queue = ["job-2"]
        api.argv["job-2"] = argv
        let cancelling = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        if let job2 = api.claim(executor: "mac-1") {
            cancelling.send(.claimed(job2))
            cancelling.advance(20)
            api.cancelled.insert("job-2")
            cancelling.advance(15)
            check("lease: cancel → Flye stopped, report \"stopped\" accepted",
                  cancelling.terminations == 1 && cancelling.lease.state == .idle
                  && api.results["job-2"]?["outcome"] as? String == "stopped", "\(cancelling.lease.state)")
        } else {
            check("lease: cancel", false, "no job")
        }

        // The lease lost (the app was too slow: the API's lease expired): Flye is killed and nothing more is sent.
        api.queue = ["job-3"]
        api.argv["job-3"] = argv
        let late = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        if let job3 = api.claim(executor: "mac-1") {
            late.send(.claimed(job3))
            api.leases["job-3"]?.expires = api.now   // expired on the API's side
            late.advance(16)
            check("lease: 409 native_lease_lost → Flye killed, no report sent",
                  late.terminations == 1 && late.finishes == 0 && late.lease.state == .idle && api.results["job-3"] == nil,
                  "\(late.lease.state), finishes \(late.finishes)")
        } else {
            check("lease: lost", false, "no job")
        }

        // ARVA stops answering: after lease_seconds without a successful heartbeat the API's lease has expired too, so
        // Flye is killed, and nothing is sent.
        api.queue = ["job-4"]
        api.argv["job-4"] = argv
        let offline = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        if let job4 = api.claim(executor: "mac-1") {
            offline.send(.claimed(job4))
            offline.networkDown = true
            offline.advance(119)
            check("lease: ARVA briefly not answering: Flye keeps running", offline.lease.state == .running
                  && offline.terminations == 0, "\(offline.lease.state)")
            offline.advance(2)
            check("lease: no answer for lease_seconds → Flye killed, nothing sent",
                  offline.terminations == 1 && offline.finishes == 0 && offline.lease.state == .idle, "\(offline.lease.state)")
        } else {
            check("lease: offline", false, "no job")
        }

        // Quitting the app: Flye stopped, its report sent ("stopped": the worker keeps the folder for a resume).
        api.queue = ["job-5"]
        api.argv["job-5"] = argv
        let quitting = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        if let job5 = api.claim(executor: "mac-1") {
            quitting.send(.claimed(job5))
            quitting.advance(5)
            quitting.send(.quit)
            check("lease: quit → Flye stopped and its report sent",
                  quitting.terminations == 1 && quitting.lease.state == .idle
                  && api.results["job-5"]?["outcome"] as? String == "stopped", "\(quitting.lease.state)")
        } else {
            check("lease: quit", false, "no job")
        }

        // native.py could not start: a "not_started" report, accepted.
        api.queue = ["job-6"]
        let failing = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv) }
        failing.launchFails = true
        if let job6 = api.claim(executor: "mac-1") {
            failing.send(.claimed(job6))
            check("lease: nothing could start → report \"not_started\"", failing.lease.state == .idle
                  && api.results["job-6"]?["outcome"] as? String == "not_started", "\(failing.lease.state)")
        } else {
            check("lease: not started", false, "no job")
        }

        // A report whose argv is not the API's is refused (the job then fails with native_argv_mismatch).
        api.queue = ["job-7"]
        api.argv["job-7"] = argv
        let other = Driver(api: api, executor: "mac-1") { report(stopped: $0, ran: argv + ["--meta"]) }
        if let job7 = api.claim(executor: "mac-1") {
            other.send(.claimed(job7))
            other.processExits()
            check("lease: another argv is refused by the API, and not sent twice",
                  api.results["job-7"]?["outcome"] as? String == "rejected" && other.finishes == 1 && other.lease.state == .idle, "")
        } else {
            check("lease: argv", false, "no job")
        }

        // The report cannot be sent at once: tried again, then given up once the lease cannot be held.
        var machine = NativeLease()
        let t0 = Date(timeIntervalSince1970: 0)
        let job8 = NativeJob(id: "job-8", leaseId: UUID().uuidString.lowercased(), leaseSeconds: 120, heartbeatSeconds: 15)
        _ = machine.handle(.claimed(job8), now: t0)
        _ = machine.handle(.launched, now: t0)
        _ = machine.handle(.heartbeatAnswered(cancel: false), now: t0)
        let first = machine.handle(.exited(hasReport: true), now: t0)
        _ = machine.handle(.finishFailed, now: t0)
        let retry = machine.handle(.tick, now: t0.addingTimeInterval(NativeLease.finishRetrySeconds + 1))
        check("lease: a report that did not get through is sent again", first == [.finish(job8)]
              && retry.contains(.finish(job8)), "\(retry)")
        _ = machine.handle(.finishFailed, now: t0.addingTimeInterval(7))
        let gaveUp = machine.handle(.tick, now: t0.addingTimeInterval(200))
        check("lease: and given up once the lease has expired", machine.state == .idle && gaveUp.contains(.forget), "\(gaveUp)")

        check("lease: job and lease identifiers checked",
              NativeJob.isJobID("0b0f7c1e-0000-4000-8000-000000000001") && !NativeJob.isJobID("../x")
              && !NativeJob.isJobID("") && NativeJob.isLeaseID(UUID().uuidString.lowercased()) && !NativeJob.isLeaseID("x"), "")
    }

    // MARK: Paths

    private static func paths() {
        let scope = "results/0b0f7c1e-0000-4000-8000-000000000001/_project/0b0f7c1e-0000-4000-8000-000000000002"
        for rel in ["../outside.fastq.gz", "/etc/passwd", "\(scope)/../x", "\(scope)//x", "", ".", "\(scope)/", "a b",
                    "x\ny", "-flag", "\(scope)/./x", "~/x", "a/.hidden"] {
            check("paths: refused \(rel.debugDescription)", !NativeRelPath.isSafe(rel), "")
        }
        for rel in ["\(scope)/input/01_reads.fastq.gz", "\(scope)/flye", "raw/r.fq"] {
            check("paths: accepted \(rel.prefix(50))", NativeRelPath.isSafe(rel), "")
        }
        for (dir, ok) in [("/Volumes/JM/ARVA/data", true), ("/Users/x/ARVA", true), ("/", false), ("relative", false),
                          ("/Volumes/JM/", false), ("/Volumes//JM", false), ("/Volumes/JM/../x", false), ("/a/./b", false)] {
            check("paths: data folder \(dir)", NativeRelPath.isNormalisedAbsolute(dir) == ok, "")
        }
        check("paths: spaces are seen", NativeRelPath.hasWhitespace("/Volumes/Lab Disk") && !NativeRelPath.hasWhitespace("/Volumes/JM"), "")

        // A data folder with a stored read, a link to it, and links that lead outside.
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("arva-native-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: temp) }
        let data = temp.appendingPathComponent("data", isDirectory: true)
        let outside = temp.appendingPathComponent("elsewhere", isDirectory: true)
        do {
            try fm.createDirectory(at: data.appendingPathComponent("raw"), withIntermediateDirectories: true)
            try fm.createDirectory(at: data.appendingPathComponent("job/input"), withIntermediateDirectories: true)
            try fm.createDirectory(at: outside, withIntermediateDirectories: true)
            try Data("reads".utf8).write(to: data.appendingPathComponent("raw/r.fastq.gz"))
            try Data("secret".utf8).write(to: outside.appendingPathComponent("s.fastq.gz"))
            try fm.createSymbolicLink(atPath: data.appendingPathComponent("job/input/01_r.fastq.gz").path,
                                      withDestinationPath: "../../raw/r.fastq.gz")
            try fm.createSymbolicLink(atPath: data.appendingPathComponent("job/input/02_s.fastq.gz").path,
                                      withDestinationPath: outside.appendingPathComponent("s.fastq.gz").path)
            try fm.createSymbolicLink(atPath: data.appendingPathComponent("job/escape").path, withDestinationPath: outside.path)
            let root = data.path
            check("paths: a relative link to a stored read stays inside", NativeRelPath.check("job/input/01_r.fastq.gz", in: root) == nil, "")
            check("paths: a link that leads outside is refused",
                  NativeRelPath.check("job/input/02_s.fastq.gz", in: root) == .outside, "")
            check("paths: a folder link that leads outside is refused",
                  NativeRelPath.check("job/escape/s.fastq.gz", in: root) == .outside, "")
            check("paths: Flye's folder may not exist yet", NativeRelPath.check("job/flye", in: root, mustExist: false) == nil, "")
            check("paths: but not under a link that leads outside",
                  NativeRelPath.check("job/escape/flye", in: root, mustExist: false) == .outside, "")
            check("paths: a missing read", NativeRelPath.check("job/input/03_x.fastq.gz", in: root) == .missing, "")
            check("paths: '..' never reaches the disk", NativeRelPath.check("job/../../elsewhere/s.fastq.gz", in: root) == .unsafe, "")
        } catch {
            check("paths: test folder", false, error.localizedDescription)
        }
    }

    private static func workRecord() {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("arva-native-work-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: temp) }
        let data = temp.appendingPathComponent("data", isDirectory: true)
        let exe = "/Users/x/.arva-tools/conda/flye/bin/flye"
        do {
            try fm.createDirectory(at: data.appendingPathComponent("results/j/input"), withIntermediateDirectories: true)
            try Data("r".utf8).write(to: data.appendingPathComponent("results/j/input/01_r.fastq.gz"))
        } catch {
            check("work: test folder", false, error.localizedDescription)
            return
        }
        let base: [String: Any] = [
            "tool": "flye", "storage_id": UUID().uuidString.lowercased(), "data_dir": data.path, "executable": exe,
            "params": ["read_type": "nano-hq"], "reads": ["results/j/input/01_r.fastq.gz"], "out_dir": "results/j/flye",
            "results_dir": "results/j", "stderr_log": "flye.stderr.log", "resume": false, "argv": [exe],
        ]
        func code(_ changes: [String: Any], dataDir: String? = nil, executable: String = exe) -> String? {
            var work = base
            for (k, v) in changes { work[k] = v }
            return NativeWorkCheck.problem(work, dataDir: dataDir ?? data.path, executable: executable)?.code
        }
        check("work: a well-formed record passes", code([:]) == nil, code([:]) ?? "")
        check("work: another tool", code(["tool": "prokka"]) == "not_flye_work", "")
        check("work: another data folder", code([:], dataDir: "/Volumes/Other/data") == "other_data_dir", "")
        check("work: another executable", code([:], executable: "/usr/local/bin/flye") == "other_executable", "")
        check("work: a read path with '..'", code(["reads": ["results/j/../../etc/passwd"]]) == "unsafe_path", "")
        check("work: an absolute read path", code(["reads": ["/etc/passwd"]]) == "unsafe_path", "")
        check("work: a missing read", code(["reads": ["results/j/input/02_x.fastq.gz"]]) == "input_missing", "")
        check("work: Flye's folder outside the job's", code(["out_dir": "results/other/flye"]) == "unsafe_path", "")
        check("work: another log name", code(["stderr_log": "../x.log"]) == "unsafe_path", "")
        check("work: a field missing", code(["argv": "flye --nano-hq"]) == "work_incomplete", "")
        baktaWorkRecord()
    }

    /// Bakta's work record: the job's files in the data folder, the database (and AMRFinderPlus data) as a folder of
    /// arva.conf and a path inside it (arva_tools.bakta.native_database).
    private static func baktaWorkRecord() {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("arva-native-bakta-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: temp) }
        let data = temp.appendingPathComponent("data", isDirectory: true).path
        let databases = temp.appendingPathComponent("databases", isDirectory: true).path
        let exe = "/Users/x/.arva-tools/conda/bakta/bin/bakta"
        do {
            try fm.createDirectory(atPath: data + "/results/j/input", withIntermediateDirectories: true)
            try fm.createDirectory(atPath: data + "/results/j/bakta-tmp", withIntermediateDirectories: true)
            try Data(">c\nACGT\n".utf8).write(to: URL(fileURLWithPath: data + "/results/j/input/genome.fna"))
            try fm.createDirectory(atPath: databases + "/bakta-full/6.0", withIntermediateDirectories: true)
            try fm.createDirectory(atPath: temp.appendingPathComponent("elsewhere").path, withIntermediateDirectories: true)
            try fm.createSymbolicLink(atPath: databases + "/escape", withDestinationPath: temp.appendingPathComponent("elsewhere").path)
        } catch {
            check("bakta work: test folder", false, error.localizedDescription)
            return
        }
        let base: [String: Any] = [
            "tool": "bakta", "storage_id": UUID().uuidString.lowercased(), "data_dir": data, "executable": exe,
            "params": ["locus_tag": "S27"], "genome": "results/j/input/genome.fna", "out_dir": "results/j/bakta",
            "tmp_dir": "results/j/bakta-tmp", "results_dir": "results/j", "console_log": "bakta.console.log",
            "database": ["root": databases, "rel": "bakta-full/6.0"], "amr_data": NSNull(), "database_type": "full",
            "skip_options": [String](), "argv": [exe],
        ]
        func code(_ changes: [String: Any], dirs: [String]? = nil) -> String? {
            var work = base
            for (k, v) in changes { work[k] = v }
            return NativeWorkCheck.problem(work, dataDir: data, executable: exe, databaseDirs: dirs ?? [databases])?.code
        }
        check("bakta work: a well-formed record passes", code([:]) == nil, code([:]) ?? "")
        check("bakta work: a database folder arva.conf does not name", code([:], dirs: ["/Volumes/Other/db"]) == "database_folder_unknown", "")
        check("bakta work: a database path with '..'", code(["database": ["root": databases, "rel": "../data"]]) == "unsafe_path", "")
        check("bakta work: a database link leading outside", code(["database": ["root": databases, "rel": "escape"]]) == "outside_database_dir", "")
        check("bakta work: a missing database", code(["database": ["root": databases, "rel": "bakta-full/5.1"]]) == "input_missing", "")
        check("bakta work: the out-dir outside the job's folder", code(["out_dir": "results/other/bakta"]) == "unsafe_path", "")
        check("bakta work: another log name", code(["console_log": "../x.log"]) == "unsafe_path", "")
        check("bakta work: another executable", NativeWorkCheck.problem(base, dataDir: data, executable: "/usr/local/bin/bakta",
                                                                       databaseDirs: [databases])?.code == "other_executable", "")
        check("bakta work: a field missing", code(["skip_options": "--skip-cds"]) == "work_incomplete", "")
    }

    // MARK: Token, reports, requests

    private static func token() {
        let a = NativeToken.make()
        check("token: 43 characters of base64url", a.count == 43 && NativeToken.isValid(a), a.count.description)
        check("token: a new one each time", NativeToken.make() != a, "")
        check("token: the API's rule", !NativeToken.isValid("short") && !NativeToken.isValid(String(repeating: "a", count: 40) + "+/="), "")
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("arva-token-\(UUID().uuidString)/host", isDirectory: true)
        defer { try? fm.removeItem(at: dir.deletingLastPathComponent()) }
        let file = dir.appendingPathComponent("native-executor.token")
        do {
            try NativeToken.write(a, to: file)
            let b = NativeToken.make()
            try NativeToken.write(b, to: file)
            let mode = (try fm.attributesOfItem(atPath: file.path)[.posixPermissions] as? NSNumber)?.intValue ?? 0
            let text = try String(contentsOf: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            check("token: written for this user only (0600)", mode == 0o600, String(mode, radix: 8))
            check("token: replaced by the new one", text == b, "")
            check("token: no temporary file left", (try fm.contentsOfDirectory(atPath: dir.path)) == ["native-executor.token"], "")
        } catch {
            check("token: written", false, error.localizedDescription)
        }
    }

    private static func reports() {
        let long = String(repeating: "x", count: 5000)
        let line = "{\"tool\": \"flye\", \"outcome\": \"stopped\", \"exit_code\": -15, \"argv\": [\"f\"], \"executable\": \"f\", \"detail\": \"\(long)\"}"
        let parsed = NativeReport.parse("Traceback? no\n" + line + "\n")
        check("report: the last JSON line of native.py", parsed?["outcome"] as? String == "stopped", "")
        check("report: a long detail is shortened to the API's limit", ((parsed?["detail"] as? String)?.count ?? 9999) <= 2000, "")
        check("report: nothing when native.py printed none", NativeReport.parse("Traceback (most recent call last):\n") == nil, "")
        let refused = NativeReport.notRun(outcome: "refused", code: "unsafe_path", detail: "x", executable: "/x/bin/flye")
        check("report: a refusal here carries no argv", refused["argv"] is NSNull && refused["outcome"] as? String == "refused"
              && JSONSerialization.isValidJSONObject(refused), "")
        let request = NativeAPIClient.request("native/jobs/abc-1/heartbeat", body: ["executor_id": "e1234567", "lease_id": "x"],
                                              token: "tok")
        check("api: heartbeat request", request?.url?.absoluteString == "http://localhost:8080/api/v1/native/jobs/abc-1/heartbeat"
              && request?.httpMethod == "POST" && request?.value(forHTTPHeaderField: "Authorization") == "Bearer tok"
              && request?.value(forHTTPHeaderField: "Content-Type") == "application/json",
              request?.url?.absoluteString ?? "none")
        check("api: only the native endpoints", NativeAPIClient.request("dashboard", body: [:], token: "t") == nil
              && NativeAPIClient.request("native/../projects", body: [:], token: "t") == nil
              && NativeAPIClient.request("native/x?y=1", body: [:], token: "t") == nil, "")
    }

    // MARK: Processes

    private static func processes() {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("arva-native-proc-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: temp) }
        try? fm.createDirectory(at: temp, withIntermediateDirectories: true)
        let env = ["PATH": "/usr/bin:/bin"]

        // A stand-in for native.py that answers SIGTERM like it: it stops its children and prints a "stopped" report.
        let polite = """
        sleep 61 & child=$!
        trap 'kill $child; printf "%s\\n" "{\\"tool\\": \\"flye\\", \\"outcome\\": \\"stopped\\", \\"code\\": \\"stopped_by_app\\"}"; exit 0' TERM
        wait
        """
        do {
            let run = try NativeRun(executable: "/bin/sh", arguments: ["-c", polite], environment: env, directory: temp,
                                    stderrLog: temp.appendingPathComponent("polite.log"))
            try run.start()
            Thread.sleep(forTimeInterval: 1)
            let tree = run.snapshot()
            check("process: native.py's tree recorded", tree.count >= 2 && tree.first?.pid == run.pid, "\(tree.count)")
            run.stop(grace: 10)
            let out = run.waitForExit(timeout: 5)
            check("process: SIGTERM → a \"stopped\" report", out.flatMap { NativeReport.parse($0.stdout) }?["outcome"] as? String == "stopped",
                  out?.stdout ?? "did not exit")
            Thread.sleep(forTimeInterval: 0.5)
            check("process: its children are gone", !tree.contains { ProcessTree.isAlive($0.pid) }, "")
        } catch {
            check("process: polite stand-in", false, error.localizedDescription)
        }

        // One that ignores SIGTERM, with grandchildren in their own process group (as Flye's are): killed all the same.
        let stubborn = """
        trap '' TERM
        sh -c 'trap "" TERM; sleep 62 & sleep 62 & wait' &
        set -m 2>/dev/null; sleep 63 &
        wait
        """
        do {
            let run = try NativeRun(executable: "/bin/sh", arguments: ["-c", stubborn], environment: env, directory: temp,
                                    stderrLog: temp.appendingPathComponent("stubborn.log"))
            try run.start()
            Thread.sleep(forTimeInterval: 1)
            let tree = run.snapshot()
            check("process: a tree that ignores SIGTERM is recorded", tree.count >= 4, "\(tree.count)")
            run.stop(grace: 1)
            Thread.sleep(forTimeInterval: 0.5)
            check("process: and killed, all of it", !run.isRunning && !tree.contains { ProcessTree.isAlive($0.pid) },
                  tree.filter { ProcessTree.isAlive($0.pid) }.map(\.command).joined(separator: ", "))
        } catch {
            check("process: stubborn stand-in", false, error.localizedDescription)
        }

        // Orphans: a record left by an app that crashed. Only processes that still run the recorded command, and look
        // like a native run (`markers`), are killed.
        let orphan = Process()
        orphan.executableURL = URL(fileURLWithPath: "/bin/sleep")
        orphan.arguments = ["64"]
        let bystander = Process()
        bystander.executableURL = URL(fileURLWithPath: "/bin/sleep")
        bystander.arguments = ["65"]
        do {
            try orphan.run()
            try bystander.run()
            Thread.sleep(forTimeInterval: 0.3)
            let table = NativeProcesses.table()
            let orphanCommand = table[orphan.processIdentifier]?.command ?? ""
            check("orphans: commands read with ps", orphanCommand.contains("sleep 64"), orphanCommand)
            let recordURL = temp.appendingPathComponent("running.json")
            let record = NativeRunningRecord(jobId: "job-1", leaseId: UUID().uuidString.lowercased(),
                                             startedAt: Date(timeIntervalSince1970: 2_000_000_000),
                                             processes: [NativeProcessEntry(pid: orphan.processIdentifier, command: orphanCommand),
                                                         NativeProcessEntry(pid: bystander.processIdentifier, command: "/bin/sleep 99")])
            record.save(to: recordURL)
            check("orphans: the record is read back", NativeRunningRecord.load(from: recordURL) == record, "")
            let killed = NativeRunningRecord.killOrphans(at: recordURL, markers: ["sleep 64"])
            orphan.waitUntilExit()
            check("orphans: the recorded process is killed", killed == 1 && !orphan.isRunning, "\(killed)")
            check("orphans: a process whose command differs is left alone", bystander.isRunning, "")
            check("orphans: the record is removed", !fm.fileExists(atPath: recordURL.path), "")
            check("orphans: nothing recorded, nothing killed", NativeRunningRecord.killOrphans(at: recordURL) == 0, "")
            let real = NativeRunningRecord(jobId: "j", leaseId: "l", startedAt: Date(),
                                           processes: [NativeProcessEntry(pid: bystander.processIdentifier, command: "/bin/sleep 65")])
            real.save(to: recordURL)
            check("orphans: the app's markers never match another program",
                  NativeRunningRecord.killOrphans(at: recordURL) == 0 && bystander.isRunning, "")
        } catch {
            check("orphans: stand-ins", false, error.localizedDescription)
        }
        if bystander.isRunning { bystander.terminate() }
        if orphan.isRunning { orphan.terminate() }
    }

    private static func texts() {
        for code in ["platform_unsupported", "unsafe_path", "path_has_spaces", "storage_mismatch", "other_data_dir",
                     "lock_mismatch", "build_mismatch", "version_mismatch", "help_incomplete", "samtools_missing",
                     "native_token_missing", "native_token_refused", "not_answering"] {
            let text = NativeExecutor.reasonText(code)
            check("native text: \(code)", !text.isEmpty && !text.contains(code), text)
        }
        check("native text: menu item in the app's language",
              NativeFlyeUI.menuTitle == (Lang.isSpanish ? "Flye para esta Mac…" : "Flye for This Mac…"), NativeFlyeUI.menuTitle)
    }
}
