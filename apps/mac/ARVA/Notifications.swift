import Foundation
import UserNotifications

/// One analysis job as GET /api/v1/jobs and GET /api/v1/jobs/{id} give it (apps/api/app/schemas/schemas.py,
/// AnalysisJobRead), only what a notification needs. `status` is one of JobStatus (apps/api/app/models/analysis_job.py):
/// pending, running, completed, failed, cancelled.
struct JobSnapshot: Equatable {
    let id: String
    let status: String
    let tool: String
    let jobType: String
    let sampleId: String?

    /// The fields asked for (the page's own request keeps only these, so a long job log is not passed around).
    static let keys = ["id", "status", "tool_name", "job_type", "sample_id"]

    /// The jobs with one status, newest first (GET /api/v1/jobs takes status and a limit of at most 500).
    static func listPath(status: String) -> String { "api/v1/jobs?status=\(status)&limit=200" }

    static func detailPath(id: String) -> String { "api/v1/jobs/\(id)" }

    init(id: String, status: String, tool: String = "", jobType: String = "", sampleId: String? = nil) {
        self.id = id
        self.status = status
        self.tool = tool
        self.jobType = jobType
        self.sampleId = sampleId
    }

    /// A job from its JSON object; nil when it has no usable id or status. An id that is not a plain identifier
    /// (letters, digits, - and _: ARVA's ids are UUIDs) is never put in a URL.
    init?(json: Any?) {
        guard let object = json as? [String: Any], let id = object["id"] as? String, JobSnapshot.isPlainID(id),
              let status = object["status"] as? String, !status.isEmpty else { return nil }
        self.id = id
        self.status = status
        tool = object["tool_name"] as? String ?? ""
        jobType = object["job_type"] as? String ?? ""
        let sample = object["sample_id"] as? String
        sampleId = sample.flatMap { JobSnapshot.isPlainID($0) ? $0 : nil }
    }

    /// The jobs of a JSON array; nil when it is not an array (the request failed or answered something else).
    static func list(from json: Any?) -> [JobSnapshot]? {
        guard let array = json as? [Any] else { return nil }
        return array.compactMap { JobSnapshot(json: $0) }
    }

    static func isPlainID(_ text: String) -> Bool {
        !text.isEmpty && text.count <= 64
            && text.unicodeScalars.allSatisfy { $0.isASCII && (CharacterSet.alphanumerics.contains($0) || $0 == "-" || $0 == "_") }
    }

    var isActive: Bool { status == "pending" || status == "running" }
}

/// Which analyses ended between two looks at the running and waiting jobs. Only jobs seen running or waiting are
/// followed, so nothing is said about analyses that ended before ARVA.app was watching.
struct JobWatch {
    /// A job that left the list is looked up on its own; after this many lookups without an answer it is dropped.
    static let lookupsBeforeDropping = 3

    /// The running and waiting jobs seen the last time, by id.
    private(set) var active: [String: JobSnapshot] = [:]
    private var failedLookups: [String: Int] = [:]

    var isWatching: Bool { !active.isEmpty }

    /// The jobs running or waiting now (other statuses are ignored). Returns, in a stable order, the jobs that were
    /// running or waiting the last time and are not in the list now: they ended (or left the list), so each is looked
    /// up on its own, then given to `stillActive`, `lookupFailed` or nothing (it ended: tell the person).
    mutating func update(active now: [JobSnapshot]) -> [JobSnapshot] {
        var current: [String: JobSnapshot] = [:]
        for job in now where job.isActive && current[job.id] == nil { current[job.id] = job }
        let gone = active.values.filter { current[$0.id] == nil }.sorted { $0.id < $1.id }
        active = current
        for id in Array(failedLookups.keys) where current[id] != nil { failedLookups[id] = nil }
        return gone
    }

    /// A job that left the list but still runs or waits (there were more than the list shows): followed again.
    mutating func stillActive(_ job: JobSnapshot) {
        active[job.id] = job
        failedLookups[job.id] = nil
    }

    /// A job whose lookup got no answer (ARVA busy or not answering): followed again, at most `lookupsBeforeDropping`
    /// times in a row. Returns whether it is still followed.
    @discardableResult
    mutating func lookupFailed(_ job: JobSnapshot) -> Bool {
        let count = (failedLookups[job.id] ?? 0) + 1
        if count >= JobWatch.lookupsBeforeDropping {
            failedLookups[job.id] = nil
            return false
        }
        failedLookups[job.id] = count
        active[job.id] = job
        return true
    }
}

/// The notification for an analysis that ended: "ARVA: <analysis> finished — <sample>".
struct JobNotice: Equatable {
    let id: String
    let title: String
    let body: String
    /// The page of the job's sample in ARVA ("samples/<id>"), nil for a project-level job.
    let path: String?

    /// What to call the analysis: the tool's name (Flye, fastp, Bakta…), "Import" for ARVA's own import of a folder
    /// (its tool name is arva-import, apps/api/app/services/jobs.py), else the job type in words.
    static func analysisName(tool: String, jobType: String) -> String {
        let name = tool.trimmingCharacters(in: .whitespacesAndNewlines)
        if name == "arva-import" { return L("Import", "Importación") }
        if !name.isEmpty { return name }
        let type = jobType.replacingOccurrences(of: "_", with: " ").trimmingCharacters(in: .whitespaces)
        return type.isEmpty ? L("Analysis", "Análisis") : type
    }

    /// The notice for a job that was `before` (running or waiting) and is now `after`, with its sample's code when
    /// known. nil while it still runs or waits, for a job cancelled before it started (whoever cancelled it knows), and
    /// for a status ARVA does not have.
    static func make(before: JobSnapshot, after: JobSnapshot, sample: String?) -> JobNotice? {
        let name = analysisName(tool: after.tool.isEmpty ? before.tool : after.tool,
                                jobType: after.jobType.isEmpty ? before.jobType : after.jobType)
        let what: String
        switch after.status {
        case "completed": what = L("ARVA: \(name) finished", "ARVA: \(name) terminó")
        case "failed": what = L("ARVA: \(name) failed", "ARVA: \(name) falló")
        case "cancelled":
            guard before.status == "running" else { return nil }
            what = L("ARVA: \(name) cancelled", "ARVA: \(name) se canceló")
        default: return nil
        }
        let code = sample?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let title = code.isEmpty ? what : "\(what) — \(code)"
        let sampleId = after.sampleId ?? before.sampleId
        let path = sampleId.map { "samples/\($0)" }
        let body = path == nil ? L("Click to open ARVA.", "Haz clic para abrir ARVA.")
            : L("Click to see the sample in ARVA.", "Haz clic para ver la muestra en ARVA.")
        return JobNotice(id: after.id, title: title, body: body, path: path)
    }
}

/// macOS notifications (UserNotifications) when an analysis ends, while ARVA.app is open. On or off in the ARVA menu
/// (kept in UserDefaults); macOS's own permission comes first, and a "no" there is respected: the app then only says
/// where to change it. Notifications are made on this Mac only: nothing is sent anywhere.
final class AnalysisNotifier: NSObject, UNUserNotificationCenterDelegate {
    static let enabledKey = "ARVA.notifyAnalyses"
    /// The first-launch question was asked (once).
    static let askedKey = "ARVA.notifyAnalysesAsked"

    static var isEnabled: Bool {
        get { UserDefaults.standard.object(forKey: enabledKey) as? Bool ?? false }
        set { UserDefaults.standard.set(newValue, forKey: enabledKey) }
    }

    /// Called on the main thread with the notice's path when the person clicks a notification.
    var onOpen: ((String?) -> Void)?

    private var center: UNUserNotificationCenter { UNUserNotificationCenter.current() }

    /// Set before the app finishes launching, so that a click that opens the app is delivered too.
    func install() {
        center.delegate = self
    }

    /// Asks macOS (its own dialog, the first time only); calls back on the main thread with whether notifications may
    /// be shown.
    func requestPermission(_ completion: @escaping (Bool) -> Void) {
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            DispatchQueue.main.async { completion(granted) }
        }
    }

    /// Whether macOS still lets the app notify (System Settings → Notifications can turn it off at any time).
    func isAllowed(_ completion: @escaping (Bool) -> Void) {
        center.getNotificationSettings { settings in
            let status = settings.authorizationStatus
            let allowed = status == .authorized || status == .provisional
            DispatchQueue.main.async { completion(allowed) }
        }
    }

    func post(_ notice: JobNotice) {
        let content = UNMutableNotificationContent()
        content.title = notice.title
        content.body = notice.body
        content.sound = .default
        if let path = notice.path { content.userInfo = ["path": path] }
        let request = UNNotificationRequest(identifier: "arva-job-" + notice.id, content: content, trigger: nil)
        center.add(request) { _ in }
    }

    // MARK: UNUserNotificationCenterDelegate

    /// Shown also while ARVA.app is in front (the person may be in another window or page).
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let path = response.notification.request.content.userInfo["path"] as? String
        DispatchQueue.main.async { [weak self] in self?.onOpen?(path) }
        completionHandler()
    }
}
