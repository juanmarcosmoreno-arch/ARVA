import AppKit

/// ARVA → Flye for This Mac… (and Bakta for This Mac…): what it is, whether it is installed and ready, and Install /
/// Reinstall / Remove. The installation shows its progress (and every command with its output under Details) in a
/// small window of its own.
final class NativeFlyeUI {
    static var menuTitle: String { L("Flye for This Mac…", "Flye para esta Mac…") }
    static var baktaMenuTitle: String { L("Bakta for This Mac…", "Bakta para esta Mac…") }

    private let executor: NativeExecutor
    private let tool: NativeTool
    private var installer: NativeFlyeInstaller?
    private var window: StartupWindow?
    /// Called after the tool was installed or removed for this Mac.
    var onChange: (() -> Void)?

    init(executor: NativeExecutor, tool: NativeTool = .flye) {
        self.executor = executor
        self.tool = tool
    }

    private var explanation: String {
        if tool == .bakta {
            return L("Bakta 1.12.2 runs DIAMOND with a fixed block size (3 billion letters); with the full database that needs more memory than Docker has on a Mac with 8 GB, and Bakta has no option to lower it. ARVA.app can run the same Bakta release directly on macOS (Bioconda's packages for Apple silicon, with DIAMOND, BLAST+, AMRFinderPlus and every other program Bakta runs), installed only from ARVA's lock file, in which every package is pinned by its checksum. Bakta reads the databases from the database folders of arva.conf. Everything else stays in Docker; your genomes never leave this Mac.",
                     "Bakta 1.12.2 corre DIAMOND con un tamaño de bloque fijo (3 mil millones de letras); con la base completa eso necesita más memoria de la que Docker tiene en una Mac con 8 GB, y Bakta no tiene opción para bajarla. ARVA.app puede ejecutar la misma versión de Bakta directamente en macOS (los paquetes de Bioconda para Apple silicon, con DIAMOND, BLAST+, AMRFinderPlus y todos los demás programas que corre Bakta), instalada solo desde el archivo lock de ARVA, en el que cada paquete está fijado por su suma de verificación. Bakta lee las bases desde las carpetas de bases de datos de arva.conf. Todo lo demás sigue en Docker; tus genomas nunca salen de esta Mac.")
        }
        return L("Flye 2.9.6 reserves a fixed 8 GiB table to count k-mers, more than Docker has on a Mac with 8 GB. ARVA.app can run the same Flye version directly on macOS (Bioconda's build for Apple silicon), installed only from ARVA's lock file, in which every package is pinned by its checksum. Everything else stays in Docker; your reads never leave this Mac.",
                 "Flye 2.9.6 reserva una tabla fija de 8 GiB para contar k-mers, más de lo que Docker tiene en una Mac con 8 GB. ARVA.app puede ejecutar la misma versión de Flye directamente en macOS (la compilación de Bioconda para Apple silicon), instalada solo desde el archivo lock de ARVA, en el que cada paquete está fijado por su suma de verificación. Todo lo demás sigue en Docker; tus lecturas nunca salen de esta Mac.")
    }

    /// What install.json says (version, build, when), for the dialog.
    private func installedSummary() -> String? {
        guard tool.isInstalled,
              let data = try? Data(contentsOf: tool.installRecord),
              let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let version = record["\(tool.id)_version"] as? String ?? "?"
        let build = record["build"] as? String ?? "?"
        let date = (record["installed_at"] as? String).map { String($0.prefix(10)) } ?? "?"
        return L("Installed: \(tool.name) \(version), build \(build) (osx-arm64), on \(date), in \(AppInfo.tilde(tool.envPrefix.path)).",
                 "Instalado: \(tool.name) \(version), compilación \(build) (osx-arm64), el \(date), en \(AppInfo.tilde(tool.envPrefix.path)).")
    }

    func show() {
        if let window, installer != nil {
            window.show()
            return
        }
        let alert = NSAlert()
        alert.messageText = L("\(tool.name) for This Mac", "\(tool.name) para esta Mac")
        if let problem = NativeFlyeInstaller.preflight(tool: tool), !NativePaths.platformSupported || !tool.isInstalled {
            alert.informativeText = explanation + "\n\n" + problem
            alert.addButton(withTitle: L("Close", "Cerrar"))
            alert.runModal()
            return
        }
        let installed = installedSummary()
        var info = explanation + "\n\n"
        if let installed {
            info += installed + "\n" + executor.phaseText
        } else if NativeFlyeInstaller.somethingInstalled(tool: tool) {
            info += L("Something that ARVA.app did not install (or did not finish installing) is in \(AppInfo.tilde(tool.envPrefix.path)); installing replaces it.",
                      "En \(AppInfo.tilde(tool.envPrefix.path)) hay algo que ARVA.app no instaló (o no terminó de instalar); instalar lo reemplaza.")
        } else {
            info += L("Not installed.", "No instalado.")
        }
        alert.informativeText = info
        let install = alert.addButton(withTitle: installed == nil ? L("Install…", "Instalar…") : L("Reinstall…", "Reinstalar…"))
        if installed != nil { alert.addButton(withTitle: L("Remove…", "Quitar…")) }
        let close = alert.addButton(withTitle: L("Close", "Cerrar"))
        close.keyEquivalent = "\u{1b}"
        if installed != nil {
            install.keyEquivalent = ""
            close.keyEquivalent = "\r"
        }
        let response = alert.runModal()
        switch response {
        case .alertFirstButtonReturn:
            confirmInstall()
        case .alertSecondButtonReturn where installed != nil:
            confirmRemove()
        default:
            return
        }
    }

    private func busyAlert() -> Bool {
        guard executor.isBusy else { return false }
        let alert = NSAlert()
        alert.messageText = L("A native run is going on on this Mac", "Hay una ejecución nativa en curso en esta Mac")
        alert.informativeText = L("Wait until the assembly or annotation ends (or cancel it in ARVA), then try again.",
                                  "Espera a que termine el ensamblaje o la anotación (o cancélalo en ARVA) y vuelve a intentarlo.")
        alert.runModal()
        return true
    }

    private func confirmInstall() {
        guard !busyAlert() else { return }
        let alert = NSAlert()
        alert.messageText = L("Install \(tool.name) for this Mac?", "¿Instalar \(tool.name) para esta Mac?")
        alert.informativeText = L("ARVA.app downloads micromamba (its checksum is checked) and \(tool.downloadEN) from conda.anaconda.org, exactly as ARVA's lock lists them, into \(AppInfo.tilde(tool.envPrefix.path)). Only packages are downloaded: nothing about your data is sent. Then it checks every package against the lock and \(tool.name)'s version and options.",
                                  "ARVA.app descarga micromamba (se comprueba su suma de verificación) y \(tool.downloadES) de conda.anaconda.org, exactamente como los lista el lock de ARVA, en \(AppInfo.tilde(tool.envPrefix.path)). Solo se descargan paquetes: no se envía nada de tus datos. Después comprueba cada paquete contra el lock, y la versión y las opciones de \(tool.name).")
        alert.addButton(withTitle: L("Install", "Instalar"))
        let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
        cancel.keyEquivalent = "\u{1b}"
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        install()
    }

    private func install() {
        let window = self.window ?? StartupWindow()
        self.window = window
        window.window.title = L("\(tool.name) for This Mac", "\(tool.name) para esta Mac")
        window.clearDetails()
        window.setStatus(L("Installing \(tool.name) for this Mac…", "Instalando \(tool.name) para esta Mac…"),
                         hint: L("A few minutes; ARVA can be used meanwhile.", "Unos minutos; mientras tanto se puede usar ARVA."))
        window.setCancel(L("Cancel", "Cancelar"))
        window.appendDetails(AppInfo.summary + "\n")
        executor.suspend()
        let installer = NativeFlyeInstaller(tool: tool)
        self.installer = installer
        window.onCancel = { [weak installer] in installer?.cancel() }
        window.onClose = nil
        installer.onOutput = { [weak window] text in window?.appendDetails(text) }
        installer.onStep = { [weak window] text in
            window?.setStatus(text, hint: L("A few minutes; ARVA can be used meanwhile.", "Unos minutos; mientras tanto se puede usar ARVA."))
        }
        installer.onFinish = { [weak self, weak window] outcome in
            guard let self else { return }
            self.installer = nil
            window?.setCancel(nil)
            self.onChange?()
            switch outcome {
            case .installed:
                let name = self.tool.name
                window?.setStatus(L("\(name) for this Mac is installed.", "\(name) para esta Mac está instalado."))
                window?.window.orderOut(nil)
                let alert = NSAlert()
                alert.messageText = L("\(name) for this Mac is installed", "\(name) para esta Mac está instalado")
                alert.informativeText = L("When Docker has too little memory for \(name), ARVA's \(name) dialog now offers “Run on this Mac (native)”. ARVA.app must stay open while such a run goes on.",
                                          "Cuando Docker tiene poca memoria para \(name), el diálogo de \(name) de ARVA ahora ofrece “Ejecutar en esta Mac (nativo)”. ARVA.app debe quedar abierta mientras dura esa ejecución.")
                alert.runModal()
            case .failed(let message):
                window?.setStatus(L("\(self.tool.name) for this Mac could not be installed.", "No se pudo instalar \(self.tool.name) para esta Mac."),
                                  hint: message)
                window?.show()
            case .cancelled:
                window?.setStatus(L("Installation cancelled.", "Instalación cancelada."))
            }
        }
        window.show()
        installer.start()
    }

    private func confirmRemove() {
        guard !busyAlert() else { return }
        let alert = NSAlert()
        alert.messageText = L("Remove \(tool.name) for this Mac?", "¿Quitar \(tool.name) para esta Mac?")
        alert.informativeText = L("\(AppInfo.tilde(tool.envPrefix.path)) is deleted. Results already made are kept; \(tool.name) then runs only in Docker.",
                                  "Se borra \(AppInfo.tilde(tool.envPrefix.path)). Los resultados ya hechos se conservan; \(tool.name) vuelve a ejecutarse solo en Docker.")
        alert.addButton(withTitle: L("Remove", "Quitar"))
        let cancel = alert.addButton(withTitle: L("Cancel", "Cancelar"))
        cancel.keyEquivalent = "\u{1b}"
        guard alert.runModal() == .alertFirstButtonReturn, !busyAlert() else { return }
        executor.suspend()
        do {
            try NativeFlyeInstaller.remove(tool: tool)
        } catch {
            let failed = NSAlert()
            failed.alertStyle = .warning
            failed.messageText = L("\(tool.name) for this Mac was not removed", "No se quitó \(tool.name) para esta Mac")
            failed.informativeText = error.localizedDescription
            failed.runModal()
        }
        onChange?()
    }
}
