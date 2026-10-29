import { useQuery } from "@tanstack/react-query";
import { FlaskConical, FolderKanban, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useT } from "@/i18n";
import { api } from "@/lib/api";

export function GlobalSearch() {
  const t = useT();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: open });
  const samples = useQuery({ queryKey: ["samples", "all"], queryFn: api.allSamples, enabled: open });

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    const p = (projects.data ?? [])
      .filter((x) => [x.name, x.description, x.institution].some((v) => v?.toLowerCase().includes(needle)))
      .map((x) => ({ id: x.id, kind: "project" as const, label: x.name, sub: `${x.sample_count} samples`, to: `/projects/${x.id}` }));
    const s = (samples.data ?? [])
      .filter((x) =>
        [x.sample_code, x.organism, x.expected_species, x.host, x.geographic_origin, x.sequencing_run].some((v) =>
          v?.toLowerCase().includes(needle),
        ),
      )
      .map((x) => ({
        id: x.id,
        kind: "sample" as const,
        label: x.sample_code,
        sub: [x.organism, x.project_name].filter(Boolean).join(" · "),
        to: `/samples/${x.id}`,
      }));
    return [...p, ...s].slice(0, 8);
  }, [q, projects.data, samples.data]);

  const go = (to: string) => {
    setQ("");
    setOpen(false);
    navigate(to);
  };

  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => e.key === "Enter" && results[0] && go(results[0].to)}
        placeholder={t("common.search")}
        aria-label={t("common.search")}
        className="h-10 w-full rounded-lg border bg-surface pl-9 pr-3 text-sm placeholder:text-muted-foreground/70"
      />
      {open && q.trim() && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-xl border bg-surface shadow-lg">
          {results.length === 0 ? (
            <div className="px-4 py-3 text-sm text-muted-foreground">{t("search.noMatches")}</div>
          ) : (
            results.map((r) => (
              <button
                key={`${r.kind}-${r.id}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(r.to)}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted"
              >
                {r.kind === "project" ? (
                  <FolderKanban className="h-4 w-4 text-arva-royal dark:text-arva-cyan" />
                ) : (
                  <FlaskConical className="h-4 w-4 text-arva-teal" />
                )}
                <span className="min-w-0">
                  <span className="block truncate text-sm">{r.label}</span>
                  <span className="block truncate text-xs text-muted-foreground">{r.sub}</span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
