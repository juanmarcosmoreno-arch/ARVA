import AppKit

/// The small window shown while ARVA starts or stops: what is happening in one sentence, a progress bar, and a
/// "Details" area (closed by default) with everything the launcher prints.
final class StartupWindow: NSObject, NSWindowDelegate {
    let window: NSWindow
    private let statusLabel = NSTextField(wrappingLabelWithString: "")
    private let hintLabel = NSTextField(wrappingLabelWithString: "")
    private let progress = NSProgressIndicator()
    private let detailsButton = NSButton()
    private let detailsScroll = NSScrollView()
    private let detailsText = NSTextView()
    private let cancelButton = NSButton()
    private var detailsShown = false
    var onCancel: (() -> Void)?
    var onClose: (() -> Void)?

    override init() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 220),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        super.init()
        window.title = "ARVA"
        window.isRestorable = false
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.delegate = self

        let logo = NSImageView()
        logo.image = Bundle.main.image(forResource: "arva-logo") ?? NSApp.applicationIconImage
        logo.imageScaling = .scaleProportionallyUpOrDown
        logo.translatesAutoresizingMaskIntoConstraints = false
        logo.widthAnchor.constraint(equalToConstant: 64).isActive = true
        logo.heightAnchor.constraint(equalToConstant: 64).isActive = true

        let title = NSTextField(labelWithString: "ARVA")
        title.font = NSFont.systemFont(ofSize: 20, weight: .semibold)
        statusLabel.font = NSFont.systemFont(ofSize: 13)
        statusLabel.preferredMaxLayoutWidth = 400
        hintLabel.font = NSFont.systemFont(ofSize: 11)
        hintLabel.textColor = .secondaryLabelColor
        hintLabel.preferredMaxLayoutWidth = 400
        hintLabel.isHidden = true

        progress.style = .bar
        progress.isIndeterminate = true
        progress.controlSize = .regular
        progress.translatesAutoresizingMaskIntoConstraints = false
        progress.widthAnchor.constraint(equalToConstant: 400).isActive = true
        progress.startAnimation(nil)

        let texts = NSStackView(views: [title, statusLabel, progress, hintLabel])
        texts.orientation = .vertical
        texts.alignment = .leading
        texts.spacing = 8
        let header = NSStackView(views: [logo, texts])
        header.orientation = .horizontal
        header.alignment = .top
        header.spacing = 16

        detailsButton.setButtonType(.pushOnPushOff)
        detailsButton.bezelStyle = .disclosure
        detailsButton.title = ""
        detailsButton.target = self
        detailsButton.action = #selector(toggleDetails)
        let detailsLabel = NSTextField(labelWithString: L("Details", "Detalles"))
        detailsLabel.font = NSFont.systemFont(ofSize: 12)
        let clickable = NSClickGestureRecognizer(target: self, action: #selector(toggleFromLabel))
        detailsLabel.addGestureRecognizer(clickable)
        cancelButton.title = L("Cancel", "Cancelar")
        cancelButton.bezelStyle = .rounded
        cancelButton.target = self
        cancelButton.action = #selector(cancel)
        cancelButton.isHidden = true
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let footer = NSStackView(views: [detailsButton, detailsLabel, spacer, cancelButton])
        footer.orientation = .horizontal
        footer.spacing = 4

        detailsText.isEditable = false
        detailsText.isSelectable = true
        detailsText.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        detailsText.textContainerInset = NSSize(width: 6, height: 6)
        detailsText.isVerticallyResizable = true
        detailsText.autoresizingMask = [.width]
        detailsText.textContainer?.widthTracksTextView = true
        detailsScroll.documentView = detailsText
        detailsScroll.hasVerticalScroller = true
        detailsScroll.borderType = .bezelBorder
        detailsScroll.translatesAutoresizingMaskIntoConstraints = false
        detailsScroll.heightAnchor.constraint(equalToConstant: 220).isActive = true
        detailsScroll.isHidden = true

        let stack = NSStackView(views: [header, footer, detailsScroll])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 16, right: 20)
        stack.translatesAutoresizingMaskIntoConstraints = false
        footer.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView()
        content.addSubview(stack)
        window.contentView = content
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            stack.widthAnchor.constraint(equalToConstant: 520),
            footer.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -40),
            detailsScroll.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -40),
        ])
        fit()
        window.center()
    }

    func show() {
        window.makeKeyAndOrderFront(nil)
    }

    func setStatus(_ text: String, hint: String? = nil) {
        statusLabel.stringValue = text
        hintLabel.stringValue = hint ?? ""
        hintLabel.isHidden = (hint ?? "").isEmpty
        fit()
    }

    /// A cancel button (nil hides it).
    func setCancel(_ title: String?) {
        cancelButton.isHidden = title == nil
        if let title { cancelButton.title = title }
    }

    func clearDetails() {
        detailsText.string = ""
    }

    func appendDetails(_ text: String) {
        guard let storage = detailsText.textStorage else { return }
        let atEnd = detailsScroll.verticalScroller.map { $0.floatValue > 0.98 } ?? true
        storage.append(NSAttributedString(string: text, attributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: NSColor.textColor,
        ]))
        if storage.length > 300_000 {
            storage.deleteCharacters(in: NSRange(location: 0, length: storage.length - 250_000))
        }
        if atEnd || !detailsShown { detailsText.scrollToEndOfDocument(nil) }
    }

    @objc private func toggleFromLabel() {
        detailsButton.state = detailsButton.state == .on ? .off : .on
        toggleDetails()
    }

    @objc private func toggleDetails() {
        detailsShown = detailsButton.state == .on
        detailsScroll.isHidden = !detailsShown
        fit()
        if detailsShown { detailsText.scrollToEndOfDocument(nil) }
    }

    @objc private func cancel() {
        onCancel?()
    }

    /// Resizes the window to its content, keeping its top edge where it is.
    private func fit() {
        guard let content = window.contentView else { return }
        content.layoutSubtreeIfNeeded()
        let size = content.fittingSize
        var frame = window.frameRect(forContentRect: NSRect(origin: .zero, size: size))
        frame.origin.x = window.frame.minX
        frame.origin.y = window.frame.maxY - frame.height
        window.setFrame(frame, display: true, animate: false)
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }
}
