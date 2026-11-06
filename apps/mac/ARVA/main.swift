import AppKit

// ARVA.app: a native window for ARVA (http://localhost:8080) that starts and stops it with Docker Desktop.
//   ARVA --self-test                        check the app and exit (no window; used by CI)
//   ARVA --render-iconset LOGO.png DIR      draw the app icon's sizes (used by scripts/build-mac-app.sh)
//   ARVA --install-native-flye              install Flye for this Mac without a window (used by CI)
//   ARVA --remove-native-flye               remove it again
//   ARVA --install-native-bakta             install Bakta for this Mac without a window (used by CI)
//   ARVA --remove-native-bakta              remove it again
let arguments = CommandLine.arguments
if arguments.contains("--self-test") {
    exit(SelfTest.run())
}
if arguments.contains("--install-native-flye") {
    exit(NativeFlyeCLI.install())
}
if arguments.contains("--remove-native-flye") {
    exit(NativeFlyeCLI.remove())
}
if arguments.contains("--install-native-bakta") {
    exit(NativeFlyeCLI.install(tool: .bakta))
}
if arguments.contains("--remove-native-bakta") {
    exit(NativeFlyeCLI.remove(tool: .bakta))
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
