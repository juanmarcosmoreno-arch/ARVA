import AppKit

/// Docker Desktop: whether it is installed, whether its engine answers, opening and quitting it.
enum DockerDesktop {
    static let bundleID = "com.docker.docker"
    static let installPage = URL(string: "https://docs.docker.com/desktop/setup/install/mac-install/")!

    static var appURL: URL? {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) { return url }
        for path in ["/Applications/Docker.app", AppPaths.home.appendingPathComponent("Applications/Docker.app").path]
        where FileManager.default.fileExists(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        return nil
    }

    static var cli: String? { ShellEnvironment.which("docker") }

    /// Installed: Docker Desktop's app, or at least a docker command (another engine that answers is fine too).
    static var isInstalled: Bool { appURL != nil || cli != nil }

    static var isAppRunning: Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).isEmpty
    }

    /// `docker info` answers (never call on the main thread).
    static func engineReady() -> Bool {
        guard let cli else { return false }
        guard let result = ShellTask.run(cli, ["info", "--format", "{{.ServerVersion}}"], timeout: 20) else { return false }
        return result.status == 0
    }

    /// Opens Docker Desktop in the background; returns false when it is not there.
    static func open(completion: @escaping (Bool) -> Void) {
        guard let url = appURL else {
            completion(false)
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        NSWorkspace.shared.openApplication(at: url, configuration: configuration) { app, error in
            DispatchQueue.main.async { completion(app != nil && error == nil) }
        }
    }

    static func quit() {
        for app in NSRunningApplication.runningApplications(withBundleIdentifier: bundleID) {
            app.terminate()
        }
    }
}

/// ARVA's web server on this computer (nginx in the web container, which passes /health and /api to the API).
enum ArvaServer {
    static let base = URL(string: "http://localhost:8080/")!

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 4
        config.timeoutIntervalForResource = 6
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config)
    }()

    /// /health answers with ARVA's JSON (`{"status": "ok"|"degraded", "version": ...}`): ARVA is up. A degraded
    /// status is still up: Settings → Storage explains it.
    static func checkHealth(completion: @escaping (Bool) -> Void) {
        let task = session.dataTask(with: base.appendingPathComponent("health")) { data, response, _ in
            var ok = false
            if let http = response as? HTTPURLResponse, http.statusCode == 200, let data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any], json["status"] is String {
                ok = true
            }
            DispatchQueue.main.async { completion(ok) }
        }
        task.resume()
    }

    /// One of ARVA's API paths ("api/v1/jobs?status=running", relative to `base`), parsed as JSON; nil when it does not
    /// answer 200 with JSON (ARVA not answering, or accounts are on and this request has no session).
    static func getJSON(_ path: String, completion: @escaping (Any?) -> Void) {
        guard let url = URL(string: path, relativeTo: base)?.absoluteURL, WebPolicy.classify(url) == .local else {
            DispatchQueue.main.async { completion(nil) }
            return
        }
        let task = session.dataTask(with: url) { data, response, _ in
            var object: Any?
            if let http = response as? HTTPURLResponse, http.statusCode == 200, let data {
                object = try? JSONSerialization.jsonObject(with: data)
            }
            DispatchQueue.main.async { completion(object) }
        }
        task.resume()
    }

    /// The analyses running or waiting to run (GET /api/v1/dashboard, `jobs_running`), or nil when unknown (ARVA not
    /// answering, or accounts are on and this request has no session: the web view's own request is tried first).
    static func activeJobs(completion: @escaping (Int?) -> Void) {
        let task = session.dataTask(with: base.appendingPathComponent("api/v1/dashboard")) { data, response, _ in
            var count: Int?
            if let http = response as? HTTPURLResponse, http.statusCode == 200, let data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let running = json["jobs_running"] as? Int {
                count = running
            }
            DispatchQueue.main.async { completion(count) }
        }
        task.resume()
    }
}

/// Whether ARVA answers while it runs (GET /health, every `interval` seconds): it is reported as not responding after
/// `failuresToReport` failed checks in a row (one can be a slow answer, or the Mac waking up), and as back at the first
/// answer after that. Closing Docker Desktop stops ARVA this way. When it opens again, ARVA's containers may come back
/// by themselves (docker-compose.yml gives them `restart: unless-stopped`; not yet seen on a real Mac): the page is then
/// reloaded at the first answer when `shouldReload` says so. Otherwise the person's Try Again starts ARVA as opening
/// the app does.
struct ServerWatch {
    static let interval: TimeInterval = 15
    static let failuresToReport = 2
    /// How long ARVA must have stopped answering for the page to be reloaded when it answers again, although the page
    /// shown is still ARVA's own: long enough to mean it was stopped (Docker Desktop closed), not only busy. Two /health
    /// checks that time out while ARVA works hard take about one or two intervals.
    static let reloadAfterDown: TimeInterval = 60

    enum Change: Equatable {
        case wentDown
        case cameBack
    }

    private(set) var failures = 0
    private(set) var isDown = false
    /// When the failed checks in a row began (nil while ARVA answers).
    private(set) var failingSince: Date?
    /// At `.cameBack`: how long ARVA did not answer, from the first failed check of that series.
    private(set) var lastOutage: TimeInterval = 0

    mutating func update(answered: Bool, now: Date = Date()) -> Change? {
        if answered {
            let since = failingSince
            failures = 0
            failingSince = nil
            guard isDown else { return nil }
            isDown = false
            lastOutage = max(0, now.timeIntervalSince(since ?? now))
            return .cameBack
        }
        if failures == 0 { failingSince = now }
        failures += 1
        guard !isDown, failures >= ServerWatch.failuresToReport else { return nil }
        isDown = true
        return .wentDown
    }

    /// Whether to reload the page when ARVA answers again. Reloading discards what the person was doing in the page (an
    /// open dialog, a form being filled, an upload), so only when the window does not show ARVA's own page (the
    /// "ARVA is not answering" page after a load that failed, or nothing), or when ARVA was down for at least
    /// `reloadAfterDown` (it was stopped, so the page's requests failed meanwhile and its data may be out of date).
    static func shouldReload(showsARVAPage: Bool, downFor: TimeInterval) -> Bool {
        !showsARVAPage || downFor >= reloadAfterDown
    }
}
