import { NavLink } from "react-router-dom";
import { ArvaWordmark } from "@/components/brand/ArvaLogo";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { NAV } from "./nav";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const t = useT();
  return (
    <nav aria-label={t("nav.main")} className="flex h-full flex-col bg-arva-navy text-slate-200">
      <div className="px-5 pb-4 pt-5 text-white">
        <ArvaWordmark tagline />
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {NAV.map((section, i) => (
          <div key={i}>
            {section.label && (
              <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                {t(section.label)}
              </div>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.key}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        "group flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors",
                        isActive ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <item.icon className={cn("h-4 w-4 shrink-0", isActive ? "text-arva-teal" : "text-slate-400")} />
                        <span className="flex-1 truncate">{t(item.label)}</span>
                        {item.plannedPhase !== undefined && (
                          <span className="rounded bg-white/5 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-500">
                            P{item.plannedPhase}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-white/5 px-5 py-3 text-[10px] tracking-[0.18em] text-slate-500">
        {t("brand.motto")}
      </div>
    </nav>
  );
}
