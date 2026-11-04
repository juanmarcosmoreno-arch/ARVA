import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";
export type Language = "en" | "es";
export type GuideLevel = "beginner" | "intermediate" | "advanced";

/** The language of the browser (or of macOS, in ARVA.app's web view): Spanish when its first preferred language is
 * Spanish (es, es-AR, es-419…), English otherwise. Used until the user picks a language. */
export function browserLanguage(nav: Partial<Pick<Navigator, "language" | "languages">> | undefined = globalThis.navigator): Language {
  const first = nav?.languages?.[0] ?? nav?.language ?? "";
  return /^es(-|_|$)/i.test(first) ? "es" : "en";
}

interface SettingsState {
  theme: Theme;
  language: Language;
  /** True once the user has picked the language (Settings, or the header's switch); until then it follows the browser. */
  languageChosen: boolean;
  guideLevel: GuideLevel;
  showIntro: boolean;
  /** The Dashboard's getting-started checklist (components/platform/FirstRunChecklist.tsx). */
  showChecklist: boolean;
  /** Diagnostic reports replace project, sample and file names (Settings → Diagnostics, and every copy button). */
  diagnosticsAnonymise: boolean;
  setTheme: (t: Theme) => void;
  setLanguage: (l: Language) => void;
  setGuideLevel: (g: GuideLevel) => void;
  setShowIntro: (v: boolean) => void;
  setShowChecklist: (v: boolean) => void;
  setDiagnosticsAnonymise: (v: boolean) => void;
}

/** The stored settings over the defaults. A language stored before `languageChosen` existed: Spanish is kept (it was
 * always picked by hand, English being the old default); English may be only that old default, so the browser's
 * language decides until the user picks one. */
export function mergeStored<S extends Pick<SettingsState, "language" | "languageChosen">>(persisted: unknown, current: S): S {
  const p = (persisted && typeof persisted === "object" ? persisted : {}) as Partial<SettingsState>;
  const chosen = typeof p.languageChosen === "boolean" ? p.languageChosen : p.language === "es";
  const language = chosen && (p.language === "en" || p.language === "es") ? p.language : browserLanguage();
  return { ...current, ...p, languageChosen: chosen, language };
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "system",
      language: browserLanguage(),
      languageChosen: false,
      guideLevel: "beginner",
      showIntro: true,
      showChecklist: true,
      diagnosticsAnonymise: false,
      setTheme: (theme) => set({ theme }),
      setLanguage: (language) => set({ language, languageChosen: true }),
      setGuideLevel: (guideLevel) => set({ guideLevel }),
      setShowIntro: (showIntro) => set({ showIntro }),
      setShowChecklist: (showChecklist) => set({ showChecklist }),
      setDiagnosticsAnonymise: (diagnosticsAnonymise) => set({ diagnosticsAnonymise }),
    }),
    {
      name: "arva-settings",
      merge: (persisted, current) => mergeStored(persisted, current),
    },
  ),
);

export function resolveDark(theme: Theme) {
  if (theme === "system") return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  return theme === "dark";
}
