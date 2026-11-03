import AppKit
import UniformTypeIdentifiers
import WebKit

/// A window that shows ARVA. Only ARVA's own pages (http://localhost:8080) load inside it; other links open in the
/// default browser. No script message handler or other bridge is offered to the page: the two small scripts below run
/// in the app's own isolated JavaScript world, which the page cannot see or call.
final class WebWindowController: NSObject, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    static let mainAutosaveName = "ARVA.MainWindow"
    private static let zoomKey = "ARVA.pageZoom"

    /// Remembers the accept attribute of the file input last clicked (also by a script's input.click()), because
    /// WebKit does not hand it to the app with the open panel request.
    private static let acceptTracker = """
    document.addEventListener('click', function (event) {
      var t = event.target;
      if (t && t.tagName === 'INPUT' && String(t.type).toLowerCase() === 'file') {
        window.__arvaAccept = t.getAttribute('accept') || '';
        window.__arvaAcceptAt = Date.now();
      }
    }, true);
    """

    static func makeConfiguration() -> WKWebViewConfiguration {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        if #available(macOS 12.3, *) { config.preferences.isElementFullscreenEnabled = true }
        config.userContentController.addUserScript(
            WKUserScript(source: acceptTracker, injectionTime: .atDocumentStart, forMainFrameOnly: false, in: .defaultClient))
        return config
    }

    let window: NSWindow
    let webView: WKWebView
    let isMain: Bool
    /// Asks the app for a new window for a link that targets one (it must use the configuration WebKit gives).
    var makeWindow: ((WKWebViewConfiguration) -> WKWebView?)?
    var onClose: ((WebWindowController) -> Void)?

    private var downloads: [ObjectIdentifier: URL] = [:]
    private var toast: NSView?
    private var toastTimer: Timer?

    init(configuration: WKWebViewConfiguration, isMain: Bool) {
        self.isMain = isMain
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let size = NSSize(width: min(1360, visible.width * 0.9), height: min(880, visible.height * 0.9))
        window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        webView = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: configuration)
        super.init()

        window.title = "ARVA"
        window.minSize = NSSize(width: 720, height: 480)
        window.isRestorable = false
        window.tabbingMode = .disallowed
        window.isReleasedWhenClosed = false
        window.delegate = self

        let container = NSView(frame: NSRect(origin: .zero, size: size))
        webView.autoresizingMask = [.width, .height]
        webView.frame = container.bounds
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.allowsMagnification = true
        let zoom = UserDefaults.standard.double(forKey: Self.zoomKey)
        if zoom >= 0.5 && zoom <= 3 { webView.pageZoom = CGFloat(zoom) }
        container.addSubview(webView)
        window.contentView = container

        if isMain {
            if !window.setFrameUsingName(Self.mainAutosaveName) { window.center() }
            window.setFrameAutosaveName(Self.mainAutosaveName)
        } else {
            window.cascadeTopLeft(from: NSPoint(x: window.frame.minX + 24, y: window.frame.maxY - 24))
        }
    }

    func show() {
        window.makeKeyAndOrderFront(nil)
    }

    func loadARVA() {
        webView.load(URLRequest(url: ArvaServer.base))
    }

    // MARK: Menu commands

    func reload() {
        if let url = webView.url, WebPolicy.classify(url) == .local {
            webView.reload()
        } else {
            loadARVA()
        }
    }

    func setZoom(_ zoom: CGFloat) {
        let value = min(3, max(0.5, zoom))
        webView.pageZoom = value
        UserDefaults.standard.set(Double(value), forKey: Self.zoomKey)
    }

    func zoomIn() { setZoom(webView.pageZoom * 1.1) }
    func zoomOut() { setZoom(webView.pageZoom / 1.1) }
    func zoomReset() { setZoom(1) }

    /// The page shown, in the default browser (ARVA's address when the page is not one of ARVA's).
    func openInBrowser() {
        if let url = webView.url, WebPolicy.classify(url) == .local {
            NSWorkspace.shared.open(url)
        } else {
            NSWorkspace.shared.open(ArvaServer.base)
        }
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        toastTimer?.invalidate()
        onClose?(self)
    }

    // MARK: Navigation

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        guard let url = navigationAction.request.url else {
            decisionHandler(.allow)
            return
        }
        switch WebPolicy.classify(url) {
        case .local, .inert:
            decisionHandler(.allow)
        case .external:
            // A link the person followed (in any frame) opens in the browser; a frame that loads another site by
            // itself is just not loaded.
            let mainFrame = navigationAction.targetFrame?.isMainFrame ?? true
            if mainFrame || navigationAction.navigationType == .linkActivated {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        case .blocked:
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if let http = navigationResponse.response as? HTTPURLResponse,
           let disposition = http.value(forHTTPHeaderField: "Content-Disposition"),
           disposition.trimmingCharacters(in: .whitespaces).lowercased().hasPrefix("attachment") {
            decisionHandler(.download)
        } else if !navigationResponse.canShowMIMEType {
            decisionHandler(.download)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showUnreachable(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showUnreachable(error)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        reload()
    }

    private func showUnreachable(_ error: Error) {
        let nsError = error as NSError
        // Cancelled loads and loads turned into downloads are not failures.
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled { return }
        if nsError.domain == "WebKitErrorDomain" && (nsError.code == 102 || nsError.code == 204) { return }
        if let failing = nsError.userInfo[NSURLErrorFailingURLErrorKey] as? URL, WebPolicy.classify(failing) != .local {
            return
        }
        let title = L("ARVA is not answering", "ARVA no responde")
        let body = L("ARVA may have stopped, or Docker Desktop may have closed. Open Docker Desktop if needed, then try again (⌘R). If it keeps happening, quit ARVA and open it again.",
                     "Puede que ARVA se haya detenido o que Docker Desktop se haya cerrado. Abre Docker Desktop si hace falta y vuelve a intentarlo (⌘R). Si sigue pasando, sal de ARVA y vuelve a abrirlo.")
        let retry = L("Try again", "Reintentar")
        let html = """
        <!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light dark">
        <style>body{font:15px -apple-system,system-ui,sans-serif;max-width:34em;margin:18vh auto;padding:0 24px;line-height:1.5}
        a{display:inline-block;margin-top:12px;padding:6px 16px;border-radius:6px;background:#1d4ed8;color:#fff;text-decoration:none}</style>
        </head><body><h2>\(title)</h2><p>\(body)</p><a href="http://localhost:8080/">\(retry)</a></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: New windows, file inputs and dialogs

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        let url = navigationAction.request.url
        switch url.map(WebPolicy.classify) ?? .inert {
        case .local, .inert:
            return makeWindow?(configuration)
        case .external:
            if let url { NSWorkspace.shared.open(url) }
            return nil
        case .blocked:
            return nil
        }
    }

    func webViewDidClose(_ webView: WKWebView) {
        if !isMain { window.close() }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let script = "[window.__arvaAccept || '', Date.now() - (window.__arvaAcceptAt || 0)]"
        webView.evaluateJavaScript(script, in: frame, in: .defaultClient) { [weak self] result in
            var accept = ""
            if case .success(let value) = result, let pair = value as? [Any], pair.count == 2,
               let text = pair[0] as? String, let age = (pair[1] as? NSNumber)?.doubleValue, age >= 0, age < 10_000 {
                accept = text
            }
            guard let self else {
                completionHandler(nil)
                return
            }
            let panel = NSOpenPanel()
            panel.canChooseFiles = true
            panel.canChooseDirectories = parameters.allowsDirectories
            panel.allowsMultipleSelection = parameters.allowsMultipleSelection
            panel.resolvesAliases = true
            panel.prompt = L("Choose", "Elegir")
            if let types = WebPolicy.contentTypes(forAccept: accept) { panel.allowedContentTypes = types }
            panel.beginSheetModal(for: self.window) { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
        }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = "ARVA"
        alert.informativeText = message
        alert.addButton(withTitle: L("OK", "Aceptar"))
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = "ARVA"
        alert.informativeText = message
        alert.addButton(withTitle: L("OK", "Aceptar"))
        alert.addButton(withTitle: L("Cancel", "Cancelar"))
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = "ARVA"
        alert.informativeText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.addButton(withTitle: L("OK", "Aceptar"))
        alert.addButton(withTitle: L("Cancel", "Cancelar"))
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { response in
            completionHandler(response == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }

    // MARK: Downloads (reports sent as attachments, and exports the page makes as blob: links)

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let directory = AppPaths.downloads
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let taken = Set(downloads.values.map(\.path))
        let destination = WebPolicy.uniqueDestination(in: directory, suggested: suggestedFilename) { path in
            taken.contains(path) || FileManager.default.fileExists(atPath: path)
        }
        downloads[ObjectIdentifier(download)] = destination
        completionHandler(destination)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        // The Downloads stack in the Dock bounces, as for a download in Safari.
        DistributedNotificationCenter.default().post(name: Notification.Name("com.apple.DownloadFileFinished"),
                                                     object: url.resolvingSymlinksInPath().path)
        showToast(L("Downloaded to Downloads: \(url.lastPathComponent)", "Descargado en Descargas: \(url.lastPathComponent)"),
                  reveal: url)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let url = downloads.removeValue(forKey: ObjectIdentifier(download))
        let name = url?.lastPathComponent ?? ""
        showToast(L("The download \(name) failed: \(error.localizedDescription)",
                    "La descarga \(name) falló: \(error.localizedDescription)"), reveal: nil)
    }

    private func showToast(_ text: String, reveal: URL?) {
        toast?.removeFromSuperview()
        toastTimer?.invalidate()
        guard let container = window.contentView else { return }

        let box = NSVisualEffectView()
        box.material = .hudWindow
        box.blendingMode = .withinWindow
        box.state = .active
        box.wantsLayer = true
        box.layer?.cornerRadius = 10
        box.translatesAutoresizingMaskIntoConstraints = false

        let label = NSTextField(labelWithString: text)
        label.lineBreakMode = .byTruncatingMiddle
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        var views: [NSView] = [label]
        if let reveal {
            let button = ActionButton(title: L("Show in Finder", "Mostrar en Finder")) {
                NSWorkspace.shared.activateFileViewerSelecting([reveal])
            }
            views.append(button)
        }
        let close = ActionButton(title: "✕") { [weak self] in self?.hideToast() }
        close.isBordered = false
        views.append(close)
        let row = NSStackView(views: views)
        row.orientation = .horizontal
        row.spacing = 10
        row.edgeInsets = NSEdgeInsets(top: 8, left: 14, bottom: 8, right: 10)
        row.translatesAutoresizingMaskIntoConstraints = false
        box.addSubview(row)
        container.addSubview(box)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: box.leadingAnchor),
            row.trailingAnchor.constraint(equalTo: box.trailingAnchor),
            row.topAnchor.constraint(equalTo: box.topAnchor),
            row.bottomAnchor.constraint(equalTo: box.bottomAnchor),
            box.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            box.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -20),
            box.widthAnchor.constraint(lessThanOrEqualTo: container.widthAnchor, constant: -40),
        ])
        toast = box
        toastTimer = Timer.scheduledTimer(withTimeInterval: 8, repeats: false) { [weak self] _ in self?.hideToast() }
    }

    private func hideToast() {
        toast?.removeFromSuperview()
        toast = nil
    }
}

/// A push button that runs a closure.
final class ActionButton: NSButton {
    private var handler: () -> Void = {}

    convenience init(title: String, handler: @escaping () -> Void) {
        self.init(frame: .zero)
        self.title = title
        self.bezelStyle = .rounded
        self.setButtonType(.momentaryPushIn)
        self.handler = handler
        self.target = self
        self.action = #selector(run)
    }

    @objc private func run() { handler() }
}
