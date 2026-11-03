import AppKit

/// The menu bar, built in code (no nib), in the app's language.
enum MainMenu {
    private static func item(_ title: String, _ action: Selector?, _ key: String = "",
                             _ modifiers: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        return item
    }

    private static func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
        let top = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let menu = NSMenu(title: title)
        for item in items { menu.addItem(item) }
        top.submenu = menu
        return top
    }

    static func build() -> NSMenu {
        let bar = NSMenu()

        let app = submenu("ARVA", [
            item(L("About ARVA", "Acerca de ARVA"), #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item(L("Set Up Again…", "Volver a configurar…"), #selector(AppDelegate.arvaSetupAgain(_:))),
            .separator(),
            item(L("Hide ARVA", "Ocultar ARVA"), #selector(NSApplication.hide(_:)), "h"),
            item(L("Hide Others", "Ocultar otros"), #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item(L("Show All", "Mostrar todo"), #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item(L("Quit ARVA", "Salir de ARVA"), #selector(NSApplication.terminate(_:)), "q"),
        ])
        bar.addItem(app)

        bar.addItem(submenu(L("File", "Archivo"), [
            item(L("Open the Import Folder", "Abrir la carpeta de importación"), #selector(AppDelegate.arvaShowImportFolder(_:))),
            .separator(),
            item(L("Close Window", "Cerrar ventana"), #selector(NSWindow.performClose(_:)), "w"),
        ]))

        bar.addItem(submenu(L("Edit", "Edición"), [
            item(L("Undo", "Deshacer"), Selector(("undo:")), "z"),
            item(L("Redo", "Rehacer"), Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item(L("Cut", "Cortar"), #selector(NSText.cut(_:)), "x"),
            item(L("Copy", "Copiar"), #selector(NSText.copy(_:)), "c"),
            item(L("Paste", "Pegar"), #selector(NSText.paste(_:)), "v"),
            item(L("Select All", "Seleccionar todo"), #selector(NSText.selectAll(_:)), "a"),
        ]))

        bar.addItem(submenu(L("View", "Visualización"), [
            item(L("Reload Page", "Volver a cargar la página"), #selector(AppDelegate.arvaReload(_:)), "r"),
            .separator(),
            item(L("Actual Size", "Tamaño real"), #selector(AppDelegate.arvaZoomReset(_:)), "0"),
            item(L("Zoom In", "Ampliar"), #selector(AppDelegate.arvaZoomIn(_:)), "+"),
            item(L("Zoom Out", "Reducir"), #selector(AppDelegate.arvaZoomOut(_:)), "-"),
            .separator(),
            item(L("Back", "Atrás"), #selector(AppDelegate.arvaBack(_:)), "["),
            item(L("Forward", "Adelante"), #selector(AppDelegate.arvaForward(_:)), "]"),
            .separator(),
            item(L("View in Browser", "Ver en el navegador"), #selector(AppDelegate.arvaOpenInBrowser(_:)), "b", [.command, .shift]),
            .separator(),
            item(L("Enter Full Screen", "Pantalla completa"), #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ]))

        let window = submenu(L("Window", "Ventana"), [
            item(L("Minimize", "Minimizar"), #selector(NSWindow.performMiniaturize(_:)), "m"),
            item(L("Zoom", "Zoom"), #selector(NSWindow.performZoom(_:))),
            .separator(),
            item(L("Bring All to Front", "Traer todo al frente"), #selector(NSApplication.arrangeInFront(_:))),
        ])
        bar.addItem(window)
        NSApp.windowsMenu = window.submenu

        let help = submenu(L("Help", "Ayuda"), [
            item(L("ARVA for Mac Guide", "Guía de ARVA para Mac"), #selector(AppDelegate.arvaHelp(_:))),
            item(L("Copy Start Details", "Copiar detalles del inicio"), #selector(AppDelegate.arvaCopyDetails(_:))),
        ])
        bar.addItem(help)
        NSApp.helpMenu = help.submenu
        return bar
    }
}
