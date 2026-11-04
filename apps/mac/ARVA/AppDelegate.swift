import AppKit
import WebKit

/// Opening ARVA: Docker Desktop first (opened and waited for when needed), then the launcher (the first-run questions
/// in Terminal for a new person, scripts/start.sh --no-setup in the background otherwise), then ARVA in its own window.
/// Quitting asks whether to stop ARVA too.
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuItemValidation {
    private enum Phase { case idle, preparing, waitingDocker, firstRun, starting, waitingHealth, running, failed, stopping }

    private static let quitDockerKey = "ARVA.quitDockerOnStop"
    private static let repository = URL(string: "https://github.com/juanmarcosmoreno-arch/ARVA")!

    private var phase: Phase = .idle
    private var splash: StartupWindow?
    private var mainWeb: WebWindowController?
    private var otherWebs: [WebWindowController] = []
    private let webConfiguration = WebWindowController.makeConfiguration()
    private var startTask: ShellTask?
    private var stopTask: ShellTask?
    private var pollTimer: Timer?
    private var watchdog: Timer?
    /// Asks ARVA, while it runs, whether analyses are running or waiting (SleepGuard).
    private var sleepTimer: Timer?
    private let sleepGuard = SleepGuard()
    /// The analyses running or waiting at the last SleepGuard poll (nil before the first answer).
    private var lastActiveCount: Int?
    /// Asks every 30 seconds, while analyses run or were running, which ones ended (macOS notifications).
    private var jobTimer: Timer?
    private var jobWatch = JobWatch()
    private var jobPollInFlight = false
    private let notifier = AnalysisNotifier()
    /// Asks every 15 seconds whether ARVA answers, to say so when it stops (Docker Desktop closed).
    private var healthTimer: Timer?
    private var serverWatch = ServerWatch()
    private var notRespondingAlert: NSAlert?
    private var attempt = 0
    /// Docker Desktop was opened by this app (so quitting may offer to close it again).
    private var launchedDocker = false
    private var terminating = false
    /// The quit dialog is open: the start waits (no new window or dialog) until it is answered.
    private var quitPending = false
    private var deferredError: (title: String, message: String, offerSetup: Bool)?
    /// Everything shown under Details for the last start or stop, for "Copy details".
    private var log = ""

    // MARK: Application

    func applicationWillFinishLaunching(_ notification: Notification) {
        notifier.onOpen = { [weak self] path in self?.openFromNotification(path) }
        notifier.install()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.build()
        sleepGuard.onChange = { [weak self] active in self?.showSleepStatus(active) }
        begin()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            if phase == .running, let mainWeb { mainWeb.show() } else { splash?.show() }
        }
        return true
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        stopSleepWatch()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminating { return .terminateNow }
        switch phase {
        case .idle, .preparing, .waitingDocker, .failed:
            return .terminateNow
        case .stopping:
            return .terminateCancel
        case .firstRun, .starting, .waitingHealth, .running:
            askToStop()
            return .terminateLater
        }
    }

    // MARK: Starting

    private func makeSplash() -> StartupWindow {
        let window = StartupWindow()
        window.onCancel = { [weak self] in self?.cancelStart() }
        splash = window
        return window
    }

    private func note(_ text: String) {
        log += text
        splash?.appendDetails(text)
    }

    private func stopTimers() {
        pollTimer?.invalidate()
        pollTimer = nil
        watchdog?.invalidate()
        watchdog = nil
        stopSleepWatch()
    }

    // MARK: Keeping the Mac awake while analyses run

    /// While ARVA runs: ask every minute whether analyses are running or waiting, and hold or release the sleep
    /// assertion accordingly (the first question a few seconds after ARVA opens). The same watch also asks whether
    /// ARVA still answers (ServerWatch) and, with notifications on, which analyses ended (JobWatch).
    private func startSleepWatch() {
        stopSleepWatch()
        sleepTimer = commonTimer(withTimeInterval: SleepGuard.pollInterval, repeats: true) { [weak self] _ in
            self?.pollActiveJobs()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in self?.pollActiveJobs() }
        healthTimer = commonTimer(withTimeInterval: ServerWatch.interval, repeats: true) { [weak self] _ in
            self?.checkServer()
        }
        jobTimer = commonTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.pollJobs() }
        // macOS may have been told "no" since the last time (System Settings → Notifications): that is respected.
        if AnalysisNotifier.isEnabled {
            notifier.isAllowed { allowed in
                if !allowed { AnalysisNotifier.isEnabled = false }
            }
        }
    }

    private func stopSleepWatch() {
        sleepTimer?.invalidate()
        sleepTimer = nil
        sleepGuard.release()
        healthTimer?.invalidate()
        healthTimer = nil
        jobTimer?.invalidate()
        jobTimer = nil
        lastActiveCount = nil
        jobWatch = JobWatch()
        jobPollInFlight = false
        serverWatch = ServerWatch()
        closeNotRespondingAlert()
    }

    private func pollActiveJobs() {
        guard phase == .running, sleepTimer != nil else { return }
        countActiveJobs { [weak self] count in
            guard let self, self.phase == .running, self.sleepTimer != nil else { return }
            if let count { self.lastActiveCount = count }
            self.sleepGuard.update(activeJobs: count)
        }
    }

    // MARK: Notifications when analyses end

    /// Every 30 seconds while analyses run or are followed (none of this while notifications are off): the running and
    /// waiting jobs, compared with the last ones; each job that left the list is looked up and, once ended, notified.
    private func pollJobs() {
        guard phase == .running, jobTimer != nil, AnalysisNotifier.isEnabled, !jobPollInFlight else { return }
        guard (lastActiveCount ?? 0) > 0 || jobWatch.isWatching else { return }
        jobPollInFlight = true
        let current = attempt
        fetchActiveJobs { [weak self] jobs in
            guard let self, current == self.attempt, self.phase == .running else { return }
            guard let jobs else {
                self.jobPollInFlight = false
                return
            }
            let ended = self.jobWatch.update(active: jobs)
            self.resolveEnded(ended, attempt: current) { [weak self] in self?.jobPollInFlight = false }
        }
    }

    /// The running jobs and the waiting ones; nil when either list could not be read (then nothing is compared, so a
    /// failed request never looks like analyses that ended).
    private func fetchActiveJobs(_ completion: @escaping ([JobSnapshot]?) -> Void) {
        apiJSON(JobSnapshot.listPath(status: "running"), keys: JobSnapshot.keys) { [weak self] runningJSON in
            guard let self, let running = JobSnapshot.list(from: runningJSON) else {
                completion(nil)
                return
            }
            self.apiJSON(JobSnapshot.listPath(status: "pending"), keys: JobSnapshot.keys) { pendingJSON in
                guard let pending = JobSnapshot.list(from: pendingJSON) else {
                    completion(nil)
                    return
                }
                completion(running + pending)
            }
        }
    }

    /// Looks up, one after the other, the jobs that left the list, and notifies the ones that ended.
    private func resolveEnded(_ ended: [JobSnapshot], attempt current: Int, done: @escaping () -> Void) {
        guard let job = ended.first, current == attempt, phase == .running else {
            done()
            return
        }
        let rest = Array(ended.dropFirst())
        apiJSON(JobSnapshot.detailPath(id: job.id), keys: JobSnapshot.keys) { [weak self] object in
            guard let self else { return }
            guard current == self.attempt else {
                done()
                return
            }
            guard let now = JobSnapshot(json: object), now.id == job.id else {
                self.jobWatch.lookupFailed(job)
                self.resolveEnded(rest, attempt: current, done: done)
                return
            }
            if now.isActive {
                self.jobWatch.stillActive(now)
                self.resolveEnded(rest, attempt: current, done: done)
                return
            }
            self.sampleCode(now.sampleId ?? job.sampleId) { code in
                if AnalysisNotifier.isEnabled, let notice = JobNotice.make(before: job, after: now, sample: code) {
                    self.notifier.post(notice)
                }
                self.resolveEnded(rest, attempt: current, done: done)
            }
        }
    }

    /// The code of a sample (GET /api/v1/samples/{id}, `sample_code`), for the notification; nil when unknown.
    private func sampleCode(_ sampleId: String?, _ completion: @escaping (String?) -> Void) {
        guard let sampleId, JobSnapshot.isPlainID(sampleId) else {
            completion(nil)
            return
        }
        apiJSON("api/v1/samples/\(sampleId)", keys: ["sample_code"]) { object in
            completion((object as? [String: Any])?["sample_code"] as? String)
        }
    }

    /// A click on a notification: ARVA comes to the front, on the job's sample when the notification names one.
    private func openFromNotification(_ path: String?) {
        NSApp.activate(ignoringOtherApps: true)
        guard phase == .running, let web = mainWeb else {
            splash?.show()
            return
        }
        if let path, let url = URL(string: path, relativeTo: ArvaServer.base)?.absoluteURL,
           WebPolicy.classify(url) == .local {
            web.webView.load(URLRequest(url: url))
        }
        web.show()
    }

    /// Once, the first time ARVA opens in the app: what the notifications are, before macOS asks for permission.
    private func offerNotificationsOnce() {
        guard !UserDefaults.standard.bool(forKey: AnalysisNotifier.askedKey) else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, self.phase == .running, !self.quitPending, let window = self.mainWeb?.window,
                  window.attachedSheet == nil, !UserDefaults.standard.bool(forKey: AnalysisNotifier.askedKey) else { return }
            UserDefaults.standard.set(true, forKey: AnalysisNotifier.askedKey)
            let alert = NSAlert()
            alert.messageText = L("Notify you when an analysis ends?", "¿Avisarte cuando termine un análisis?")
            alert.informativeText = L("ARVA can show a macOS notification when an analysis finishes or fails (for example “ARVA: Flye finished — sample”), also while its window is in the background; a click opens the sample. macOS asks for permission next. The notifications are made on this Mac: nothing is sent anywhere. You can turn them on or off at any time in the ARVA menu.",
                                      "ARVA puede mostrar una notificación de macOS cuando un análisis termina o falla (por ejemplo «ARVA: Flye terminó — muestra»), también mientras su ventana está en segundo plano; un clic abre la muestra. A continuación macOS pide permiso. Las notificaciones se generan en esta Mac: no se envía nada a ningún lado. Puedes activarlas o desactivarlas cuando quieras en el menú ARVA.")
            alert.addButton(withTitle: L("Turn On", "Activar"))
            let later = alert.addButton(withTitle: L("Not Now", "Ahora no"))
            later.keyEquivalent = "\u{1b}"
            alert.beginSheetModal(for: window) { [weak self] response in
                if response == .alertFirstButtonReturn {
                    self?.enableNotifications()
                } else {
                    AnalysisNotifier.isEnabled = false
                }
            }
        }
    }

    /// Asks macOS (its dialog appears only the first time); a "no", now or before, is respected.
    private func enableNotifications() {
        notifier.requestPermission { [weak self] granted in
            guard let self else { return }
            AnalysisNotifier.isEnabled = granted
            self.jobWatch = JobWatch()
            if granted {
                self.note(L("Notifications are on: ARVA says when an analysis ends.\n",
                            "Notificaciones activadas: ARVA avisa cuando termina un análisis.\n"))
                return
            }
            let alert = NSAlert()
            alert.messageText = L("macOS does not let ARVA show notifications", "macOS no deja que ARVA muestre notificaciones")
            alert.informativeText = L("To allow them: System Settings → Notifications → ARVA → turn on Allow notifications. Then choose ARVA → Notify When Analyses End again.",
                                      "Para permitirlas: Ajustes del Sistema → Notificaciones → ARVA → activa Permitir notificaciones. Después elige de nuevo ARVA → Avisar cuando terminen los análisis.")
            alert.runModal()
        }
    }

    // MARK: When ARVA stops answering

    private func checkServer() {
        guard phase == .running, healthTimer != nil else { return }
        let current = attempt
        ArvaServer.checkHealth { [weak self] up in
            guard let self, current == self.attempt, self.phase == .running, self.healthTimer != nil else { return }
            switch self.serverWatch.update(answered: up) {
            case .wentDown?: self.showNotResponding()
            case .cameBack?: self.serverCameBack()
            case nil: break
            }
        }
    }

    /// ARVA stopped answering (most often: Docker Desktop was closed). Said on the window, as a sheet that does not
    /// block the app, with a button that opens Docker Desktop when needed and starts ARVA again (the same start as
    /// opening the app) and one to wait; it closes by itself when ARVA answers again.
    private func showNotResponding() {
        let title = L("ARVA is not responding: is Docker Desktop open?", "ARVA no responde: ¿Docker Desktop está abierto?")
        note(title + "\n")
        mainWeb?.window.subtitle = L("ARVA is not responding", "ARVA no responde")
        guard !quitPending, notRespondingAlert == nil, let window = mainWeb?.window, window.attachedSheet == nil else { return }
        let dockerOpen = DockerDesktop.isAppRunning
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = dockerOpen
            ? L("Docker Desktop is open, but ARVA does not answer at http://localhost:8080 (it may be restarting). Press Try Again to start ARVA again, or Wait: this message closes by itself as soon as ARVA answers. Your projects and databases are kept.",
                "Docker Desktop está abierto, pero ARVA no responde en http://localhost:8080 (puede que se esté reiniciando). Pulsa Reintentar para iniciar ARVA de nuevo, o Esperar: este mensaje se cierra solo en cuanto ARVA responda. Tus proyectos y bases de datos se conservan.")
            : L("ARVA runs inside Docker Desktop, which is not open. Press Open Docker Desktop: ARVA.app opens it and starts ARVA again. Your projects and databases are kept.",
                "ARVA funciona dentro de Docker Desktop, que no está abierto. Pulsa Abrir Docker Desktop: ARVA.app lo abre e inicia ARVA de nuevo. Tus proyectos y bases de datos se conservan.")
        alert.addButton(withTitle: dockerOpen ? L("Try Again", "Reintentar") : L("Open Docker Desktop", "Abrir Docker Desktop"))
        let wait = alert.addButton(withTitle: L("Wait", "Esperar"))
        wait.keyEquivalent = "\u{1b}"
        notRespondingAlert = alert
        let current = attempt
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            if self.notRespondingAlert === alert { self.notRespondingAlert = nil }
            guard response == .alertFirstButtonReturn, current == self.attempt, self.phase == .running else { return }
            // The whole start again: Docker Desktop is opened and waited for when needed, then ARVA is shown (and the
            // page reloaded) as soon as it answers, started again by the launcher when it does not come back by itself.
            self.begin()
        }
    }

    private func closeNotRespondingAlert() {
        if let alert = notRespondingAlert, let parent = alert.window.sheetParent {
            parent.endSheet(alert.window, returnCode: .cancel)
        }
        notRespondingAlert = nil
    }

    private func serverCameBack() {
        note(L("ARVA answers again.\n", "ARVA vuelve a responder.\n"))
        mainWeb?.window.subtitle = sleepGuard.isActive ? SleepGuard.statusText : ""
        closeNotRespondingAlert()
        // Not after a short gap with ARVA's page still shown (ARVA was only busy): a reload would discard what the
        // person was doing in it.
        if let web = mainWeb, ServerWatch.shouldReload(showsARVAPage: web.showsARVAPage, downFor: serverWatch.lastOutage) {
            web.reload()
        }
    }

    private func showSleepStatus(_ active: Bool) {
        let text = active ? SleepGuard.statusText : ""
        MainMenu.setSleepStatus(active ? text : nil)
        mainWeb?.window.subtitle = text
        if active { note(text + "\n") }
    }

    private func begin() {
        attempt += 1
        let current = attempt
        stopTimers()
        phase = .preparing
        log = ""
        let window = splash ?? makeSplash()
        window.clearDetails()
        window.setCancel(nil)
        window.setStatus(L("Preparing ARVA…", "Preparando ARVA…"))
        window.show()
        note(AppInfo.summary + "\n")
        DispatchQueue.global(qos: .userInitiated).async {
            var problem: String?
            var copied = false
            var envNote: String?
            do {
                guard let source = AppPaths.bundledRuntime else { throw RuntimeError.missingBundle("Resources/runtime") }
                copied = try RuntimeSync.sync(from: source, to: AppPaths.runtimeDir)
                try LauncherShims.install()
                envNote = EnvLink.ensure()
            } catch {
                problem = error.localizedDescription
            }
            let installed = DockerDesktop.isInstalled
            let ready = installed && DockerDesktop.engineReady()
            DispatchQueue.main.async {
                guard current == self.attempt else { return }
                if copied { self.note(L("Launcher files updated in ", "Archivos del lanzador actualizados en ") + AppInfo.tilde(AppPaths.runtimeDir.path) + "\n") }
                if let envNote { self.note(AppInfo.tilde(envNote)) }
                if let problem {
                    self.showError(title: L("ARVA could not be prepared", "No se pudo preparar ARVA"), message: problem)
                } else if !installed {
                    self.dockerMissing()
                } else if ready {
                    self.dockerReady(current)
                } else {
                    self.openDocker(current)
                }
            }
        }
    }

    private func dockerMissing() {
        phase = .failed
        splash?.setStatus(L("Docker Desktop is not installed.", "Docker Desktop no está instalado."))
        let alert = NSAlert()
        alert.messageText = L("ARVA needs Docker Desktop", "ARVA necesita Docker Desktop")
        alert.informativeText = L("ARVA runs inside Docker Desktop, a free program. Download it (choose “Mac with Apple chip” or “Mac with Intel chip”), install it, open it once and accept its terms. ARVA continues by itself once Docker is ready.",
                                  "ARVA funciona dentro de Docker Desktop, un programa gratuito. Descárgalo (elige “Mac with Apple chip” o “Mac with Intel chip”), instálalo, ábrelo una vez y acepta sus condiciones. ARVA sigue solo en cuanto Docker esté listo.")
        alert.addButton(withTitle: L("Download Docker Desktop", "Descargar Docker Desktop"))
        alert.addButton(withTitle: L("Try again", "Reintentar"))
        alert.addButton(withTitle: L("Quit", "Salir"))
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            NSWorkspace.shared.open(DockerDesktop.installPage)
            waitForDockerInstall(attempt)
        case .alertSecondButtonReturn:
            begin()
        default:
            NSApp.terminate(nil)
        }
    }

    /// After the download page was opened: checks every 5 seconds whether Docker Desktop has been installed.
    private func waitForDockerInstall(_ current: Int) {
        phase = .waitingDocker
        splash?.setStatus(L("Waiting for Docker Desktop to be installed…", "Esperando a que se instale Docker Desktop…"),
                          hint: L("Install Docker Desktop and open it; ARVA continues by itself.",
                                  "Instala Docker Desktop y ábrelo; ARVA sigue solo."))
        splash?.setCancel(L("Quit", "Salir"))
        pollTimer = commonTimer(withTimeInterval: 5, repeats: true) { [weak self] timer in
            guard let self, current == self.attempt else {
                timer.invalidate()
                return
            }
            if self.quitPending { return }
            if DockerDesktop.isInstalled {
                timer.invalidate()
                self.splash?.setCancel(nil)
                self.openDocker(current)
            }
        }
    }

    private func openDocker(_ current: Int) {
        phase = .waitingDocker
        splash?.setStatus(L("Opening Docker…", "Abriendo Docker…"),
                          hint: L("The first time, Docker Desktop may ask you to accept its terms or to sign in (signing in is optional): answer in its window.",
                                  "La primera vez, Docker Desktop puede pedir que aceptes sus condiciones o que inicies sesión (no hace falta): responde en su ventana."))
        if DockerDesktop.appURL == nil {
            showError(title: L("Docker is not running", "Docker no está en marcha"),
                      message: L("Start your Docker engine, then press Try again.", "Inicia tu motor de Docker y pulsa Reintentar."))
            return
        }
        if !DockerDesktop.isAppRunning {
            launchedDocker = true
            note(L("Opening Docker Desktop.\n", "Abriendo Docker Desktop.\n"))
        }
        DockerDesktop.open { [weak self] opened in
            guard let self, current == self.attempt else { return }
            if !opened { self.note(L("Docker Desktop did not confirm it opened; waiting anyway.\n", "Docker Desktop no confirmó que se abrió; se espera igualmente.\n")) }
        }
        let deadline = Date().addingTimeInterval(300)
        pollDocker(current, deadline: deadline)
    }

    private func pollDocker(_ current: Int, deadline: Date) {
        DispatchQueue.global(qos: .userInitiated).async {
            let ready = DockerDesktop.engineReady()
            DispatchQueue.main.async {
                guard current == self.attempt else { return }
                if ready {
                    self.note(L("Docker is ready.\n", "Docker está listo.\n"))
                    self.dockerReady(current)
                } else if Date() > deadline {
                    self.showError(title: L("Docker Desktop did not finish opening", "Docker Desktop no terminó de abrirse"),
                                   message: L("Look at Docker Desktop's window: it may be waiting for you (terms, an update, or a message). When its whale icon in the menu bar stops moving, press Try again.",
                                              "Mira la ventana de Docker Desktop: puede estar esperándote (condiciones, una actualización o un mensaje). Cuando el icono de la ballena en la barra de menús deje de moverse, pulsa Reintentar."))
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.pollDocker(current, deadline: deadline) }
                }
            }
        }
    }

    private func dockerReady(_ current: Int) {
        splash?.setStatus(L("Starting ARVA…", "Iniciando ARVA…"))
        ArvaServer.checkHealth { [weak self] up in
            guard let self, current == self.attempt else { return }
            if up {
                // Already running (left running last time, or started from Terminal): shown at once.
                self.note(L("ARVA is already running.\n", "ARVA ya está en marcha.\n"))
                self.showARVA()
            } else if !FileManager.default.fileExists(atPath: AppPaths.configFile().path) {
                self.firstRun(current)
            } else {
                self.runLauncher(current)
            }
        }
    }

    private func firstRun(_ current: Int) {
        let alert = NSAlert()
        alert.messageText = L("Welcome to ARVA", "Te damos la bienvenida a ARVA")
        alert.informativeText = L("ARVA runs for the first time on this Mac: a Terminal window opens with a few questions (mainly which disk keeps your data). Answer them there; ARVA opens here by itself when it is ready.",
                                  "ARVA se usa por primera vez en esta Mac: se abre una ventana de Terminal con unas preguntas (sobre todo, en qué disco guardar los datos). Contéstalas allí; ARVA se abre aquí solo cuando esté listo.")
        alert.addButton(withTitle: L("Continue", "Continuar"))
        alert.addButton(withTitle: L("Quit", "Salir"))
        guard alert.runModal() == .alertFirstButtonReturn else {
            NSApp.terminate(nil)
            return
        }
        startWizard(current)
    }

    /// The first-run questions in Terminal (also for ARVA → Set Up Again); then ARVA opens here once it answers.
    private func startWizard(_ current: Int) {
        let runtime = AppPaths.runtimeDir
        let command: URL
        do {
            command = try FirstRunCommand.write(in: runtime)
        } catch {
            showError(title: L("ARVA could not be prepared", "No se pudo preparar ARVA"), message: error.localizedDescription)
            return
        }
        phase = .firstRun
        note(L("The questions are asked in Terminal (scripts/start.sh --setup); what that window shows follows here.\n",
               "Las preguntas se hacen en Terminal (scripts/start.sh --setup); lo que muestra esa ventana sigue aquí.\n"))
        if let terminal = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal") {
            NSWorkspace.shared.open([command], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration())
        } else {
            NSWorkspace.shared.open(command)
        }
        splash?.setStatus(L("Answer the questions in the Terminal window…", "Contesta las preguntas en la ventana de Terminal…"),
                          hint: L("Then ARVA downloads its programs (10 to 16 GB once unpacked, the first time) and opens here by itself. On a slow connection this can take more than an hour.",
                                  "Después ARVA descarga sus programas (de 10 a 16 GB ya descomprimidos, la primera vez) y se abre aquí solo. Con una conexión lenta puede tardar más de una hora."))
        splash?.setCancel(L("Cancel", "Cancelar"))
        let tail = LogTail(url: runtime.appendingPathComponent(FirstRunCommand.logFile))
        let opened = Date()
        var finishedAt: Date?
        var checking = false
        pollTimer = commonTimer(withTimeInterval: 3, repeats: true) { [weak self] timer in
            guard let self, current == self.attempt else {
                timer.invalidate()
                return
            }
            if self.quitPending { return }
            let text = tail.read()
            if !text.isEmpty { self.note(text) }
            if finishedAt == nil {
                switch FirstRunCommand.status(in: runtime) {
                case .succeeded?:
                    finishedAt = Date()
                    self.splash?.setStatus(L("Opening ARVA…", "Abriendo ARVA…"))
                case .declined?:
                    timer.invalidate()
                    self.firstRunDeclined()
                    return
                case .interrupted?:
                    timer.invalidate()
                    self.wizardClosed()
                    return
                case .failed(_)?:
                    timer.invalidate()
                    self.showError(title: L("ARVA did not start", "ARVA no se inició"),
                                   message: L("What happened is under Details here (and in the Terminal window). Fix it if it says how (for example, connect the disk), then press Try again. If it keeps happening, press Copy details and send the text to whoever helps you with ARVA.",
                                              "Lo que pasó está en Detalles, aquí (y en la ventana de Terminal). Corrígelo si indica cómo (por ejemplo, conectar el disco) y pulsa Reintentar. Si sigue pasando, pulsa Copiar detalles y envía el texto a quien te ayuda con ARVA."))
                    return
                case nil:
                    // Still asking, unless its Terminal window was closed (or never opened).
                    if checking { return }
                    checking = true
                    DispatchQueue.global(qos: .utility).async {
                        let running = FirstRunCommand.isRunning(in: runtime)
                        let status = FirstRunCommand.status(in: runtime)
                        DispatchQueue.main.async {
                            checking = false
                            guard current == self.attempt, self.phase == .firstRun, !self.quitPending, status == nil else { return }
                            if running == false || (running == nil && Date().timeIntervalSince(opened) > 90) {
                                self.pollTimer?.invalidate()
                                self.wizardClosed()
                            }
                        }
                    }
                    return
                }
            }
            if let finishedAt, Date().timeIntervalSince(finishedAt) > 180 {
                timer.invalidate()
                self.healthTimedOut()
                return
            }
            ArvaServer.checkHealth { up in
                guard up, current == self.attempt, self.phase == .firstRun, !self.quitPending else { return }
                timer.invalidate()
                self.showARVA()
            }
        }
    }

    private func wizardClosed() {
        showError(title: L("The questions were not finished", "Las preguntas no se terminaron"),
                  message: L("The Terminal window with the questions was closed (or stopped) before ARVA started. Press Try again to see the questions again.",
                             "La ventana de Terminal con las preguntas se cerró (o se detuvo) antes de que ARVA se iniciara. Pulsa Reintentar para ver de nuevo las preguntas."))
    }

    /// The person answered no to "Save these choices and start ARVA?": nothing was saved or started.
    private func firstRunDeclined() {
        phase = .failed
        stopTimers()
        splash?.setCancel(nil)
        splash?.setStatus(L("ARVA was not set up.", "ARVA no se configuró."))
        note(L("\nThe answers were not saved; ARVA did not start.\n", "\nNo se guardaron las respuestas; ARVA no se inició.\n"))
        let alert = NSAlert()
        alert.messageText = L("ARVA was not set up", "ARVA no se configuró")
        alert.informativeText = L("You chose not to save the answers, so nothing was saved and ARVA did not start. Press Answer again to see the questions again.",
                                  "Elegiste no guardar las respuestas, así que no se guardó nada y ARVA no se inició. Pulsa Responder de nuevo para ver otra vez las preguntas.")
        alert.addButton(withTitle: L("Answer again", "Responder de nuevo"))
        alert.addButton(withTitle: L("Quit", "Salir"))
        if alert.runModal() == .alertFirstButtonReturn {
            begin()
        } else {
            NSApp.terminate(nil)
        }
    }

    /// scripts/start.sh --no-setup in the background, with `extra` options (e.g. --import-dir PATH), as an argument list.
    private func runLauncher(_ current: Int, extra: [String] = []) {
        phase = .starting
        let runtime = AppPaths.runtimeDir
        splash?.setStatus(L("Starting ARVA…", "Iniciando ARVA…"),
                          hint: L("When there is a new version, Docker downloads it first: from a few minutes to more than an hour on a slow connection (Details shows the progress).",
                                  "Cuando hay una versión nueva, Docker la descarga primero: desde unos minutos hasta más de una hora con una conexión lenta (Detalles muestra el avance)."))
        splash?.setCancel(L("Cancel", "Cancelar"))
        let arguments = ["scripts/start.sh", "--no-setup"] + extra
        note("$ sh " + arguments.map { $0.hasPrefix("-") || $0 == "scripts/start.sh" ? $0 : shellQuote($0) }.joined(separator: " ") + "\n")
        let task = ShellTask(executable: "/bin/sh", arguments: arguments, directory: runtime,
                             environment: ShellEnvironment.make(),
                             logFile: AppPaths.logsDir.appendingPathComponent("start.log"))
        var timedOut = false
        task.onOutput = { [weak self] text in self?.note(text) }
        task.onExit = { [weak self] status, output in
            guard let self, current == self.attempt else { return }
            self.startTask = nil
            self.watchdog?.invalidate()
            self.splash?.setCancel(nil)
            if status == 0 {
                self.waitForHealth(current)
            } else if timedOut {
                self.showError(title: L("ARVA took too long to start", "ARVA tardó demasiado en iniciarse"),
                               message: L("Nothing happened for 20 minutes (a slow or interrupted download?). Check the internet connection and press Try again.",
                                          "No pasó nada durante 20 minutos (¿una descarga lenta o interrumpida?). Comprueba la conexión a internet y pulsa Reintentar."))
            } else {
                self.launcherFailed(status: status, output: output)
            }
        }
        do {
            try task.start()
        } catch {
            showError(title: L("ARVA could not be started", "No se pudo iniciar ARVA"), message: error.localizedDescription)
            return
        }
        startTask = task
        watchdog = commonTimer(withTimeInterval: 30, repeats: true) { [weak task] _ in
            guard let task, task.isRunning else { return }
            if Date().timeIntervalSince(task.lastOutputDate) > 20 * 60 {
                timedOut = true
                task.terminateAll()
            }
        }
    }

    private func waitForHealth(_ current: Int) {
        phase = .waitingHealth
        splash?.setStatus(L("Opening ARVA…", "Abriendo ARVA…"))
        let deadline = Date().addingTimeInterval(180)
        pollTimer = commonTimer(withTimeInterval: 2, repeats: true) { [weak self] timer in
            guard let self, current == self.attempt else {
                timer.invalidate()
                return
            }
            if self.quitPending { return }
            if Date() > deadline {
                timer.invalidate()
                self.healthTimedOut()
                return
            }
            ArvaServer.checkHealth { up in
                guard up, current == self.attempt, self.phase == .waitingHealth, !self.quitPending else { return }
                timer.invalidate()
                self.showARVA()
            }
        }
        pollTimer?.fire()
    }

    private func healthTimedOut() {
        showError(title: L("ARVA does not answer", "ARVA no responde"),
                  message: L("ARVA started but does not answer at http://localhost:8080. Press Try again; if it keeps happening, press Copy details and send the text to whoever helps you with ARVA.",
                             "ARVA se inició pero no responde en http://localhost:8080. Pulsa Reintentar; si sigue pasando, pulsa Copiar detalles y envía el texto a quien te ayuda con ARVA."))
    }

    /// Why start.sh failed, in plain words. Only its last lines are read, without the warnings it goes on after (an
    /// added database or import folder whose disk is not connected), so an earlier warning does not hide the cause.
    static func failureLines(_ output: String) -> String {
        let warnings = ["is not available: is its disk connected", "no está disponible: ¿está conectado su disco",
                        "(disk not connected)", "(disco no conectado)", "starts without it", "se inicia sin ella"]
        let lines = output.components(separatedBy: "\n").map { $0.lowercased() }
            .filter { line in !line.trimmingCharacters(in: .whitespaces).isEmpty && !warnings.contains { line.contains($0) } }
        return lines.suffix(15).joined(separator: "\n")
    }

    private func launcherFailed(status: Int32, output: String) {
        let last = Self.failureLines(output)
        let config = ArvaConfig.load(from: AppPaths.configFile())
        let disks = config?.missingDisks() ?? []
        let diskWords = ["connect the disk", "conéctalo", "probably not connected", "probablemente ese disco no está conectado",
                         "is the disk connected", "el disco está conectado"]
        let otherDisk = L(" To keep ARVA's data on another disk, press Set up again.",
                          " Para guardar los datos de ARVA en otro disco, pulsa Volver a configurar.")
        var offerSetup = false
        let title: String
        let message: String
        if last.contains("could not download") || last.contains("no pudo descargar") {
            title = L("ARVA could not be downloaded", "No se pudo descargar ARVA")
            message = L("Docker could not download ARVA's programs. Check the internet connection, then press Try again.",
                        "Docker no pudo descargar los programas de ARVA. Comprueba la conexión a internet y pulsa Reintentar.")
        } else if last.contains("docker is not running") || last.contains("docker no está en marcha") {
            title = L("Docker is not running", "Docker no está en marcha")
            message = L("Docker Desktop closed or is still starting. Open it, wait until it is ready, then press Try again.",
                        "Docker Desktop se cerró o todavía se está iniciando. Ábrelo, espera a que esté listo y pulsa Reintentar.")
        } else if last.contains("mounts denied") || last.contains("file sharing") {
            title = L("Docker Desktop cannot see the folder", "Docker Desktop no puede ver la carpeta")
            message = L("Docker Desktop refused one of ARVA's folders. In Docker Desktop: Settings → Resources → File sharing, add the folder (or the disk under /Volumes), press Apply, then Try again here.",
                        "Docker Desktop rechazó una de las carpetas de ARVA. En Docker Desktop: Settings → Resources → File sharing, añade la carpeta (o el disco bajo /Volumes), pulsa Apply y luego Reintentar aquí.")
        } else if !disks.isEmpty {
            let name = disks.map { "“\($0)”" }.joined(separator: ", ")
            title = L("Connect the disk", "Conecta el disco")
            message = L("The disk \(name) is not connected. ARVA keeps your projects there and does not start without it, so nothing is written to the Mac's own disk instead. Connect it, wait until it appears in Finder, then press Try again.",
                        "El disco \(name) no está conectado. ARVA guarda allí tus proyectos y no se inicia sin él, así no escribe nada en el disco de la Mac. Conéctalo, espera a que aparezca en Finder y pulsa Reintentar.") + otherDisk
            offerSetup = true
        } else if diskWords.contains(where: { last.contains($0) }) {
            title = L("ARVA cannot reach its disk", "ARVA no llega a su disco")
            message = L("ARVA cannot reach the folder where it keeps your data. Connect the disk and wait until it appears in Finder. If it is already connected, macOS may be keeping ARVA away from it (for example after “Don’t Allow”): in System Settings → Privacy & Security → Files and Folders, turn on “Removable Volumes” for ARVA, then press Try again.",
                        "ARVA no llega a la carpeta donde guarda tus datos. Conecta el disco y espera a que aparezca en Finder. Si ya está conectado, puede que macOS no deje que ARVA lo use (por ejemplo, después de “No permitir”): en Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas, activa “Volúmenes extraíbles” para ARVA y pulsa Reintentar.") + otherDisk
            offerSetup = true
        } else {
            title = L("ARVA could not start", "ARVA no pudo iniciarse")
            message = L("Something went wrong while starting ARVA (exit status \(status)). Press Try again; if it keeps happening, press Copy details and send the text to whoever helps you with ARVA.",
                        "Algo falló al iniciar ARVA (estado de salida \(status)). Pulsa Reintentar; si sigue pasando, pulsa Copiar detalles y envía el texto a quien te ayuda con ARVA.")
        }
        showError(title: title, message: message, offerSetup: offerSetup)
    }

    private func cancelStart() {
        switch phase {
        case .waitingDocker where pollTimer != nil:
            NSApp.terminate(nil)
            return
        case .starting, .firstRun, .waitingHealth:
            break
        default:
            return
        }
        attempt += 1
        stopTimers()
        phase = .stopping
        splash?.setCancel(nil)
        splash?.setStatus(L("Cancelling…", "Cancelando…"))
        note(L("\nCancelled.\n", "\nCancelado.\n"))
        stopLaunchers { [weak self] in
            self?.showError(title: L("Start cancelled", "Inicio cancelado"),
                            message: L("ARVA's start was cancelled. Press Try again to start it, or Quit.",
                                       "Se canceló el inicio de ARVA. Pulsa Reintentar para iniciarlo, o Salir."))
        }
    }

    /// Stops what this app started to get ARVA going (start.sh and its docker compose, or the first-run questions in
    /// Terminal) and calls back once they are gone, so that nothing races what comes next (Try again, or stop.sh).
    private func stopLaunchers(_ completion: @escaping () -> Void) {
        let group = DispatchGroup()
        if let task = startTask {
            startTask = nil
            group.enter()
            task.terminateAll { group.leave() }
        }
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            FirstRunCommand.stop(in: AppPaths.runtimeDir)
            group.leave()
        }
        group.notify(queue: .main, execute: completion)
    }

    /// A plain-language problem, with Try again, Copy details (what support needs) and Quit.
    private func showError(title: String, message: String, offerSetup: Bool = false) {
        if quitPending {
            deferredError = (title, message, offerSetup)
            return
        }
        phase = .failed
        stopTimers()
        splash?.setCancel(nil)
        splash?.setStatus(title)
        splash?.show()
        note("\n[\(title)] \(message)\n")
        var copiedNote = ""
        while true {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = title
            alert.informativeText = message + copiedNote
            alert.addButton(withTitle: L("Try again", "Reintentar"))
            alert.addButton(withTitle: L("Copy details", "Copiar detalles"))
            if offerSetup { alert.addButton(withTitle: L("Set up again…", "Volver a configurar…")) }
            alert.addButton(withTitle: L("Quit", "Salir"))
            let response = alert.runModal()
            if response == .alertFirstButtonReturn {
                begin()
                return
            } else if response == .alertSecondButtonReturn {
                copyDetailsToPasteboard()
                copiedNote = "\n\n" + L("The details were copied: paste them (⌘V) in a message.", "Se copiaron los detalles: pégalos (⌘V) en un mensaje.")
            } else if offerSetup && response == .alertThirdButtonReturn {
                setupAgain()
                return
            } else {
                NSApp.terminate(nil)
                return
            }
        }
    }

    private func copyDetailsToPasteboard() {
        let text = AppInfo.tilde(log)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private func showARVA() {
        phase = .running
        stopTimers()
        splash?.setCancel(nil)
        note(L("ARVA is ready.\n", "ARVA está listo.\n"))
        let web: WebWindowController
        if let mainWeb {
            web = mainWeb
            web.reload()
        } else {
            web = makeWeb(configuration: webConfiguration, isMain: true)
            mainWeb = web
            web.loadARVA()
        }
        web.window.subtitle = ""
        web.show()
        splash?.window.orderOut(nil)
        NSApp.activate(ignoringOtherApps: true)
        startSleepWatch()
        offerNotificationsOnce()
    }

    private func makeWeb(configuration: WKWebViewConfiguration, isMain: Bool) -> WebWindowController {
        let controller = WebWindowController(configuration: configuration, isMain: isMain)
        controller.makeWindow = { [weak self] config in
            guard let self else { return nil }
            let other = self.makeWeb(configuration: config, isMain: false)
            other.show()
            return other.webView
        }
        controller.onClose = { [weak self] closed in
            self?.otherWebs.removeAll { $0 === closed }
        }
        if !isMain { otherWebs.append(controller) }
        return controller
    }

    // MARK: Quitting

    private func askToStop() {
        quitPending = true
        countActiveJobs { [weak self] count in
            guard let self else { return }
            let alert = NSAlert()
            alert.messageText = L("Stop ARVA?", "¿Detener ARVA?")
            var info = L("Stopping ARVA frees the memory Docker uses for it. Your projects and databases are kept, and ARVA starts again the next time you open it.",
                         "Detener ARVA libera la memoria que Docker usa para él. Tus proyectos y bases de datos se conservan, y ARVA vuelve a iniciarse la próxima vez que lo abras.")
            if let count, count > 0 {
                let en = count == 1 ? "1 analysis is running or waiting" : "\(count) analyses are running or waiting"
                info += "\n\n⚠️ " + L("\(en): stopping ARVA interrupts them (they can be run again later). To let them finish, choose Quit without stopping.",
                                     "Hay \(count) análisis en curso o en espera: detener ARVA los interrumpe (se pueden volver a ejecutar después). Para que terminen, elige Salir sin detener.")
            }
            alert.informativeText = info
            let stopButton = alert.addButton(withTitle: L("Stop and quit", "Detener y salir"))
            let leaveButton = alert.addButton(withTitle: L("Quit without stopping", "Salir sin detener"))
            if let count, count > 0 {
                // Analyses are running: Return keeps them running.
                stopButton.keyEquivalent = ""
                leaveButton.keyEquivalent = "\r"
            }
            let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
            cancel.keyEquivalent = "\u{1b}"
            var checkbox: NSButton?
            if self.launchedDocker {
                let box = NSButton(checkboxWithTitle: L("Also quit Docker Desktop (ARVA opened it) to free memory",
                                                        "Cerrar también Docker Desktop (lo abrió ARVA) para liberar memoria"),
                                   target: nil, action: nil)
                let defaults = UserDefaults.standard
                box.state = (defaults.object(forKey: Self.quitDockerKey) as? Bool ?? true) ? .on : .off
                alert.accessoryView = box
                checkbox = box
            }
            let response = alert.runModal()
            self.quitPending = false
            let quitDocker = checkbox?.state == .on
            if let checkbox, response != .alertThirdButtonReturn {
                UserDefaults.standard.set(checkbox.state == .on, forKey: Self.quitDockerKey)
            }
            switch response {
            case .alertFirstButtonReturn:
                self.stopAndQuit(quitDocker: quitDocker)
            case .alertSecondButtonReturn:
                self.terminating = true
                NSApp.reply(toApplicationShouldTerminate: true)
            default:
                NSApp.reply(toApplicationShouldTerminate: false)
                if let error = self.deferredError {
                    self.deferredError = nil
                    DispatchQueue.main.async {
                        self.showError(title: error.title, message: error.message, offerSetup: error.offerSetup)
                    }
                }
            }
        }
    }

    /// The analyses running or waiting: asked by the page's own session first (so it also works with accounts on),
    /// in the app's isolated script world, then directly; nil when unknown. At most about 3 seconds.
    private func countActiveJobs(_ completion: @escaping (Int?) -> Void) {
        var done = false
        let finish: (Int?) -> Void = { value in
            guard !done else { return }
            done = true
            completion(value)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { finish(nil) }
        let direct = { ArvaServer.activeJobs { finish($0) } }
        guard let web = mainWeb?.webView, let url = web.url, WebPolicy.classify(url) == .local else {
            direct()
            return
        }
        let body = """
        const r = await fetch('/api/v1/dashboard', {credentials: 'same-origin', cache: 'no-store'});
        if (!r.ok) return -1;
        const j = await r.json();
        return typeof j.jobs_running === 'number' ? j.jobs_running : -1;
        """
        web.callAsyncJavaScript(body, arguments: [:], in: nil, in: .defaultClient) { result in
            if case .success(let value) = result, let number = value as? NSNumber, number.intValue >= 0 {
                finish(number.intValue)
            } else {
                direct()
            }
        }
    }

    /// A GET of one of ARVA's API paths ("api/v1/jobs?status=running"), as JSON, like countActiveJobs: asked by the
    /// page's own session first (in the app's isolated script world, so it also works with accounts on), then
    /// directly; nil when neither answered. Only the `keys` of the object (or of each object of a list) are kept, so a
    /// job's log is not passed around. At most about 5 seconds.
    private func apiJSON(_ path: String, keys: [String], _ completion: @escaping (Any?) -> Void) {
        var done = false
        let finish: (Any?) -> Void = { value in
            guard !done else { return }
            done = true
            completion(value)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { finish(nil) }
        let direct = { ArvaServer.getJSON(path) { finish($0) } }
        guard let web = mainWeb?.webView, let url = web.url, WebPolicy.classify(url) == .local else {
            direct()
            return
        }
        let body = """
        const r = await fetch('/' + path, {credentials: 'same-origin', cache: 'no-store'});
        if (!r.ok) return null;
        const j = await r.json();
        const pick = (o) => (o && typeof o === 'object' && !Array.isArray(o))
          ? Object.fromEntries(keys.map((k) => [k, o[k] === undefined ? null : o[k]])) : o;
        return JSON.stringify(Array.isArray(j) ? j.map(pick) : pick(j));
        """
        web.callAsyncJavaScript(body, arguments: ["path": path, "keys": keys], in: nil, in: .defaultClient) { result in
            if case .success(let value) = result, let text = value as? String,
               let object = try? JSONSerialization.jsonObject(with: Data(text.utf8)) {
                finish(object)
            } else {
                direct()
            }
        }
    }

    private func stopAndQuit(quitDocker: Bool) {
        attempt += 1
        stopTimers()
        phase = .stopping
        log = ""
        let window = splash ?? makeSplash()
        window.clearDetails()
        window.setCancel(nil)
        window.setStatus(L("Stopping ARVA…", "Deteniendo ARVA…"),
                         hint: L("Your projects and databases are kept.", "Tus proyectos y bases de datos se conservan."))
        window.show()
        mainWeb?.window.orderOut(nil)
        for other in otherWebs { other.window.orderOut(nil) }
        // A start still under way is stopped first, so that stop.sh does not race a docker compose up.
        stopLaunchers { [weak self] in self?.runStop(quitDocker: quitDocker) }
    }

    private func runStop(quitDocker: Bool) {
        note("$ sh scripts/stop.sh\n")
        let task = ShellTask(executable: "/bin/sh", arguments: ["scripts/stop.sh"], directory: AppPaths.runtimeDir,
                             environment: ShellEnvironment.make(),
                             logFile: AppPaths.logsDir.appendingPathComponent("stop.log"))
        task.onOutput = { [weak self] text in self?.note(text) }
        task.onExit = { [weak self] status, _ in
            guard let self else { return }
            self.stopTask = nil
            self.watchdog?.invalidate()
            if status == 0 {
                if quitDocker { DockerDesktop.quit() }
                self.terminating = true
                NSApp.reply(toApplicationShouldTerminate: true)
            } else {
                self.stopFailed(status: status, quitDocker: quitDocker)
            }
        }
        do {
            try task.start()
        } catch {
            note(error.localizedDescription + "\n")
            stopFailed(status: -1, quitDocker: false)
            return
        }
        stopTask = task
        watchdog = commonTimer(withTimeInterval: 180, repeats: false) { [weak task] _ in task?.terminateAll() }
    }

    private func stopFailed(status: Int32, quitDocker: Bool) {
        var copiedNote = ""
        while true {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = L("ARVA could not be stopped", "No se pudo detener ARVA")
            alert.informativeText = L("Docker did not stop ARVA (exit status \(status)). You can quit anyway: ARVA keeps running until Docker Desktop closes.",
                                      "Docker no detuvo ARVA (estado de salida \(status)). Puedes salir igualmente: ARVA sigue en marcha hasta que se cierre Docker Desktop.") + copiedNote
            alert.addButton(withTitle: L("Quit anyway", "Salir igualmente"))
            alert.addButton(withTitle: L("Copy details", "Copiar detalles"))
            let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
            cancel.keyEquivalent = "\u{1b}"
            switch alert.runModal() {
            case .alertFirstButtonReturn:
                if quitDocker { DockerDesktop.quit() }
                terminating = true
                NSApp.reply(toApplicationShouldTerminate: true)
                return
            case .alertSecondButtonReturn:
                copyDetailsToPasteboard()
                copiedNote = "\n\n" + L("The details were copied.", "Se copiaron los detalles.")
            default:
                NSApp.reply(toApplicationShouldTerminate: false)
                // ARVA may be half stopped, or (when the quit came during the start) not started at all: it is
                // checked again from the beginning, and shown as soon as it answers.
                begin()
                return
            }
        }
    }

    // MARK: Menu commands

    private var frontWeb: WebWindowController? {
        if let key = NSApp.keyWindow {
            if mainWeb?.window === key { return mainWeb }
            if let other = otherWebs.first(where: { $0.window === key }) { return other }
        }
        return phase == .running ? mainWeb : nil
    }

    @objc func arvaReload(_ sender: Any?) { frontWeb?.reload() }
    @objc func arvaZoomIn(_ sender: Any?) { frontWeb?.zoomIn() }
    @objc func arvaZoomOut(_ sender: Any?) { frontWeb?.zoomOut() }
    @objc func arvaZoomReset(_ sender: Any?) { frontWeb?.zoomReset() }
    @objc func arvaBack(_ sender: Any?) { frontWeb?.webView.goBack() }
    @objc func arvaForward(_ sender: Any?) { frontWeb?.webView.goForward() }
    @objc func arvaOpenInBrowser(_ sender: Any?) {
        if let web = frontWeb ?? mainWeb { web.openInBrowser() } else { NSWorkspace.shared.open(ArvaServer.base) }
    }
    @objc func arvaCopyDetails(_ sender: Any?) { copyDetailsToPasteboard() }
    @objc func arvaShowImportFolder(_ sender: Any?) {
        DispatchQueue.global(qos: .userInitiated).async {
            let answer = ImportFolder.current()
            DispatchQueue.main.async {
                switch answer {
                case .folder(let folder):
                    NSWorkspace.shared.open(folder)
                case .unavailable(let path):
                    let alert = NSAlert()
                    alert.messageText = L("The import folder is not available", "La carpeta de importación no está disponible")
                    alert.informativeText = L("ARVA imports from \(path), which cannot be found now: connect its disk (then open ARVA again so that it uses it), or choose another folder with ARVA → Choose Import Folder….",
                                              "ARVA importa desde \(path), que ahora no se encuentra: conecta su disco (y vuelve a abrir ARVA para que la use) o elige otra carpeta con ARVA → Elegir carpeta de importación….")
                    alert.runModal()
                }
            }
        }
    }
    @objc func arvaHelp(_ sender: Any?) {
        let configured = (Bundle.main.object(forInfoDictionaryKey: "ARVAGuideURL") as? String).flatMap(URL.init(string:))
        NSWorkspace.shared.open(configured ?? Self.repository.appendingPathComponent("blob/main/docs/guia-mac-app.md"))
    }
    @objc func arvaSetupAgain(_ sender: Any?) {
        guard phase == .running || phase == .failed else { return }
        let alert = NSAlert()
        alert.messageText = L("Set up ARVA again?", "¿Volver a configurar ARVA?")
        alert.informativeText = L("A Terminal window opens with the first-run questions again (which disk keeps the data, the databases you already have…), and ARVA restarts with the new answers. Nothing is moved or deleted: folders you stop using stay as they are.",
                                  "Se abre una ventana de Terminal con las preguntas del primer inicio (en qué disco guardar los datos, las bases de datos que ya tienes…) y ARVA se reinicia con las nuevas respuestas. No se mueve ni se borra nada: las carpetas que dejes de usar quedan como están.")
        alert.addButton(withTitle: L("Continue", "Continuar"))
        let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
        cancel.keyEquivalent = "\u{1b}"
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        setupAgain()
    }

    private func setupAgain() {
        attempt += 1
        let current = attempt
        stopTimers()
        log = ""
        let window = splash ?? makeSplash()
        window.clearDetails()
        window.setCancel(nil)
        window.setStatus(L("Preparing ARVA…", "Preparando ARVA…"))
        window.show()
        mainWeb?.window.orderOut(nil)
        for other in otherWebs { other.window.orderOut(nil) }
        note(AppInfo.summary + "\n")
        startWizard(current)
    }

    /// ARVA → Choose Import Folder…: a folder chosen in Finder's panel, checked here (ImportFolderRule), then passed to
    /// the launcher (scripts/start.sh --no-setup --import-dir FOLDER), which checks it again, saves it in arva.conf as
    /// ARVA_IMPORT_DIR and starts ARVA's services again with it, as when the app opens. No terminal needed.
    @objc func arvaChooseImportFolder(_ sender: Any?) {
        guard phase == .running || phase == .failed else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        panel.showsHiddenFiles = false
        panel.title = L("Choose Import Folder", "Elegir carpeta de importación")
        panel.message = L("The folder with the sequencing runs ARVA imports from. ARVA only reads it: it never writes, moves or deletes anything in it.",
                          "La carpeta con las corridas de secuenciación desde la que importa ARVA. ARVA solo la lee: nunca escribe, mueve ni borra nada en ella.")
        panel.prompt = L("Choose", "Elegir")
        if let saved = ArvaConfig.load(from: AppPaths.configFile())?.importDir {
            panel.directoryURL = URL(fileURLWithPath: saved, isDirectory: true)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let path = url.path
        let fm = FileManager.default
        let problem = ImportFolderRule.problem(path, home: AppPaths.home.path, isDirectory: { folder in
            var isDir: ObjCBool = false
            return fm.fileExists(atPath: folder, isDirectory: &isDir) && isDir.boolValue
        }, isReadable: { folder in
            fm.isReadableFile(atPath: folder) && fm.isExecutableFile(atPath: folder)
        })
        if let problem {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = L("This folder cannot be the import folder", "Esta carpeta no puede ser la carpeta de importación")
            alert.informativeText = ImportFolderRule.message(problem, path: path)
            alert.runModal()
            return
        }
        let wasRunning = phase == .running
        countActiveJobs { [weak self] count in
            guard let self, self.phase == .running || self.phase == .failed else { return }
            let alert = NSAlert()
            alert.messageText = L("Import from this folder?", "¿Importar desde esta carpeta?")
            var info = L("ARVA will import sequencing runs from \(path), read-only. ", "ARVA importará las corridas de secuenciación desde \(path), en solo lectura. ")
            info += wasRunning
                ? L("To use it, ARVA starts its services again (about a minute) and then this window reloads by itself.",
                    "Para usarla, ARVA vuelve a iniciar sus servicios (más o menos un minuto) y después esta ventana se vuelve a cargar sola.")
                : L("ARVA starts with it.", "ARVA se inicia con ella.")
            if let count, count > 0 {
                let en = count == 1 ? "1 analysis is running or waiting" : "\(count) analyses are running or waiting"
                info += "\n\n⚠️ " + L("\(en): starting the services again interrupts them (they can be run again later). To let them finish, choose the folder later.",
                                     "Hay \(count) análisis en curso o en espera: volver a iniciar los servicios los interrumpe (se pueden volver a ejecutar después). Para que terminen, elige la carpeta más tarde.")
            }
            alert.informativeText = info
            let use = alert.addButton(withTitle: L("Use This Folder", "Usar esta carpeta"))
            let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
            cancel.keyEquivalent = "\u{1b}"
            if let count, count > 0 {
                // Analyses are running: Return keeps them running.
                use.keyEquivalent = ""
                cancel.keyEquivalent = "\r"
            }
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            self.restartWithImportFolder(path)
        }
    }

    private func restartWithImportFolder(_ path: String) {
        attempt += 1
        let current = attempt
        stopTimers()
        log = ""
        let window = splash ?? makeSplash()
        window.clearDetails()
        window.setCancel(nil)
        window.setStatus(L("Starting ARVA…", "Iniciando ARVA…"))
        window.show()
        mainWeb?.window.orderOut(nil)
        for other in otherWebs { other.window.orderOut(nil) }
        note(AppInfo.summary + "\n")
        note(L("New import folder: \(path)\n", "Nueva carpeta de importación: \(path)\n"))
        runLauncher(current, extra: ["--import-dir", path])
    }

    /// ARVA → Notify When Analyses End: on (macOS is asked first) or off.
    @objc func arvaToggleNotifications(_ sender: Any?) {
        if AnalysisNotifier.isEnabled {
            AnalysisNotifier.isEnabled = false
            jobWatch = JobWatch()
        } else {
            enableNotifications()
        }
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        switch menuItem.action {
        case #selector(arvaReload(_:)), #selector(arvaZoomIn(_:)), #selector(arvaZoomOut(_:)), #selector(arvaZoomReset(_:)):
            return frontWeb != nil
        case #selector(arvaBack(_:)):
            return frontWeb?.webView.canGoBack ?? false
        case #selector(arvaForward(_:)):
            return frontWeb?.webView.canGoForward ?? false
        case #selector(arvaOpenInBrowser(_:)):
            return phase == .running
        case #selector(arvaCopyDetails(_:)):
            return !log.isEmpty
        case #selector(arvaSetupAgain(_:)), #selector(arvaChooseImportFolder(_:)):
            return phase == .running || phase == .failed
        case #selector(arvaToggleNotifications(_:)):
            menuItem.state = AnalysisNotifier.isEnabled ? .on : .off
            return true
        default:
            return true
        }
    }
}

/// What the app is, for the details people paste to support (the home folder is shown as ~).
enum AppInfo {
    static var version: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?" }
    static var build: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?" }
    static var commit: String { Bundle.main.object(forInfoDictionaryKey: "ARVACommit") as? String ?? "?" }

    static var architecture: String {
        #if arch(arm64)
        return "arm64"
        #else
        return "x86_64"
        #endif
    }

    static var summary: String {
        let os = ProcessInfo.processInfo.operatingSystemVersion
        return "ARVA.app \(version) (\(build), \(commit)) · macOS \(os.majorVersion).\(os.minorVersion).\(os.patchVersion) · \(architecture)"
    }

    static func tilde(_ text: String) -> String {
        let home = AppPaths.home.path
        guard home.count > 1 else { return text }
        return text.replacingOccurrences(of: home, with: "~")
    }
}

/// A timer that also fires while a dialog is open or the app waits to quit (the run loop's common modes).
func commonTimer(withTimeInterval interval: TimeInterval, repeats: Bool, block: @escaping (Timer) -> Void) -> Timer {
    let timer = Timer(timeInterval: interval, repeats: repeats, block: block)
    RunLoop.main.add(timer, forMode: .common)
    return timer
}
