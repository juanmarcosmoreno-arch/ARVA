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
