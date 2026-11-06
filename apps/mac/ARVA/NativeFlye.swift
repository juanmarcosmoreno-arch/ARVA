import Foundation

// "Flye for this Mac" (docs/plan-flye-nativo.md, option (b) and "Contrato implementado"). Flye 2.9.6 fills a fixed
// 8 GiB k-mer table that does not fit Docker Desktop's VM on an 8 GB Mac, but runs natively. ARVA.app installs the
// same Flye release from Bioconda's osx-arm64 build, only from ARVA's checked-in lock
// (docker/conda-locks/flye/osx-arm64.lock, every package pinned by URL and sha256), and runs it for ARVA's worker
// through ARVA's own adapter (arva_tools/native.py), which builds the command itself and runs it only when it is
// identical to the one the API built. Nothing here sends data anywhere: the only network traffic is the API at
// localhost and, when the person asks for the installation, the packages from conda.anaconda.org.
//
// The bundle carries, in Contents/Resources/native (scripts/build-mac-app.sh): arva_tools/{__init__,base,runner,
// native_common,flye,bakta,nanoplot,amrfinderplus,native}.py, scripts/conda_locks.py, scripts/install-micromamba.sh
// (micromamba pinned by sha256 per platform), docker/conda-locks/{flye,bakta}/{osx-arm64.lock,native-platforms} and
// the --help texts of Flye 2.9.6 and Bakta 1.12.2 (fixtures/{flye,bakta}/help_*.txt, from
// workflows/tool-adapters/tests/fixtures).
//
// "Bakta for this Mac" works the same way (NativeTool.bakta): Bakta 1.12.2 runs DIAMOND with a fixed block size, and
// with the full database that block does not fit Docker Desktop's VM on an 8 GB Mac (registro de prueba, item 49).

/// One tool ARVA.app may install and run natively: where its environment lives and what the bundle carries for it.
struct NativeTool: Equatable {
    /// The id the API uses ("flye", "bakta") and the name shown.
    let id: String
    let name: String
    let lockRel: String
    let platformsRel: String
    let helpRel: String
    /// The channel subdir of the tool's own package in the lock (Bakta is noarch).
    let lockSubdir: String
    let downloadEN: String
    let downloadES: String

    static let flye = NativeTool(id: "flye", name: "Flye", lockRel: "docker/conda-locks/flye/osx-arm64.lock",
                                 platformsRel: "docker/conda-locks/flye/native-platforms",
                                 helpRel: "fixtures/flye/help_2.9.6.txt", lockSubdir: "osx-arm64",
                                 downloadEN: "Flye 2.9.6 with its 18 dependencies (about 48 MB)",
                                 downloadES: "Flye 2.9.6 con sus 18 dependencias (unos 48 MB)")
    static let bakta = NativeTool(id: "bakta", name: "Bakta", lockRel: "docker/conda-locks/bakta/osx-arm64.lock",
                                  platformsRel: "docker/conda-locks/bakta/native-platforms",
                                  helpRel: "fixtures/bakta/help_1.12.2.txt", lockSubdir: "noarch",
                                  downloadEN: "Bakta 1.12.2 with DIAMOND, BLAST+, AMRFinderPlus, tRNAscan-SE, Infernal and its other 133 packages (about 296 MB)",
                                  downloadES: "Bakta 1.12.2 con DIAMOND, BLAST+, AMRFinderPlus, tRNAscan-SE, Infernal y sus otros 133 paquetes (unos 296 MB)")
    static let all = [flye, bakta]

    static func named(_ id: String?) -> NativeTool? { all.first { $0.id == id } }

    var envPrefix: URL { NativePaths.toolsDir.appendingPathComponent("conda/\(id)", isDirectory: true) }
    var executable: String { envPrefix.appendingPathComponent("bin/\(id)").path }
    var python: String { envPrefix.appendingPathComponent("bin/python").path }
    var recordDir: URL { envPrefix.appendingPathComponent("arva-native", isDirectory: true) }
    var installedLock: URL { recordDir.appendingPathComponent("osx-arm64.lock") }
    var installRecord: URL { recordDir.appendingPathComponent("install.json") }

    /// An environment ARVA.app made (its record is there) with the tool and its Python.
    var isInstalled: Bool {
        let fm = FileManager.default
        return fm.isExecutableFile(atPath: executable) && fm.isExecutableFile(atPath: python)
            && fm.fileExists(atPath: installRecord.path)
    }
}

/// Where "Flye for this Mac" lives. The environment is in ~/.arva-tools/conda/flye (the place ARVA's Linux
/// installation uses for its tool environments), not in ~/Library/Application Support: Flye refuses paths that contain
/// spaces, and the adapter refuses an executable path with one (arva_tools.flye.native_executable).
enum NativePaths {
    static var toolsDir: URL { AppPaths.home.appendingPathComponent(".arva-tools", isDirectory: true) }
    // Flye's environment (NativeTool.flye), by the names the first version of this file used.
    static var envPrefix: URL { NativeTool.flye.envPrefix }
    static var flye: String { NativeTool.flye.executable }
    static var python: String { NativeTool.flye.python }
    /// What ARVA.app writes into the environment about how it made it: the lock it was created from and a record.
    static var recordDir: URL { NativeTool.flye.recordDir }
    static var installedLock: URL { NativeTool.flye.installedLock }
    static var installRecord: URL { NativeTool.flye.installRecord }

    static let lockRel = NativeTool.flye.lockRel
    static let nativeScriptRel = "arva_tools/native.py"
    static let condaLocksRel = "scripts/conda_locks.py"
    static let micromambaRel = "scripts/install-micromamba.sh"
    static let helpRel = NativeTool.flye.helpRel
    /// Every file the bundle must carry for "Flye for this Mac" and "Bakta for this Mac" (the self-test checks them).
    static let bundledFiles = [
        "arva_tools/__init__.py", "arva_tools/base.py", "arva_tools/runner.py", "arva_tools/native_common.py",
        "arva_tools/flye.py", "arva_tools/bakta.py", "arva_tools/nanoplot.py", "arva_tools/amrfinderplus.py",
        nativeScriptRel, condaLocksRel, micromambaRel,
    ] + NativeTool.all.flatMap { [$0.lockRel, $0.platformsRel, $0.helpRel] }

    static var bundle: URL? { Bundle.main.resourceURL?.appendingPathComponent("native", isDirectory: true) }
    static func bundled(_ rel: String) -> URL? { bundle?.appendingPathComponent(rel) }

    /// The work records, the running job's process record and the installation's temporary folders.
    static var workDir: URL { AppPaths.supportDir.appendingPathComponent("native", isDirectory: true) }
    static var runningRecord: URL { workDir.appendingPathComponent("running.json") }
    static var logsDir: URL { AppPaths.logsDir.appendingPathComponent("native", isDirectory: true) }
    static var executorIDKey: String { "ARVA.nativeExecutorID" }

    /// The token file the API reads (/run/arva-host/native-executor.token in its containers): $ARVA_CONFIG_DIR/host,
    /// which scripts/lib/arva-locations.sh mounts read-only at /run/arva-host when ARVA uses folders on this Mac.
    static func tokenFile(environment: [String: String] = ProcessInfo.processInfo.environment) -> URL {
        AppPaths.configFile(environment: environment).deletingLastPathComponent()
            .appendingPathComponent("host", isDirectory: true).appendingPathComponent("native-executor.token")
    }

    /// Whether "Flye for this Mac" can exist here at all: Apple silicon, running natively (Bioconda's osx-arm64
    /// build; the x86_64 slice of the app runs only on Intel Macs or under Rosetta).
    static var platformSupported: Bool { AppInfo.architecture == "arm64" }

    /// An environment ARVA.app made (its record is there) with Flye and its Python.
    static var isInstalled: Bool { NativeTool.flye.isInstalled }

    /// Some native tool is installed (the executor then runs).
    static var anyInstalled: Bool { NativeTool.all.contains { $0.isInstalled } }

    /// The database folders of arva.conf (ARVA_DATABASES_DIR, each ARVA_ADD_DATABASES), links resolved as the launcher
    /// resolves them: the only roots a native Bakta run reads databases from (sent to the API and to native.py).
    static func databaseDirs(_ config: ArvaConfig?) -> [String] {
        guard let config else { return [] }
        var out: [String] = []
        for dir in [config.databasesDir].compactMap({ $0 }) + config.extraDatabases where dir.hasPrefix("/") {
            let resolved = NativeRelPath.realPath(dir) ?? dir
            if NativeRelPath.isNormalisedAbsolute(resolved), !out.contains(resolved) { out.append(resolved) }
        }
        return Array(out.prefix(16))
    }
}

/// The checks on paths that come from the API, as arva_tools.flye makes them (native_relative, native_data_dir,
/// native_path): ARVA.app makes them again before it writes or runs anything.
enum NativeRelPath {
    private static func isPlain(_ c: Unicode.Scalar) -> Bool {
        (c >= "A" && c <= "Z") || (c >= "a" && c <= "z") || (c >= "0" && c <= "9") || c == "_"
    }

    /// One component of a relative path: [A-Za-z0-9_][A-Za-z0-9._-]{0,200} (never "." or "..", never empty).
    static func isComponent<S: StringProtocol>(_ part: S) -> Bool {
        let scalars = Array(part.unicodeScalars)
        guard let first = scalars.first, scalars.count <= 201, isPlain(first) else { return false }
        return scalars.allSatisfy { isPlain($0) || $0 == "." || $0 == "-" }
    }

    /// A path relative to the data folder as ARVA writes them: no leading "/", no "//", no "." or "..".
    static func isSafe(_ rel: String) -> Bool {
        guard !rel.isEmpty, rel.utf8.count <= 1024 else { return false }
        return rel.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { isComponent($0) }
    }

    static func hasControlCharacters(_ text: String) -> Bool {
        text.unicodeScalars.contains { $0.value < 0x20 || $0.value == 0x7F }
    }

    /// An absolute, normalised path (no ".", "..", "//" or trailing "/"), not "/", without control characters.
    static func isNormalisedAbsolute(_ path: String) -> Bool {
        guard path.hasPrefix("/"), path != "/", path.utf8.count <= 1024, !hasControlCharacters(path) else { return false }
        let parts = path.dropFirst().split(separator: "/", omittingEmptySubsequences: false)
        return parts.allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }

    static func hasWhitespace(_ text: String) -> Bool {
        text.unicodeScalars.contains { CharacterSet.whitespacesAndNewlines.contains($0) }
    }

    /// The path with every link resolved, or nil when it does not exist.
    static func realPath(_ path: String) -> String? {
        guard let resolved = realpath(path, nil) else { return nil }
        defer { free(resolved) }
        return String(cString: resolved)
    }

    enum Problem: Equatable { case unsafe, outside, missing }

    /// dataDir/rel stays inside dataDir once links are resolved (a read link points at the stored file; Flye's
    /// out-dir does not exist yet, so its parent is checked when `mustExist` is false).
    static func check(_ rel: String, in dataDir: String, mustExist: Bool = true) -> Problem? {
        guard isSafe(rel) else { return .unsafe }
        guard let root = realPath(dataDir) else { return .missing }
        let path = dataDir + "/" + rel
        // A folder the tool creates may already be there (a resumed Flye's work folder): then it is checked itself.
        let existing = mustExist ? nil : realPath(path)
        let target = mustExist ? path : (path as NSString).deletingLastPathComponent
        guard let real = existing ?? realPath(target) else { return mustExist ? .missing : .outside }
        if real != root && !real.hasPrefix(root + "/") { return .outside }
        return nil
    }
}

/// The work record of a claimed job (POST /native/jobs/claim → work), checked before anything is written or run.
/// arva_tools/native.py checks it again (and more: the storage marker, flye-samtools or Bakta's programs, the
/// identical argv).
enum NativeWorkCheck {
    static let stderrLog = "flye.stderr.log"
    static let baktaConsoleLog = "bakta.console.log"

    /// nil when the work may be handed to native.py; otherwise the refusal code native.py would give, and why.
    static func problem(_ work: [String: Any], dataDir: String, executable: String,
                        databaseDirs: [String] = []) -> (code: String, detail: String)? {
        if work["tool"] as? String == "bakta" {
            return baktaProblem(work, dataDir: dataDir, executable: executable, databaseDirs: databaseDirs)
        }
        guard work["tool"] as? String == "flye" else { return ("not_flye_work", "the work record is not a Flye run") }
        guard let workData = work["data_dir"] as? String, let workExe = work["executable"] as? String,
              let reads = work["reads"] as? [String], !reads.isEmpty, let outDir = work["out_dir"] as? String,
              let resultsDir = work["results_dir"] as? String, work["params"] is [String: Any],
              work["argv"] is [String], work["resume"] is Bool, work["storage_id"] is String else {
            return ("work_incomplete", "the work record lacks a field or has one of the wrong kind")
        }
        guard workData == dataDir else {
            return ("other_data_dir", "the work is for the data folder \(workData), this Mac's ARVA uses \(dataDir)")
        }
        guard workExe == executable else {
            return ("other_executable", "the work names \(workExe), this Mac's Flye is \(executable)")
        }
        guard work["stderr_log"] as? String == stderrLog else { return ("unsafe_path", "unexpected log name") }
        for rel in reads + [outDir, resultsDir] where !NativeRelPath.isSafe(rel) {
            return ("unsafe_path", "\(rel) is not a plain path inside the data folder")
        }
        guard outDir.hasPrefix(resultsDir + "/") else {
            return ("unsafe_path", "Flye's folder \(outDir) is not inside the job's folder \(resultsDir)")
        }
        for rel in reads {
            if let problem = inputProblem(rel, dataDir: dataDir) { return problem }
        }
        if let p = NativeRelPath.check(resultsDir, in: dataDir) {
            return (p == .missing ? "input_missing" : "outside_data_dir", "the job's folder \(resultsDir) is not usable")
        }
        if NativeRelPath.check(outDir, in: dataDir, mustExist: false) != nil {
            return ("outside_data_dir", "Flye's folder \(outDir) leads outside the data folder")
        }
        return nil
    }

    private static func inputProblem(_ rel: String, dataDir: String) -> (code: String, detail: String)? {
        switch NativeRelPath.check(rel, in: dataDir) {
        case .none: return nil
        case .some(.missing): return ("input_missing", "\(rel) does not exist in the data folder")
        case .some(.outside): return ("outside_data_dir", "\(rel) leads outside the data folder")
        case .some(.unsafe): return ("unsafe_path", "\(rel) is not a plain path inside the data folder")
        }
    }

    /// A database given as {"root", "rel"} (arva_tools.bakta.native_database): the root is one of this Mac's database
    /// folders (arva.conf), the path stays inside it once links are resolved.
    static func databaseProblem(_ ref: Any?, databaseDirs: [String]) -> (code: String, detail: String)? {
        guard let ref = ref as? [String: Any], ref.count == 2, let root = ref["root"] as? String,
              let rel = ref["rel"] as? String else {
            return ("work_incomplete", "a database must be given as its folder and a path inside it")
        }
        guard NativeRelPath.isNormalisedAbsolute(root), !NativeRelPath.hasWhitespace(root) else {
            return ("unsafe_path", "\(root) is not a plain absolute folder")
        }
        guard databaseDirs.contains(root) else {
            return ("database_folder_unknown", "\(root) is not a database folder of this Mac's ARVA (arva.conf)")
        }
        switch NativeRelPath.check(rel, in: root) {
        case .none: return nil
        case .some(.missing): return ("input_missing", "\(rel) does not exist in the database folder")
        case .some(.outside): return ("outside_database_dir", "\(rel) leads outside the database folder")
        case .some(.unsafe): return ("unsafe_path", "\(rel) is not a plain path inside the database folder")
        }
    }

    static func baktaProblem(_ work: [String: Any], dataDir: String, executable: String,
                             databaseDirs: [String]) -> (code: String, detail: String)? {
        guard let workData = work["data_dir"] as? String, let workExe = work["executable"] as? String,
              let genome = work["genome"] as? String, let outDir = work["out_dir"] as? String,
              let tmpDir = work["tmp_dir"] as? String, let resultsDir = work["results_dir"] as? String,
              work["params"] is [String: Any], work["argv"] is [String], work["skip_options"] is [String],
              work["storage_id"] is String, work["database"] != nil, work.keys.contains("amr_data") else {
            return ("work_incomplete", "the work record lacks a field or has one of the wrong kind")
        }
        guard workData == dataDir else {
            return ("other_data_dir", "the work is for the data folder \(workData), this Mac's ARVA uses \(dataDir)")
        }
        guard workExe == executable else {
            return ("other_executable", "the work names \(workExe), this Mac's Bakta is \(executable)")
        }
        guard work["console_log"] as? String == baktaConsoleLog else { return ("unsafe_path", "unexpected log name") }
        for rel in [genome, outDir, tmpDir, resultsDir] where !NativeRelPath.isSafe(rel) {
            return ("unsafe_path", "\(rel) is not a plain path inside the data folder")
        }
        for rel in [genome, outDir, tmpDir] where !rel.hasPrefix(resultsDir + "/") {
            return ("unsafe_path", "\(rel) is not inside the job's folder \(resultsDir)")
        }
        for rel in [genome, tmpDir, resultsDir] {
            if let problem = inputProblem(rel, dataDir: dataDir) { return problem }
        }
        if NativeRelPath.check(outDir, in: dataDir, mustExist: false) != nil {
            return ("outside_data_dir", "Bakta's folder \(outDir) leads outside the data folder")
        }
        if let problem = databaseProblem(work["database"], databaseDirs: databaseDirs) { return problem }
        if let amr = work["amr_data"], !(amr is NSNull),
           let problem = databaseProblem(amr, databaseDirs: databaseDirs) { return problem }
        return nil
    }
}

/// The token ARVA.app gives the API (docs/plan-flye-nativo.md, "Token"): 32 random bytes in base64url without "=",
/// written 0600 and replaced atomically, a new one at each start of the executor.
enum NativeToken {
    static func make() -> String {
        var generator = SystemRandomNumberGenerator()   // arc4random on macOS: cryptographically secure
        let bytes = (0..<32).map { _ in UInt8.random(in: 0...255, using: &generator) }
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    /// The API's rule: 32-256 characters of [A-Za-z0-9_-].
    static func isValid(_ token: String) -> Bool {
        (32...256).contains(token.count) && token.unicodeScalars.allSatisfy {
            ($0 >= "A" && $0 <= "Z") || ($0 >= "a" && $0 <= "z") || ($0 >= "0" && $0 <= "9") || $0 == "-" || $0 == "_"
        }
    }

    /// Writes the token readable by this user only (created 0600, never wider), then renames it into place.
    static func write(_ token: String, to url: URL) throws {
        let fm = FileManager.default
        let dir = url.deletingLastPathComponent()
        try fm.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let temp = dir.appendingPathComponent(".native-executor.token.\(getpid())")
        unlink(temp.path)
        let fd = open(temp.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
        guard fd >= 0 else { throw CocoaError(.fileWriteNoPermission, userInfo: [NSFilePathErrorKey: temp.path]) }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        do {
            try handle.write(contentsOf: Data((token + "\n").utf8))
            try handle.close()
        } catch {
            unlink(temp.path)
            throw error
        }
        guard rename(temp.path, url.path) == 0 else {
            unlink(temp.path)
            throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: url.path])
        }
    }
}

/// What the bundled lock pins for the tool itself (.../<tool>-<version>-<build>.conda#sha256:<sha256>; Flye's is
/// built for osx-arm64, Bakta's is noarch).
struct NativeLockPin: Equatable {
    let version: String
    let build: String
    let sha256: String

    static func parse(_ text: String, tool: NativeTool = .flye) -> NativeLockPin? {
        let prefix = "https://conda.anaconda.org/bioconda/\(tool.lockSubdir)/\(tool.id)-"
        for line in text.components(separatedBy: "\n") {
            guard let hash = line.range(of: "#sha256:"), line.hasPrefix(prefix) else { continue }
            let url = String(line[..<hash.lowerBound])
            let sha = String(line[hash.upperBound...]).trimmingCharacters(in: .whitespaces)
            var name = (url as NSString).lastPathComponent
            for suffix in [".conda", ".tar.bz2"] where name.hasSuffix(suffix) { name.removeLast(suffix.count) }
            let parts = name.split(separator: "-", maxSplits: 2).map(String.init)   // tool, version, build
            guard parts.count == 3, sha.count == 64, sha.allSatisfy({ $0.isHexDigit }) else { return nil }
            return NativeLockPin(version: parts[1], build: parts[2], sha256: sha)
        }
        return nil
    }
}

/// The long options of a Flye --help text, as arva_tools.flye reads them (_FLAG: (?<![\w-])(--[a-z][a-z0-9-]*)).
enum NativeHelp {
    static func options(_ text: String) -> Set<String> {
        guard let regex = try? NSRegularExpression(pattern: "(?<![\\w-])(--[a-z][a-z0-9-]*)") else { return [] }
        let range = NSRange(text.startIndex..., in: text)
        var found = Set<String>()
        for match in regex.matches(in: text, range: range) {
            if let r = Range(match.range(at: 1), in: text) { found.insert(String(text[r])) }
        }
        return found
    }
}

/// A short command with its standard output and error kept apart (never on the main thread).
enum NativeCommand {
    struct Result {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    static func run(_ executable: String, _ arguments: [String], environment: [String: String],
                    directory: URL? = nil, timeout: TimeInterval) -> Result? {
        let process = Process()
        let out = Pipe()
        let err = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.environment = environment
        if let directory { process.currentDirectoryURL = directory }
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = out
        process.standardError = err
        let done = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in done.signal() }
        do { try process.run() } catch { return nil }
        var outData = Data()
        var errData = Data()
        let reads = DispatchGroup()
        reads.enter()
        DispatchQueue.global().async {
            outData = out.fileHandleForReading.readDataToEndOfFile()
            reads.leave()
        }
        reads.enter()
        DispatchQueue.global().async {
            errData = err.fileHandleForReading.readDataToEndOfFile()
            reads.leave()
        }
        if done.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            _ = done.wait(timeout: .now() + 2)
            return nil
        }
        _ = reads.wait(timeout: .now() + 5)
        return Result(status: process.terminationStatus, stdout: String(decoding: outData, as: UTF8.self),
                      stderr: String(decoding: errData, as: UTF8.self))
    }

    /// The environment of everything ARVA.app runs for "Flye for this Mac": the system's folders only on PATH, the
    /// given HOME, UTF-8, the temporary folder and the proxy settings (for the download); nothing else of the app's
    /// own environment (no ARVA_*, CONDA* or MAMBA* variables, no tokens).
    static func environment(home: String) -> [String: String] {
        let current = ProcessInfo.processInfo.environment
        var env = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": home, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"]
        if let tmp = current["TMPDIR"], tmp.hasPrefix("/") { env["TMPDIR"] = tmp }
        for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"] {
            if let value = current[key], !value.isEmpty { env[key] = value }
        }
        return env
    }
}

/// What `native.py <tool> facts` prints about the installed tool (sent as is when ARVA.app registers).
struct NativeFacts {
    let json: [String: Any]

    var tool: String? { json["tool"] as? String }
    var version: String? { json["version"] as? String }
    var package: [String: Any]? { json["package"] as? [String: Any] }
    var build: String? { package?["build"] as? String }
    var packageSha256: String? { package?["sha256"] as? String }
    var lockSha256: String? { json["lock_sha256"] as? String }
    var helpOptions: Set<String> { Set(json["help_options"] as? [String] ?? []) }
    var samtoolsHelper: Bool { json["samtools_helper"] as? Bool ?? false }

    /// The last line of the output that is a JSON object with this "tool".
    static func parse(_ stdout: String, tool: String = "flye") -> NativeFacts? {
        for line in stdout.components(separatedBy: "\n").reversed() where line.hasPrefix("{") {
            if let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
               object["tool"] as? String == tool {
                return NativeFacts(json: object)
            }
        }
        return nil
    }

    /// Runs the bundled native.py with the environment's Python (isolated, without writing bytecode into the app).
    static func load(tool: NativeTool = .flye, lock: URL? = nil) -> (facts: NativeFacts?, problem: String?) {
        guard let script = NativePaths.bundled(NativePaths.nativeScriptRel) else {
            return (nil, "native.py is missing from the app")
        }
        // Bakta's facts include its start-up checks (a dozen programs): more time than Flye's.
        guard let result = NativeCommand.run(tool.python,
                                             ["-I", "-B", script.path, tool.id, "facts", "--executable", tool.executable,
                                              "--lock", (lock ?? tool.installedLock).path],
                                             environment: NativeCommand.environment(home: AppPaths.home.path),
                                             directory: NativePaths.workDirEnsured, timeout: 600) else {
            return (nil, "native.py \(tool.id) facts did not finish")
        }
        guard result.status == 0, let facts = parse(result.stdout, tool: tool.id) else {
            return (nil, "native.py \(tool.id) facts: exit status \(result.status): \(String(result.stderr.suffix(1500)))")
        }
        return (facts, nil)
    }

    /// The comparison made after an installation: the version, build and package of the lock, the lock itself,
    /// flye-samtools beside flye (Flye), and the same long --help options as the release ARVA was written against.
    func problems(pin: NativeLockPin, lockSha256 expectedLock: String?, helpText: String,
                  tool: NativeTool = .flye) -> [String] {
        var out: [String] = []
        let name = tool.id
        // Bakta prints "bakta 1.12.2", Flye "2.9.6-b1802".
        let shown = (version ?? "").hasPrefix(name + " ") ? String((version ?? "").dropFirst(name.count + 1)) : (version ?? "")
        if !shown.hasPrefix(pin.version) { out.append("\(name) --version is \(version ?? "unreadable"), not \(pin.version)") }
        if build != pin.build { out.append("the installed build is \(build ?? "unknown"), the lock's is \(pin.build)") }
        if packageSha256 != pin.sha256 { out.append("the installed \(tool.name) package's sha256 is not the lock's") }
        if let expectedLock, lockSha256 != expectedLock { out.append("the recorded lock's sha256 is not the bundled lock's") }
        if tool == .flye && !samtoolsHelper { out.append("flye-samtools is not beside flye") }
        let expected = NativeHelp.options(helpText)
        let found = Set(helpOptions.filter { $0.hasPrefix("--") })
        if expected.isEmpty || found != expected {
            let extra = found.subtracting(expected).sorted().joined(separator: " ")
            let missing = expected.subtracting(found).sorted().joined(separator: " ")
            out.append("\(name) --help differs from the release ARVA expects (only here: \(extra.isEmpty ? "-" : extra); missing: \(missing.isEmpty ? "-" : missing))")
        }
        return out
    }
}

extension NativePaths {
    /// The work folder, created when needed (0700: the work records name the person's files).
    static var workDirEnsured: URL {
        try? FileManager.default.createDirectory(at: workDir, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        return workDir
    }
}

/// The SHA-256 of a file, with the system's shasum (no other library needed).
func nativeSha256(_ url: URL) -> String? {
    guard let result = NativeCommand.run("/usr/bin/shasum", ["-a", "256", url.path],
                                         environment: ["PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"], timeout: 60),
          result.status == 0, let first = result.stdout.split(separator: " ").first, first.count == 64 else { return nil }
    return String(first)
}

/// Installs "Flye for this Mac" (or "Bakta for this Mac", with `tool`): (1) micromamba for osx-arm64 with ARVA's own scripts/install-micromamba.sh (the
/// package's sha256 is pinned there) into a temporary folder; (2) micromamba create from the bundled osx-arm64 lock
/// only (--no-rc, link scripts off, its root prefix, HOME and caches in the temporary folder, as
/// scripts/conda_locks.py does); (3) conda_locks.py verify-env with the environment's own Python; (4) the facts of the
/// installed tool (native.py <tool> facts) compared with the lock and with the --help of the release ARVA expects. The temporary folder is
/// on the same disk as the environment (micromamba hard-links the files) and is removed at the end; a failed
/// installation removes the half-made environment.
final class NativeFlyeInstaller {
    enum Outcome {
        case installed(NativeFacts)
        case failed(String)
        case cancelled
    }

    var onOutput: ((String) -> Void)?
    var onStep: ((String) -> Void)?
    var onFinish: ((Outcome) -> Void)?

    private var task: ShellTask?
    private var cancelled = false
    private var finished = false
    /// The last step runs on a background queue (no task to stop): a cancel then waits for it.
    private var checking = false
    private let temp: URL
    private var micromambaSource = ""
    let tool: NativeTool

    init(tool: NativeTool = .flye) {
        self.tool = tool
        temp = NativePaths.toolsDir.appendingPathComponent(".arva-install-\(UUID().uuidString.lowercased())", isDirectory: true)
    }

    /// Why "<tool> for this Mac" cannot be installed here, or nil.
    static func preflight(tool: NativeTool = .flye) -> String? {
        guard NativePaths.platformSupported else {
            return L("\(tool.name) for this Mac needs a Mac with Apple silicon (M1 or later), with ARVA.app running natively (not through Rosetta).",
                     "\(tool.name) para esta Mac necesita una Mac con Apple silicon (M1 o posterior), con ARVA.app ejecutándose de forma nativa (no con Rosetta).")
        }
        for rel in NativePaths.bundledFiles {
            guard let url = NativePaths.bundled(rel), FileManager.default.fileExists(atPath: url.path) else {
                return RuntimeError.missingBundle("Resources/native/\(rel)").errorDescription
            }
        }
        let prefix = tool.envPrefix.path
        if NativeRelPath.hasWhitespace(prefix) || NativeRelPath.hasControlCharacters(prefix) {
            return L("ARVA runs native tools only from paths without spaces, and your home folder's has some (\(AppPaths.home.path)): \(tool.name) for this Mac cannot be installed for this user.",
                     "ARVA ejecuta herramientas nativas solo desde rutas sin espacios, y la de tu carpeta personal los tiene (\(AppPaths.home.path)): \(tool.name) para esta Mac no se puede instalar para este usuario.")
        }
        return nil
    }

    /// Whether something is already in the environment's place (it is replaced by an installation).
    static func somethingInstalled(tool: NativeTool = .flye) -> Bool { FileManager.default.fileExists(atPath: tool.envPrefix.path) }

    func start() {
        if let problem = Self.preflight(tool: tool) {
            finish(.failed(problem))
            return
        }
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: NativePaths.logsDir, withIntermediateDirectories: true)
            try fm.createDirectory(at: temp, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            if fm.fileExists(atPath: tool.envPrefix.path) {
                output(L("Removing the previous environment \(tool.envPrefix.path)\n",
                         "Se quita el entorno anterior \(tool.envPrefix.path)\n"))
                try fm.removeItem(at: tool.envPrefix)
            }
            try fm.createDirectory(at: tool.envPrefix.deletingLastPathComponent(), withIntermediateDirectories: true)
        } catch {
            finish(.failed(error.localizedDescription))
            return
        }
        installMicromamba()
    }

    func cancel() {
        guard !finished else { return }
        cancelled = true
        if let task {
            task.terminateAll()
        } else if !checking {
            finish(.cancelled)
        }
    }

    private func output(_ text: String) { onOutput?(text) }

    private func step(_ en: String, _ es: String) {
        let text = L(en, es)
        onStep?(text)
        output("\n== \(text)\n")
    }

    private func runStep(_ executable: String, _ arguments: [String], environment: [String: String], log: String,
                         then next: @escaping (Int32, String) -> Void) {
        guard !cancelled else {
            finish(.cancelled)
            return
        }
        output("$ " + ([executable] + arguments).map { NativeRelPath.hasWhitespace($0) ? shellQuote($0) : $0 }
            .joined(separator: " ") + "\n")
        let task = ShellTask(executable: executable, arguments: arguments, directory: temp, environment: environment,
                             logFile: NativePaths.logsDir.appendingPathComponent("\(tool.id)-\(log)"))
        task.onOutput = { [weak self] text in self?.output(text) }
        task.onExit = { [weak self] status, text in
            guard let self else { return }
            self.task = nil
            if self.cancelled {
                self.finish(.cancelled)
            } else {
                next(status, text)
            }
        }
        do {
            try task.start()
            self.task = task
        } catch {
            finish(.failed(error.localizedDescription))
        }
    }

    private func installMicromamba() {
        step("Downloading micromamba (its checksum is checked)…", "Descargando micromamba (se comprueba su suma de verificación)…")
        guard let script = NativePaths.bundled(NativePaths.micromambaRel) else { return finish(.failed("install-micromamba.sh")) }
        let prefix = temp.appendingPathComponent("micromamba", isDirectory: true)
        let home = temp.appendingPathComponent("home", isDirectory: true)
        try? FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        runStep("/bin/bash", [script.path, prefix.path], environment: NativeCommand.environment(home: home.path),
                log: "1-micromamba.log") { [weak self] status, _ in
            guard let self else { return }
            let exe = prefix.appendingPathComponent("bin/micromamba").path
            guard status == 0, FileManager.default.isExecutableFile(atPath: exe) else {
                return self.finish(.failed(L("micromamba could not be installed (exit status \(status)).",
                                             "No se pudo instalar micromamba (estado de salida \(status)).")))
            }
            self.micromambaSource = (try? String(contentsOf: prefix.appendingPathComponent("SOURCE"), encoding: .utf8)) ?? ""
            self.createEnvironment(micromamba: exe)
        }
    }

    private func createEnvironment(micromamba: String) {
        step("Installing \(tool.downloadEN) from ARVA's lock (conda.anaconda.org)…",
             "Instalando \(tool.downloadES) desde el lock de ARVA (conda.anaconda.org)…")
        guard let lock = NativePaths.bundled(tool.lockRel) else { return finish(.failed("osx-arm64.lock")) }
        let root = temp.appendingPathComponent("root", isDirectory: true)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        var env = NativeCommand.environment(home: root.path)
        env["MAMBA_ROOT_PREFIX"] = root.path
        env["XDG_CACHE_HOME"] = root.appendingPathComponent("cache").path
        runStep(micromamba, ["create", "--yes", "--no-rc", "--skip-run-link-scripts", "--prefix",
                             tool.envPrefix.path, "--file", lock.path],
                environment: env, log: "2-environment.log") { [weak self] status, _ in
            guard let self else { return }
            guard status == 0, FileManager.default.isExecutableFile(atPath: self.tool.python) else {
                return self.finish(.failed(L("micromamba could not create \(self.tool.name)'s environment from the lock (exit status \(status)).",
                                             "micromamba no pudo crear el entorno de \(self.tool.name) desde el lock (estado de salida \(status)).")))
            }
            self.verifyEnvironment()
        }
    }

    private func verifyEnvironment() {
        step("Checking every installed package against the lock…", "Comprobando cada paquete instalado contra el lock…")
        guard let script = NativePaths.bundled(NativePaths.condaLocksRel) else { return finish(.failed("conda_locks.py")) }
        runStep(tool.python, ["-I", "-B", script.path, "verify-env", tool.id, tool.envPrefix.path,
                              "--platform", "osx-arm64"],
                environment: NativeCommand.environment(home: temp.path), log: "3-verify-env.log") { [weak self] status, _ in
            guard let self else { return }
            guard status == 0 else {
                return self.finish(.failed(L("The installed packages are not exactly the lock's (conda_locks.py verify-env, exit status \(status)).",
                                             "Los paquetes instalados no son exactamente los del lock (conda_locks.py verify-env, estado de salida \(status)).")))
            }
            self.checkTool()
        }
    }

    private func checkTool() {
        step("Checking \(tool.name) (version, build, --help)…", "Comprobando \(tool.name) (versión, compilación, --help)…")
        let source = micromambaSource
        let tool = self.tool
        checking = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let outcome = Self.recordAndCheck(tool: tool, micromambaSource: source)
            DispatchQueue.main.async {
                guard let self else { return }
                self.checking = false
                if self.cancelled { return self.finish(.cancelled) }
                switch outcome {
                case .success(let facts):
                    self.output((String(data: (try? JSONSerialization.data(withJSONObject: facts.json, options: [.sortedKeys])) ?? Data(),
                                        encoding: .utf8) ?? "") + "\n")
                    self.finish(.installed(facts))
                case .failure(let error):
                    self.finish(.failed(error.message))
                }
            }
        }
    }

    struct CheckError: Error { let message: String }

    /// Copies the lock into the environment, reads the facts and compares them; writes the installation record.
    private static func recordAndCheck(tool: NativeTool, micromambaSource: String) -> Result<NativeFacts, CheckError> {
        let fm = FileManager.default
        guard let lock = NativePaths.bundled(tool.lockRel), let help = NativePaths.bundled(tool.helpRel),
              let lockText = try? String(contentsOf: lock, encoding: .utf8),
              let helpText = try? String(contentsOf: help, encoding: .utf8),
              let pin = NativeLockPin.parse(lockText, tool: tool) else {
            return .failure(CheckError(message: RuntimeError.missingBundle("Resources/native").errorDescription ?? ""))
        }
        do {
            try fm.createDirectory(at: tool.recordDir, withIntermediateDirectories: true)
            try? fm.removeItem(at: tool.installedLock)
            try fm.copyItem(at: lock, to: tool.installedLock)
        } catch {
            return .failure(CheckError(message: error.localizedDescription))
        }
        let (loaded, problem) = NativeFacts.load(tool: tool)
        guard let facts = loaded else { return .failure(CheckError(message: problem ?? "native.py \(tool.id) facts")) }
        let lockSha = nativeSha256(lock)
        let problems = facts.problems(pin: pin, lockSha256: lockSha, helpText: helpText, tool: tool)
        guard problems.isEmpty else {
            return .failure(CheckError(message: L("The installed \(tool.name) is not the one ARVA expects: ", "El \(tool.name) instalado no es el que ARVA espera: ")
                                       + problems.joined(separator: "; ")))
        }
        let helpName = (tool.helpRel as NSString).lastPathComponent
        var verified = ["conda_locks.py verify-env", "\(tool.id) --version", "\(tool.id) --help options = \(helpName)"]
        if tool == .flye { verified.append("flye-samtools beside flye") }
        if tool == .bakta { verified.append("Bakta's start-up checks of its programs (native.py bakta facts)") }
        let record: [String: Any] = [
            "installed_at": ISO8601DateFormatter().string(from: Date()),
            "app_version": AppInfo.version, "app_commit": AppInfo.commit, "tool": tool.id,
            "platform": "osx-arm64", "lock": tool.lockRel, "lock_sha256": lockSha ?? NSNull(),
            "\(tool.id)_version": facts.version ?? NSNull(), "build": facts.build ?? NSNull(),
            "package_sha256": facts.packageSha256 ?? NSNull(),
            "micromamba": micromambaSource.trimmingCharacters(in: .whitespacesAndNewlines),
            "verified": verified,
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: tool.installRecord, options: .atomic)
        } catch {
            return .failure(CheckError(message: error.localizedDescription))
        }
        return .success(facts)
    }

    private func finish(_ outcome: Outcome) {
        guard !finished else { return }
        finished = true
        let fm = FileManager.default
        try? fm.removeItem(at: temp)
        switch outcome {
        case .installed:
            output(L("\n\(tool.name) for this Mac is installed.\n", "\n\(tool.name) para esta Mac está instalado.\n"))
        case .failed(let message):
            output("\n" + message + "\n")
            try? fm.removeItem(at: tool.envPrefix)
        case .cancelled:
            output(L("\nCancelled; nothing was kept.\n", "\nCancelado; no se conservó nada.\n"))
            try? fm.removeItem(at: tool.envPrefix)
        }
        onFinish?(outcome)
    }

    /// Removes the environment, only when ARVA.app made it (its record is there); nothing else is touched.
    static func remove(tool: NativeTool = .flye) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: tool.envPrefix.path) else { return }
        guard fm.fileExists(atPath: tool.installRecord.path) else {
            throw CocoaError(.fileWriteNoPermission, userInfo: [NSLocalizedDescriptionKey:
                L("\(tool.envPrefix.path) was not installed by ARVA.app, so it is left as it is.",
                  "\(tool.envPrefix.path) no lo instaló ARVA.app, así que se deja como está.")])
        }
        try fm.removeItem(at: tool.envPrefix)
    }
}

/// `ARVA --install-native-flye` / `--install-native-bakta` and `--remove-native-flye` / `--remove-native-bakta`: the
/// same installation as the menu, without a window (used by .github/workflows/mac-app.yml to check the app's own
/// installer on a real Mac).
enum NativeFlyeCLI {
    static func install(tool: NativeTool = .flye) -> Int32 {
        FileHandle.standardOutput.write(Data("ARVA.app \(AppInfo.version): installing \(tool.name) for this Mac into \(tool.envPrefix.path)\n".utf8))
        let installer = NativeFlyeInstaller(tool: tool)
        var result: Int32?
        installer.onOutput = { text in
            FileHandle.standardOutput.write(Data(text.utf8))
        }
        installer.onFinish = { outcome in
            switch outcome {
            case .installed: result = 0
            case .failed: result = 1
            case .cancelled: result = 2
            }
        }
        installer.start()
        while result == nil {
            _ = RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.2))
        }
        return result ?? 1
    }

    static func remove(tool: NativeTool = .flye) -> Int32 {
        do {
            try NativeFlyeInstaller.remove(tool: tool)
            print("Removed \(tool.envPrefix.path)")
            return 0
        } catch {
            print(error.localizedDescription)
            return 1
        }
    }
}
