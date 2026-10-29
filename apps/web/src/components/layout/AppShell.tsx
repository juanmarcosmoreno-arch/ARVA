import { Menu, Moon, Sun, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { ArvaMark } from "@/components/brand/ArvaLogo";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { resolveDark, useSettings } from "@/store/settings";
import { GlobalSearch } from "./GlobalSearch";
import { Sidebar } from "./Sidebar";

function useApplyTheme() {
  const theme = useSettings((s) => s.theme);
  const [dark, setDark] = useState(() => resolveDark(theme));
  useEffect(() => {
    const apply = () => {
      const d = resolveDark(theme);
      document.documentElement.classList.toggle("dark", d);
      setDark(d);
    };
    apply();
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener("change", apply);
    return () => mq?.removeEventListener("change", apply);
  }, [theme]);
  return dark;
}

export function AppShell() {
  const t = useT();
  const dark = useApplyTheme();
  const setTheme = useSettings((s) => s.setTheme);
  const language = useSettings((s) => s.language);
  const setLanguage = useSettings((s) => s.setLanguage);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 lg:block">
        <Sidebar />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-arva-navy/50" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64 animate-fade-in">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </div>
          <button
            className="absolute right-4 top-4 rounded-md bg-white/10 p-2 text-white"
            onClick={() => setMobileOpen(false)}
            aria-label={t("shell.closeMenu")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur sm:px-6">
          <button className="rounded-md p-2 hover:bg-muted lg:hidden" onClick={() => setMobileOpen(true)} aria-label={t("shell.openMenu")}>
            <Menu className="h-5 w-5" />
          </button>
          <ArvaMark className="h-7 w-7 lg:hidden" />
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLanguage(language === "en" ? "es" : "en")}
              aria-label={t("shell.switchLanguage")}
              className="font-semibold uppercase"
            >
              {language}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(dark ? "light" : "dark")}
              aria-label={dark ? t("shell.lightMode") : t("shell.darkMode")}
            >
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
