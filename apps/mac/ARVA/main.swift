import AppKit

// ARVA.app: a native window for ARVA (http://localhost:8080) that starts and stops it with Docker Desktop.
//   ARVA --self-test                        check the app and exit (no window; used by CI)
//   ARVA --render-iconset LOGO.png DIR      draw the app icon's sizes (used by scripts/build-mac-app.sh)
let arguments = CommandLine.arguments
if arguments.contains("--self-test") {
    exit(SelfTest.run())
}
if let index = arguments.firstIndex(of: "--render-iconset") {
    guard arguments.count > index + 2 else {
        FileHandle.standardError.write("usage: ARVA --render-iconset LOGO.png OUT.iconset\n".data(using: .utf8)!)
        exit(2)
    }
    exit(IconRenderer.render(source: arguments[index + 1], iconset: arguments[index + 2]))
}

let application = NSApplication.shared
let appDelegate = AppDelegate()
application.delegate = appDelegate
application.setActivationPolicy(.regular)
application.run()
