import Foundation
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
            let syntax = ShellTask.run("/bin/sh", ["-n", command.path], timeout: 20)
            check("first-run command syntax", syntax?.status == 0, syntax?.output ?? "")
            check("first-run status is unknown while it runs", FirstRunCommand.status(in: temp) == nil)
            try "3\n".write(to: temp.appendingPathComponent(FirstRunCommand.statusFile), atomically: true, encoding: .utf8)
            check("first-run status is read", FirstRunCommand.status(in: temp) == 3)
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
        check("details hide the home folder", AppInfo.tilde(AppPaths.home.path + "/x") == "~/x")

        print(failures == 0 ? "self-test passed" : "self-test FAILED: \(failures) check(s)")
        return failures == 0 ? 0 : 1
    }
}
