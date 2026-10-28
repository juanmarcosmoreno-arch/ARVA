import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";
export type Language = "en" | "es";
export type GuideLevel = "beginner" | "intermediate" | "advanced";

interface SettingsState {
  theme: Theme;
  language: Language;
  guideLevel: GuideLevel;
  showIntro: boolean;
  setTheme: (t: Theme) => void;
  setLanguage: (l: Language) => void;
  setGuideLevel: (g: GuideLevel) => void;
  setShowIntro: (v: boolean) => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "system",
      language: "en",
      guideLevel: "beginner",
      showIntro: true,
      setTheme: (theme) => set({ theme }),
      setLanguage: (language) => set({ language }),
      setGuideLevel: (guideLevel) => set({ guideLevel }),
      setShowIntro: (showIntro) => set({ showIntro }),
    }),
    { name: "arva-settings" },
  ),
);

export function resolveDark(theme: Theme) {
  if (theme === "system") return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  return theme === "dark";
}
