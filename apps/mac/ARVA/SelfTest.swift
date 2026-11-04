import AppKit
import Foundation
import IOKit.pwr_mgt
import UniformTypeIdentifiers

/// `ARVA --self-test`: checks the app without opening a window or touching Docker, the saved locations or the
/// runtime folder (run by .github/workflows/mac-app.yml on the built app). Prints one line per check, then exits 0
/// when every check passed. Paths are not printed.
enum SelfTest {
    private static var failures = 0

    private static func check(_ name: String, _ ok: Bool, _ detail: String = "") {
        if ok {
            print("ok - \(name)")
        } else {
            failures += 1
            print("not ok - \(name)\(detail.isEmpty ? "" : ": \(detail)")")
        }
    }

    static func run() -> Int32 {
        let fm = FileManager.default
        print("ARVA self-test: \(AppInfo.summary), language \(Lang.code)")

        // The bundle.
        guard let runtime = AppPaths.bundledRuntime, fm.fileExists(atPath: runtime.path) else {
            check("bundle has Resources/runtime", false)
            return 1
        }
        check("bundle has Resources/runtime", true)
        let files = RuntimeSync.bundledFiles(runtime)
        for required in RuntimeSync.requiredFiles {
            check("bundled \(required)", files.contains(required))
        }
        check("bundled runtime id", (try? RuntimeSync.bundledID(runtime)) != nil)
        let resources = Bundle.main.resourceURL
        check("icon ARVA.icns", resources.map { fm.fileExists(atPath: $0.appendingPathComponent("ARVA.icns").path) } ?? false)
        check("logo arva-logo.png", resources.map { fm.fileExists(atPath: $0.appendingPathComponent("arva-logo.png").path) } ?? false)
        // Drawn from the 1254 px logo (docs/brand/arva-logo-1254.png): sharp up to 512@2x.
        let iconSizes = resources.flatMap { NSImage(contentsOf: $0.appendingPathComponent("ARVA.icns")) }?
            .representations.map { $0.pixelsWide } ?? []
        check("icon has its 1024 px size (512@2x)", (iconSizes.max() ?? 0) >= 1024, "\(iconSizes)")
        let logoWidth = resources.flatMap { NSImage(contentsOf: $0.appendingPathComponent("arva-logo.png")) }?
            .representations.first?.pixelsWide ?? 0
        check("logo is the high-resolution one", logoWidth >= 1024, "\(logoWidth)")
        let version = RuntimeSync.version(in: runtime)
        check("ARVA version matches the app's", version != nil && version == AppInfo.version,
              "\(version ?? "none") vs \(AppInfo.version)")
        check("bundle identifier", Bundle.main.bundleIdentifier == "org.arva.ARVA", Bundle.main.bundleIdentifier ?? "none")
        let compose = (try? String(contentsOf: runtime.appendingPathComponent("docker-compose.yml"), encoding: .utf8)) ?? ""
        check("compose project is named arva", compose.components(separatedBy: "\n").contains("name: arva"))
        for script in files where script.hasSuffix(".sh") || script.hasSuffix(".command") {
            let result = ShellTask.run("/bin/sh", ["-n", runtime.appendingPathComponent(script).path], timeout: 20)
            check("sh -n \(script)", result?.status == 0, result?.output ?? "did not run")
        }

        // Syncing into a runtime folder (a temporary one): copies, then nothing to do, keeps other files.
        let temp = fm.temporaryDirectory.appendingPathComponent("arva-selftest-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: temp) }
        do {
            check("first sync copies", try RuntimeSync.sync(from: runtime, to: temp))
            check("second sync has nothing to do", try !RuntimeSync.sync(from: runtime, to: temp))
            let start = temp.appendingPathComponent("scripts/start.sh").path
            let mode = (try fm.attributesOfItem(atPath: start)[.posixPermissions] as? NSNumber)?.intValue ?? 0
            check("start.sh is executable", mode == 0o755, String(mode, radix: 8))
            let userFile = temp.appendingPathComponent("import/run-01/reads.fastq")
            try fm.createDirectory(at: userFile.deletingLastPathComponent(), withIntermediateDirectories: true)
            try "@r1\nACGT\n+\nIIII\n".write(to: userFile, atomically: true, encoding: .utf8)
            let obsolete = temp.appendingPathComponent("scripts/obsolete.sh")
            try "#!/bin/sh\n".write(to: obsolete, atomically: true, encoding: .utf8)
            let outside = temp.deletingLastPathComponent().appendingPathComponent("arva-selftest-outside-\(UUID().uuidString)")
            try "keep".write(to: outside, atomically: true, encoding: .utf8)
            defer { try? fm.removeItem(at: outside) }
            let manifest = temp.appendingPathComponent(RuntimeSync.manifestFile)
            let listed = try String(contentsOf: manifest, encoding: .utf8)
            try (listed + "scripts/obsolete.sh\n../\(outside.lastPathComponent)\n").write(to: manifest, atomically: true, encoding: .utf8)
            try "older build\n".write(to: temp.appendingPathComponent(RuntimeSync.idFile), atomically: true, encoding: .utf8)
            try "changed\n".write(to: temp.appendingPathComponent("scripts/stop.sh"), atomically: true, encoding: .utf8)
            check("a new build syncs again", try RuntimeSync.sync(from: runtime, to: temp))
            check("user files in import/ are kept", fm.fileExists(atPath: userFile.path))
            check("files the app no longer ships are removed", !fm.fileExists(atPath: obsolete.path))
            check("nothing outside the runtime folder is removed", fm.fileExists(atPath: outside.path))
            let stop = try Data(contentsOf: temp.appendingPathComponent("scripts/stop.sh"))
            check("changed launcher files are replaced", stop == (try Data(contentsOf: runtime.appendingPathComponent("scripts/stop.sh"))))

            // The synced launcher runs from there: its own help, in both languages.
            for lang in ["en_US.UTF-8", "es_ES.UTF-8"] {
                var env = ShellEnvironment.make()
                env["LANG"] = lang
                let help = ShellTask.run("/bin/sh", ["scripts/start.sh", "--help"], directory: temp, environment: env, timeout: 30)
                let word = lang.hasPrefix("es") ? "Uso:" : "Usage:"
                check("start.sh --help (\(lang))", help?.status == 0 && (help?.output.contains(word) ?? false),
                      String((help?.output ?? "did not run").prefix(400)))
            }

            // The first-run command.
            let command = try FirstRunCommand.write(in: temp)
            let text = try String(contentsOf: command, encoding: .utf8)
            check("first-run command runs start.sh --setup", text.contains("sh scripts/start.sh --setup"))
            check("first-run command names the compose project", text.contains("COMPOSE_PROJECT_NAME=arva"))
            check("first-run command puts the app's stand-ins first", text.contains("PATH=" + shellQuote(AppPaths.shimDir.path) + ":"))
            check("first-run command keeps a log", text.contains("/usr/bin/script -q " + FirstRunCommand.logFile))
            check("first-run command tells a declined setup apart", text.contains("status=declined"))
            check("first-run command records an interruption", text.contains("interrupted") && text.contains("INT HUP TERM"))
            let syntax = ShellTask.run("/bin/sh", ["-n", command.path], timeout: 20)
            check("first-run command syntax", syntax?.status == 0, syntax?.output ?? "")
            check("first-run status is unknown while it runs", FirstRunCommand.status(in: temp) == nil)
            check("first-run process unknown before it starts", FirstRunCommand.isRunning(in: temp) == nil)
            let statusURL = temp.appendingPathComponent(FirstRunCommand.statusFile)
            for (written, expected) in [("3\n", FirstRunCommand.Status.failed(3)), ("0\n", .succeeded),
                                        ("declined\n", .declined), ("interrupted\n", .interrupted)] {
                try written.write(to: statusURL, atomically: true, encoding: .utf8)
                check("first-run status \(written.trimmingCharacters(in: .whitespacesAndNewlines)) is read",
                      FirstRunCommand.status(in: temp) == expected)
            }
            // A process id that is not the first-run command is never trusted (nor stopped).
            try "\(ProcessInfo.processInfo.processIdentifier)\n".write(to: temp.appendingPathComponent(FirstRunCommand.pidFile),
                                                                       atomically: true, encoding: .utf8)
            check("first-run process id of another program is not trusted", FirstRunCommand.isRunning(in: temp) == false)

            // The first-run command itself, without Terminal: a declined setup, then a failed one.
            let fake = temp.appendingPathComponent("fake", isDirectory: true)
            try fm.createDirectory(at: fake.appendingPathComponent("scripts"), withIntermediateDirectories: true)
            let fakeConfig = temp.appendingPathComponent("conf/arva.conf")
            let runner = fake.appendingPathComponent(FirstRunCommand.fileName)
            for (script, expected) in [("echo 'Nothing was saved.'; exit 0", "declined"), ("echo 'No disk'; exit 4", "4")] {
                try "\(script)\n".write(to: fake.appendingPathComponent("scripts/start.sh"), atomically: true, encoding: .utf8)
                try FirstRunCommand.contents(config: fakeConfig).write(to: runner, atomically: true, encoding: .utf8)
                let ran = ShellTask.run("/bin/sh", [runner.path], directory: fake, timeout: 30)
                let status = (try? String(contentsOf: fake.appendingPathComponent(FirstRunCommand.statusFile), encoding: .utf8))?
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                check("first-run command records \(expected)", status == expected, "\(status ?? "none"): \(ran?.output.prefix(300) ?? "did not run")")
            }

            // The app's stand-ins for git and open.
            let shims = temp.appendingPathComponent("bin", isDirectory: true)
            try LauncherShims.install(in: shims)
            var shimEnv = ShellEnvironment.make()
            shimEnv["ARVA_APP_COMMIT"] = "0123456789ab"
            let git = ShellTask.run(shims.appendingPathComponent("git").path, ["-C", temp.path, "rev-parse", "--short=12", "HEAD"],
                                    environment: shimEnv, timeout: 20)
            check("git stand-in answers with the app's commit", git?.status == 0 && git?.output == "0123456789ab\n", git?.output ?? "did not run")
            shimEnv["ARVA_APP_COMMIT"] = "unknown"
            let noCommit = ShellTask.run(shims.appendingPathComponent("git").path, ["rev-parse", "HEAD"], environment: shimEnv, timeout: 20)
            check("git stand-in without a commit fails quietly", noCommit?.status == 1 && noCommit?.output == "", noCommit?.output ?? "")
            let open = ShellTask.run(shims.appendingPathComponent("open").path, ["http://localhost:8080"], environment: shimEnv, timeout: 20)
            check("open stand-in leaves ARVA's address to the app", open?.status == 0 && open?.output == "")
            let shimPath = ShellEnvironment.make(base: ["PATH": "/usr/bin:/bin"])["PATH"] ?? ""
            check("launcher PATH starts with the stand-ins", shimPath.hasPrefix(AppPaths.shimDir.path + ":"), shimPath)

            // .env of an ARVA installed before in ~/ARVA: linked when the runtime folder has none.
            let legacy = temp.appendingPathComponent("legacy", isDirectory: true)
            let target = temp.appendingPathComponent("target", isDirectory: true)
            try fm.createDirectory(at: legacy, withIntermediateDirectories: true)
            try fm.createDirectory(at: target, withIntermediateDirectories: true)
            check(".env: nothing to link", EnvLink.ensure(runtime: target, legacy: legacy) == nil)
            try "ARVA_DB_PASSWORD=x\n".write(to: legacy.appendingPathComponent(".env"), atomically: true, encoding: .utf8)
            check(".env: linked", EnvLink.ensure(runtime: target, legacy: legacy) != nil
                  && (try? String(contentsOf: target.appendingPathComponent(".env"), encoding: .utf8)) == "ARVA_DB_PASSWORD=x\n")
            check(".env: already linked", EnvLink.ensure(runtime: target, legacy: legacy) == nil)
            try fm.removeItem(at: legacy.appendingPathComponent(".env"))
            check(".env: link removed with its file", EnvLink.ensure(runtime: target, legacy: legacy) != nil
                  && (try? fm.destinationOfSymbolicLink(atPath: target.appendingPathComponent(".env").path)) == nil)
            try "OWN=1\n".write(to: target.appendingPathComponent(".env"), atomically: true, encoding: .utf8)
            try "ARVA_DB_PASSWORD=x\n".write(to: legacy.appendingPathComponent(".env"), atomically: true, encoding: .utf8)
            check(".env: the runtime folder's own is kept", EnvLink.ensure(runtime: target, legacy: legacy) == nil
                  && (try? String(contentsOf: target.appendingPathComponent(".env"), encoding: .utf8)) == "OWN=1\n")

            // A log followed as it grows.
            let logURL = temp.appendingPathComponent("tail.log")
            try "one\ntw".write(to: logURL, atomically: false, encoding: .utf8)
            let tail = LogTail(url: logURL)
            check("log tail reads whole lines", tail.read() == "one\n")
            let handle = try FileHandle(forWritingTo: logURL)
            _ = try handle.seekToEnd()
            try handle.write(contentsOf: Data("o\n\u{1B}[1mthree\u{1B}[0m\r\n".utf8))
            try handle.close()
            check("log tail reads only what was added", tail.read() == "two\nthree\n")
            check("log tail has nothing new", tail.read() == "")

            // A launcher's output goes to a file (it outlives the app), and stopping it stops what it started.
            let task = ShellTask(executable: "/bin/sh", arguments: ["-c", "echo started; sleep 30 & sleep 30 & wait"],
                                 directory: temp, environment: ShellEnvironment.make(),
                                 logFile: temp.appendingPathComponent("logs/task.log"))
            try task.start()
            Thread.sleep(forTimeInterval: 1)
            let root = task.process.processIdentifier
            let children = ProcessTree.descendants(of: root, in: ProcessTree.parents())
            check("process tree found", children.count >= 2, "\(children.count)")
            ProcessTree.terminate(root: root, grace: 5)
            task.process.waitUntilExit()
            Thread.sleep(forTimeInterval: 0.6)
            check("process tree stopped", !children.contains(where: ProcessTree.isAlive))
            check("launcher output read from its log file", task.output.contains("started"), task.output)
        } catch {
            check("runtime sync", false, error.localizedDescription)
        }

        // arva.conf, read as scripts/lib/arva-locations.sh reads it.
        let sample = "# ARVA locations\r\nARVA_DATA_DIR=/Volumes/Lab Disk/ARVA/data\r\nARVA_DATA_DIR_MOUNT=/Volumes/Lab Disk\n"
            + "ARVA_DATABASES_DIR=/Volumes/Lab Disk/ARVA/databases\nARVA_ADD_DATABASES=/Volumes/Old/db\n"
            + "ARVA_ADD_DATABASES=/Volumes/Old/db\nARVA_ADD_DATABASES=/Users/x/db=2\nARVA_PLATFORM=linux/arm64\n"
            + "not a pair\nARVA_SOMETHING=1\nARVA_IMPORT_DIR=\n"
        let cfg = ArvaConfig.parse(sample)
        check("arva.conf data folder", cfg.dataDir == "/Volumes/Lab Disk/ARVA/data", cfg.dataDir ?? "nil")
        check("arva.conf carriage returns removed", cfg.dataMount == "/Volumes/Lab Disk", cfg.dataMount ?? "nil")
        check("arva.conf databases folder", cfg.databasesDir == "/Volumes/Lab Disk/ARVA/databases")
        check("arva.conf added folders, once each, value after the first =",
              cfg.extraDatabases == ["/Volumes/Old/db", "/Users/x/db=2"], "\(cfg.extraDatabases)")
        check("arva.conf platform", cfg.platform == "linux/arm64")
        check("arva.conf empty import folder", cfg.importDir == nil)
        check("arva.conf ignored lines", cfg.ignoredLines == [9, 10], "\(cfg.ignoredLines)")
        check("arva.conf missing disk named", cfg.missingDisks(exists: { _ in false }) == ["Lab Disk"], "\(cfg.missingDisks(exists: { _ in false }))")
        check("arva.conf connected disk", cfg.missingDisks(exists: { _ in true }).isEmpty)
        check("arva.conf without external disk", ArvaConfig.parse("ARVA_DATA_DIR=/Users/x/ARVA\n").missingDisks(exists: { _ in false }).isEmpty)
        check("arva.conf bad platform ignored", ArvaConfig.parse("ARVA_PLATFORM=windows\n").platform == nil)
        check("arva.conf empty file", ArvaConfig.parse("") == ArvaConfig())
        let configPath = AppPaths.configFile(environment: ["XDG_CONFIG_HOME": "/tmp/xdg"]).path
        check("arva.conf follows XDG_CONFIG_HOME", configPath == "/tmp/xdg/arva/arva.conf", configPath)
        check("arva.conf ignores a relative XDG_CONFIG_HOME",
              AppPaths.configFile(environment: ["XDG_CONFIG_HOME": "rel"]).path.hasSuffix("/.config/arva/arva.conf"))
        if let real = ArvaConfig.load(from: AppPaths.configFile()) {
            print("# this Mac's arva.conf parsed: \(real.ignoredLines.count) ignored lines")
        }

        // The web view's rules.
        let local = ["http://localhost:8080/", "http://localhost:8080/projects/3?tab=qc", "http://127.0.0.1:8080/api/v1/reports/1"]
        for url in local { check("shown in the app: \(url)", WebPolicy.classify(URL(string: url)!) == .local) }
        let external = ["https://www.ncbi.nlm.nih.gov/gene/123", "http://localhost:3000/", "https://localhost:8080/",
                        "http://example.org:8080/", "mailto:someone@example.org"]
        for url in external { check("opened in the browser: \(url)", WebPolicy.classify(URL(string: url)!) == .external) }
        for url in ["file:///etc/hosts", "javascript:alert(1)", "ftp://example.org/x"] {
            check("never opened: \(url)", WebPolicy.classify(URL(string: url)!) == .blocked)
        }
        for url in ["about:blank", "blob:http://localhost:8080/6f1c", "data:text/plain,hi"] {
            check("frames and exports: \(url)", WebPolicy.classify(URL(string: url)!) == .inert)
        }
        let fastq = WebPolicy.contentTypes(forAccept: ".fastq,.fq,.fasta,.fa,.fna,.fas,.gz,.pod5")
        check("accept list of sequencing files", fastq?.count == 8, "\(fastq?.count ?? -1)")
        check("accept MIME type", WebPolicy.contentTypes(forAccept: ".json,application/json")?.contains(.json) ?? false)
        check("accept compound extension", WebPolicy.contentTypes(forAccept: ".fastq.gz")?.first == UTType(filenameExtension: "gz"))
        check("accept wildcard allows everything", WebPolicy.contentTypes(forAccept: "*/*") == nil)
        check("no accept allows everything", WebPolicy.contentTypes(forAccept: "") == nil)
        check("accept image wildcard", WebPolicy.contentTypes(forAccept: "image/*") == [.image])

        // Download names.
        let dir = URL(fileURLWithPath: "/tmp/dl", isDirectory: true)
        let taken: Set<String> = ["/tmp/dl/report.html", "/tmp/dl/report (2).html", "/tmp/dl/reads.fastq.gz", "/tmp/dl/README"]
        let exists: (String) -> Bool = { taken.contains($0) }
        check("download name kept", WebPolicy.uniqueDestination(in: dir, suggested: "summary.csv", exists: exists).lastPathComponent == "summary.csv")
        check("download name made unique",
              WebPolicy.uniqueDestination(in: dir, suggested: "report.html", exists: exists).lastPathComponent == "report (3).html")
        check("download keeps both extensions",
              WebPolicy.uniqueDestination(in: dir, suggested: "reads.fastq.gz", exists: exists).lastPathComponent == "reads (2).fastq.gz")
        check("download without extension",
              WebPolicy.uniqueDestination(in: dir, suggested: "README", exists: exists).lastPathComponent == "README (2)")
        let hostile = WebPolicy.uniqueDestination(in: dir, suggested: "../../.ssh/authorized_keys", exists: exists)
        check("download stays in Downloads", hostile.deletingLastPathComponent().path == "/tmp/dl" && hostile.lastPathComponent == "authorized_keys",
              hostile.path)
        check("download hidden name made visible", WebPolicy.safeFileName(".profile") == "profile")
        check("download empty name", !WebPolicy.safeFileName("").isEmpty)

        // The environment the launcher gets.
        let env = ShellEnvironment.make(base: ["PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/Users/x"])
        check("launcher PATH has Docker's places", (env["PATH"] ?? "").contains("/Applications/Docker.app/Contents/Resources/bin"))
        check("launcher language", env["LANG"] == Lang.posixLocale && env["LC_ALL"] == nil)
        check("launcher compose project", env["COMPOSE_PROJECT_NAME"] == "arva")
        check("output cleaned", cleanOutput("\u{1B}[1mbold\u{1B}[0m\r\nline\r") == "bold\nline\n")
        check("terminal recording cleaned", cleanOutput("\u{1B}]0;title\u{07}a\u{08} b\u{1B}(B\u{1B}[?1h\u{1B}=\tc\n") == "a b\tc\n",
              cleanOutput("\u{1B}]0;title\u{07}a\u{08} b\u{1B}(B\u{1B}[?1h\u{1B}=\tc\n").debugDescription)
        let failure = "The database folder /Volumes/Old/db is not available: is its disk connected?\n"
            + "  ARVA starts without it; its databases are shown as unavailable (disk not connected) and are not deleted.\n"
            + "Docker could not download ghcr.io/x:1 and ghcr.io/y:1. Check the internet connection\n"
        let lines = AppDelegate.failureLines(failure)
        check("failure read from the last lines, without warnings", lines.contains("could not download") && !lines.contains("connected"), lines)
        check("details hide the home folder", AppInfo.tilde(AppPaths.home.path + "/x") == "~/x")

        // Keeping the Mac awake while analyses run: the rules with a stand-in, then one real assertion.
        var created = 0
        var released: [IOPMAssertionID] = []
        let fake = SleepGuard.Backend(create: { _ in created += 1; return IOPMAssertionID(41 + created) },
                                      release: { released.append($0); return true })
        let guardian = SleepGuard(backend: fake)
        var changes: [Bool] = []
        guardian.onChange = { changes.append($0) }
        guardian.update(activeJobs: 0)
        check("sleep: nothing running, nothing held", !guardian.isActive && created == 0)
        guardian.update(activeJobs: 2)
        guardian.update(activeJobs: 3)
        check("sleep: held once while analyses run", guardian.isActive && created == 1 && changes == [true])
        guardian.update(activeJobs: 0)
        check("sleep: one idle answer (between two jobs of a batch) keeps it", guardian.isActive)
        guardian.update(activeJobs: 0)
        check("sleep: released after \(SleepGuard.idlePollsToRelease) idle answers", !guardian.isActive && released == [42]
              && changes == [true, false])
        guardian.update(activeJobs: 1)
        for _ in 1..<SleepGuard.unknownPollsToRelease { guardian.update(activeJobs: nil) }
        check("sleep: kept while ARVA briefly does not answer", guardian.isActive)
        guardian.update(activeJobs: nil)
        check("sleep: released when ARVA stops answering", !guardian.isActive && released == [42, 43])
        guardian.update(activeJobs: 1)
        guardian.release()
        guardian.release()
        check("sleep: released on stop or quit, once", !guardian.isActive && released == [42, 43, 44])
        check("sleep: assertion name within IOPMLib's 128 characters", SleepGuard.assertionName.count <= 128)
        check("sleep: status line", SleepGuard.statusText == (Lang.isSpanish
            ? "La Mac no se suspenderá mientras haya análisis en curso"
            : "The Mac will not sleep while analyses are running"), SleepGuard.statusText)
        if let id = SleepGuard.system.create(SleepGuard.assertionName + " (self-test)") {
            check("sleep: power management takes the assertion", true)
            check("sleep: power management releases it", SleepGuard.system.release(id))
        } else {
            check("sleep: power management takes the assertion", false, "IOPMAssertionCreateWithName did not succeed")
        }

        // Notifications when analyses end: the jobs read from the API's JSON, which ones ended, what is said.
        let listJSON = """
        [{"id": "a1b2c3d4-0000-4000-8000-000000000001", "status": "running", "tool_name": "Flye",
          "job_type": "flye_assembly", "sample_id": "5a-1", "log_text": "long"},
         {"id": "../etc", "status": "running"}, {"status": "pending"},
         {"id": "p-1", "status": "pending", "tool_name": "", "job_type": "multiqc_report", "sample_id": null}]
        """
        let parsed = JobSnapshot.list(from: try? JSONSerialization.jsonObject(with: Data(listJSON.utf8)))
        check("jobs: list read, odd ids left out", parsed?.map { $0.id } == ["a1b2c3d4-0000-4000-8000-000000000001", "p-1"],
              "\(parsed?.map { $0.id } ?? [])")
        check("jobs: sample of a sample job, none for a project job", parsed?.first?.sampleId == "5a-1" && parsed?.last?.sampleId == nil)
        check("jobs: an answer that is not a list", JobSnapshot.list(from: ["detail": "Not authenticated"]) == nil
              && JobSnapshot.list(from: nil) == nil)
        check("jobs: list path", JobSnapshot.listPath(status: "running") == "api/v1/jobs?status=running&limit=200")
        var watch = JobWatch()
        let flye = JobSnapshot(id: "j1", status: "running", tool: "Flye", sampleId: "s1")
        let fastp = JobSnapshot(id: "j2", status: "pending", tool: "fastp", sampleId: "s2")
        check("jobs: nothing ended at the first look", watch.update(active: [flye, fastp]).isEmpty && watch.isWatching)
        let fastpRunning = JobSnapshot(id: "j2", status: "running", tool: "fastp", sampleId: "s2")
        check("jobs: still running, nothing ended", watch.update(active: [flye, fastpRunning]).isEmpty)
        let left = watch.update(active: [flye, JobSnapshot(id: "j9", status: "completed")])
        check("jobs: the job that left the list is looked up, as last seen", left == [fastpRunning], "\(left)")
        check("jobs: ended jobs in the list are not followed", watch.active.keys.sorted() == ["j1"])
        watch.stillActive(fastpRunning)
        check("jobs: a job still running is followed again", watch.active.keys.sorted() == ["j1", "j2"])
        var lost = JobWatch()
        _ = lost.update(active: [flye])
        var kept: [Bool] = []
        for _ in 0..<JobWatch.lookupsBeforeDropping {
            if lost.update(active: []) == [flye] { kept.append(lost.lookupFailed(flye)) }
        }
        check("jobs: a job without an answer is dropped after \(JobWatch.lookupsBeforeDropping) lookups",
              kept == [true, true, false] && !lost.isWatching, "\(kept)")
        let finished = JobNotice.make(before: flye, after: JobSnapshot(id: "j1", status: "completed", tool: "Flye", sampleId: "s1"),
                                      sample: "S-27")
        check("notice: finished, with the sample",
              finished?.title == (Lang.isSpanish ? "ARVA: Flye terminó — S-27" : "ARVA: Flye finished — S-27")
                  && finished?.path == "samples/s1", finished?.title ?? "none")
        let failedNotice = JobNotice.make(before: fastpRunning, after: JobSnapshot(id: "j2", status: "failed", tool: "fastp"), sample: nil)
        check("notice: failed, sample code unknown",
              failedNotice?.title == (Lang.isSpanish ? "ARVA: fastp falló" : "ARVA: fastp failed") && failedNotice?.path == "samples/s2",
              failedNotice?.title ?? "none")
        check("notice: cancelled while running",
              JobNotice.make(before: flye, after: JobSnapshot(id: "j1", status: "cancelled"), sample: "S-27")?.title
                  == (Lang.isSpanish ? "ARVA: Flye se canceló — S-27" : "ARVA: Flye cancelled — S-27"))
        check("notice: nothing for a job cancelled while waiting",
              JobNotice.make(before: fastp, after: JobSnapshot(id: "j2", status: "cancelled"), sample: nil) == nil)
        check("notice: nothing while it runs",
              JobNotice.make(before: fastp, after: fastpRunning, sample: nil) == nil)
        let report = JobNotice.make(before: JobSnapshot(id: "j4", status: "running", jobType: "multiqc_report"),
                                    after: JobSnapshot(id: "j4", status: "completed", jobType: "multiqc_report"), sample: nil)
        check("notice: a project-level job just opens ARVA", report != nil && report?.path == nil, report?.title ?? "none")
        check("notice: ARVA's own import named", JobNotice.analysisName(tool: "arva-import", jobType: "server_import")
              == (Lang.isSpanish ? "Importación" : "Import"))

        // ARVA not answering (Docker Desktop closed): said after two failed checks in a row, once, until it answers.
        var server = ServerWatch()
        check("server: answers", server.update(answered: true) == nil && !server.isDown)
        check("server: one failed check is not enough", server.update(answered: false) == nil && !server.isDown)
        check("server: not responding after \(ServerWatch.failuresToReport) failed checks",
              server.update(answered: false) == .wentDown && server.isDown)
        check("server: said once", server.update(answered: false) == nil)
        check("server: answers again", server.update(answered: true) == .cameBack && !server.isDown)
        check("server: a lone failure after that is not reported", server.update(answered: false) == nil
              && server.update(answered: true) == nil)
        // When it answers again: how long it was down, from the first failed check, decides whether to reload a page
        // that is still ARVA's (a reload discards an open dialog or a form being filled).
        var timed = ServerWatch()
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        _ = timed.update(answered: false, now: t0)
        _ = timed.update(answered: false, now: t0.addingTimeInterval(15))
        check("server: outage measured from the first failed check",
              timed.update(answered: true, now: t0.addingTimeInterval(30)) == .cameBack && timed.lastOutage == 30)
        check("server: busy (30 s) with ARVA's page shown: no reload",
              !ServerWatch.shouldReload(showsARVAPage: true, downFor: timed.lastOutage))
        check("server: the not-answering page is always reloaded",
              ServerWatch.shouldReload(showsARVAPage: false, downFor: timed.lastOutage))
        _ = timed.update(answered: false, now: t0.addingTimeInterval(100))
        _ = timed.update(answered: false, now: t0.addingTimeInterval(115))
        _ = timed.update(answered: false, now: t0.addingTimeInterval(130))
        check("server: stopped (\(Int(ServerWatch.reloadAfterDown)) s or more): reload",
              timed.update(answered: true, now: t0.addingTimeInterval(190)) == .cameBack
              && ServerWatch.shouldReload(showsARVAPage: true, downFor: timed.lastOutage))

        // ARVA → Choose Import Folder…: the launcher's rules and the app's.
        let folders: Set<String> = ["/Volumes/JM/runs", "/Users/x", "/Users/x/Seq", "/Users/x/locked"]
        let rule: (String) -> ImportFolderRule.Problem? = { path in
            ImportFolderRule.problem(path, home: "/Users/x", isDirectory: { folders.contains($0) },
                                     isReadable: { $0 != "/Users/x/locked" })
        }
        let cases: [(String, ImportFolderRule.Problem?)] = [
            ("/Volumes/JM/runs", nil), ("/Users/x/Seq", nil), ("/Users/x", .home), ("/Users/x/", .home),
            ("/Users/x/.cache/runs", .hidden), ("/Volumes/JM/../runs", .hidden), ("/", .root), ("runs", .notAbsolute),
            ("/Volumes/JM/gone", .missing), ("/Users/x/locked", .notReadable), ("/Volumes/JM/r\u{7}", .controlCharacters),
            ("/" + String(repeating: "a", count: 1100), .tooLong),
        ]
        for (path, expected) in cases {
            let got = rule(path)
            check("import folder rule: \(path.prefix(40))", got == expected, "\(String(describing: got))")
            if let got { check("import folder message: \(got)", !ImportFolderRule.message(got, path: path).isEmpty) }
        }

        // The icon: the visible part of the logo, found in a constructed image (rows counted from the top).
        var pixels = [UInt8](repeating: 0, count: 6 * 5 * 4)
        for (x, y) in [(2, 1), (4, 2)] {
            pixels[(y * 6 + x) * 4] = 200
            pixels[(y * 6 + x) * 4 + 3] = 255
        }
        func makeImage(_ bytes: [UInt8]) -> CGImage? {
            guard let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
            return CGImage(width: 6, height: 5, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 24,
                           space: CGColorSpaceCreateDeviceRGB(),
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                           provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
        }
        if let image = makeImage(pixels) {
            let bounds = IconRenderer.visibleBounds(image)
            check("icon: visible part of the logo", bounds == CGRect(x: 2, y: 1, width: 3, height: 2), String(describing: bounds))
            let cropped = bounds.flatMap { image.cropping(to: $0) }
            let inner = cropped.flatMap { IconRenderer.visibleBounds($0) }
            check("icon: the visible part is what is cut out", cropped?.width == 3 && cropped?.height == 2
                  && inner == CGRect(x: 0, y: 0, width: 3, height: 2), String(describing: inner))
        } else {
            check("icon: test image", false)
        }
        check("icon: a fully transparent image has no visible part",
              makeImage([UInt8](repeating: 0, count: 6 * 5 * 4)).flatMap { IconRenderer.visibleBounds($0) } == nil)

        print(failures == 0 ? "self-test passed" : "self-test FAILED: \(failures) check(s)")
        return failures == 0 ? 0 : 1
    }
}
