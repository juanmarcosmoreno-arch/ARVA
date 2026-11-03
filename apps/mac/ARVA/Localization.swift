import Foundation

/// The app speaks Spanish when the first macOS preferred language is Spanish, English otherwise
/// (ARVA_APP_LANG=es|en overrides it, for the self-test and for support).
enum Lang {
    static let isSpanish: Bool = {
        if let forced = ProcessInfo.processInfo.environment["ARVA_APP_LANG"], !forced.isEmpty {
            return forced.lowercased().hasPrefix("es")
        }
        return (Locale.preferredLanguages.first ?? "en").lowercased().hasPrefix("es")
    }()

    static var code: String { isSpanish ? "es" : "en" }

    /// The locale passed to the launcher scripts: scripts/lib/arva-locations.sh reads LC_ALL, LC_MESSAGES and LANG
    /// (in that order) to choose its language, and a Finder-opened app has none of them.
    static var posixLocale: String { isSpanish ? "es_ES.UTF-8" : "en_US.UTF-8" }
}

/// The English or the Spanish text, following `Lang`.
func L(_ en: String, _ es: String) -> String {
    Lang.isSpanish ? es : en
}
