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
    private var attempt = 0
    /// Docker Desktop was opened by this app (so quitting may offer to close it again).
    private var launchedDocker = false
    private var terminating = false
    /// Everything shown under Details for the last start or stop, for "Copy details".
    private var log = ""

    // MARK: Application

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.build()
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
            do {
                guard let source = AppPaths.bundledRuntime else { throw RuntimeError.missingBundle("Resources/runtime") }
                copied = try RuntimeSync.sync(from: source, to: AppPaths.runtimeDir)
            } catch {
                problem = error.localizedDescription
            }
            let installed = DockerDesktop.isInstalled
            let ready = installed && DockerDesktop.engineReady()
            DispatchQueue.main.async {
                guard current == self.attempt else { return }
                if copied { self.note(L("Launcher files updated in ", "Archivos del lanzador actualizados en ") + AppInfo.tilde(AppPaths.runtimeDir.path) + "\n") }
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
        let command: URL
        do {
            command = try FirstRunCommand.write(in: AppPaths.runtimeDir)
        } catch {
            showError(title: L("ARVA could not be prepared", "No se pudo preparar ARVA"), message: error.localizedDescription)
            return
        }
        phase = .firstRun
        note(L("First run: the questions are asked in Terminal (scripts/start.sh --setup).\n",
               "Primer inicio: las preguntas se hacen en Terminal (scripts/start.sh --setup).\n"))
        if let terminal = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal") {
            NSWorkspace.shared.open([command], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration())
        } else {
            NSWorkspace.shared.open(command)
        }
        splash?.setStatus(L("Answer the questions in the Terminal window…", "Contesta las preguntas en la ventana de Terminal…"),
                          hint: L("Then ARVA downloads its programs (several GB the first time) and opens here by itself. This can take a while.",
                                  "Después ARVA descarga sus programas (varios GB la primera vez) y se abre aquí solo. Puede tardar un rato."))
        splash?.setCancel(L("Cancel", "Cancelar"))
        var finishedAt: Date?
        pollTimer = commonTimer(withTimeInterval: 3, repeats: true) { [weak self] timer in
            guard let self, current == self.attempt else {
                timer.invalidate()
                return
            }
            if finishedAt == nil, let status = FirstRunCommand.status(in: AppPaths.runtimeDir) {
                if status != 0 {
                    timer.invalidate()
                    self.showError(title: L("ARVA did not start", "ARVA no se inició"),
                                   message: L("The Terminal window says what happened. Fix it there if it says how (for example, connect the disk), then press Try again.",
                                              "La ventana de Terminal dice qué pasó. Corrígelo si indica cómo (por ejemplo, conectar el disco) y pulsa Reintentar."))
                    return
                }
                finishedAt = Date()
            }
            if let finishedAt, Date().timeIntervalSince(finishedAt) > 180 {
                timer.invalidate()
                self.healthTimedOut()
                return
            }
            ArvaServer.checkHealth { up in
                guard up, current == self.attempt, self.phase == .firstRun else { return }
                timer.invalidate()
                self.showARVA()
            }
        }
    }

    private func runLauncher(_ current: Int) {
        phase = .starting
        let runtime = AppPaths.runtimeDir
        splash?.setStatus(L("Starting ARVA…", "Iniciando ARVA…"),
                          hint: L("When there is a new version, Docker downloads it first: this can take a few minutes.",
                                  "Cuando hay una versión nueva, Docker la descarga primero: puede tardar unos minutos."))
        splash?.setCancel(L("Cancel", "Cancelar"))
        note("$ sh scripts/start.sh --no-setup\n")
        let task = ShellTask(executable: "/bin/sh", arguments: ["scripts/start.sh", "--no-setup"], directory: runtime,
                             environment: ShellEnvironment.make())
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
                task.terminate()
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
            if Date() > deadline {
                timer.invalidate()
                self.healthTimedOut()
                return
            }
            ArvaServer.checkHealth { up in
                guard up, current == self.attempt, self.phase == .waitingHealth else { return }
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

    private func launcherFailed(status: Int32, output: String) {
        let lower = output.lowercased()
        let config = ArvaConfig.load(from: AppPaths.configFile())
        let disks = config?.missingDisks() ?? []
        let title: String
        let message: String
        if !disks.isEmpty || lower.contains("is its disk connected") || lower.contains("está conectado su disco")
            || lower.contains("connect the disk") || lower.contains("conéctalo") || lower.contains("not connected")
            || lower.contains("no está conectado") {
            let name = disks.isEmpty ? L("where ARVA keeps your data", "donde ARVA guarda tus datos")
                                     : disks.map { "“\($0)”" }.joined(separator: ", ")
            title = L("Connect the disk", "Conecta el disco")
            message = L("The disk \(name) is not connected. ARVA keeps your projects there and does not start without it, so nothing is written to the Mac's own disk instead. Connect it, wait until it appears in Finder, then press Try again.",
                        "El disco \(name) no está conectado. ARVA guarda allí tus proyectos y no se inicia sin él, así no escribe nada en el disco de la Mac. Conéctalo, espera a que aparezca en Finder y pulsa Reintentar.")
        } else if lower.contains("could not download") || lower.contains("no pudo descargar") {
            title = L("ARVA could not be downloaded", "No se pudo descargar ARVA")
            message = L("Docker could not download ARVA's programs. Check the internet connection, then press Try again.",
                        "Docker no pudo descargar los programas de ARVA. Comprueba la conexión a internet y pulsa Reintentar.")
        } else if lower.contains("docker is not running") || lower.contains("docker no está en marcha") {
            title = L("Docker is not running", "Docker no está en marcha")
            message = L("Docker Desktop closed or is still starting. Open it, wait until it is ready, then press Try again.",
                        "Docker Desktop se cerró o todavía se está iniciando. Ábrelo, espera a que esté listo y pulsa Reintentar.")
        } else if lower.contains("mounts denied") || lower.contains("file sharing") {
            title = L("Docker Desktop cannot see the folder", "Docker Desktop no puede ver la carpeta")
            message = L("Docker Desktop refused one of ARVA's folders. In Docker Desktop: Settings → Resources → File sharing, add the folder (or the disk under /Volumes), press Apply, then Try again here.",
                        "Docker Desktop rechazó una de las carpetas de ARVA. En Docker Desktop: Settings → Resources → File sharing, añade la carpeta (o el disco bajo /Volumes), pulsa Apply y luego Reintentar aquí.")
        } else {
            title = L("ARVA could not start", "ARVA no pudo iniciarse")
            message = L("Something went wrong while starting ARVA (exit status \(status)). Press Try again; if it keeps happening, press Copy details and send the text to whoever helps you with ARVA.",
                        "Algo falló al iniciar ARVA (estado de salida \(status)). Pulsa Reintentar; si sigue pasando, pulsa Copiar detalles y envía el texto a quien te ayuda con ARVA.")
        }
        showError(title: title, message: message)
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
        startTask?.terminate()
        startTask = nil
        note(L("\nCancelled.\n", "\nCancelado.\n"))
        showError(title: L("Start cancelled", "Inicio cancelado"),
                  message: L("ARVA's start was cancelled. Press Try again to start it, or Quit.",
                             "Se canceló el inicio de ARVA. Pulsa Reintentar para iniciarlo, o Salir."))
    }

    /// A plain-language problem, with Try again, Copy details (what support needs) and Quit.
    private func showError(title: String, message: String) {
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
            alert.addButton(withTitle: L("Quit", "Salir"))
            switch alert.runModal() {
            case .alertFirstButtonReturn:
                begin()
                return
            case .alertSecondButtonReturn:
                copyDetailsToPasteboard()
                copiedNote = "\n\n" + L("The details were copied: paste them (⌘V) in a message.", "Se copiaron los detalles: pégalos (⌘V) en un mensaje.")
            default:
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
        web.show()
        splash?.window.orderOut(nil)
        NSApp.activate(ignoringOtherApps: true)
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
            alert.addButton(withTitle: L("Stop and quit", "Detener y salir"))
            alert.addButton(withTitle: L("Quit without stopping", "Salir sin detener"))
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

    private func stopAndQuit(quitDocker: Bool) {
        attempt += 1
        stopTimers()
        startTask?.terminate()
        startTask = nil
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
        note("$ sh scripts/stop.sh\n")
        let task = ShellTask(executable: "/bin/sh", arguments: ["scripts/stop.sh"], directory: AppPaths.runtimeDir,
                             environment: ShellEnvironment.make())
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
        watchdog = commonTimer(withTimeInterval: 180, repeats: false) { [weak task] _ in task?.terminate() }
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
                phase = .running
                splash?.window.orderOut(nil)
                mainWeb?.show()
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
        let folder = AppPaths.runtimeDir.appendingPathComponent("import", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        NSWorkspace.shared.open(folder)
    }
    @objc func arvaHelp(_ sender: Any?) {
        NSWorkspace.shared.open(Self.repository.appendingPathComponent("blob/main/docs/guia-mac-app.md"))
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
