import { useQuery } from "@tanstack/react-query";
import { BarChart3, ChevronRight, FileText, FlaskConical } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, technologyLabel } from "@/lib/format";
import type { Sample } from "@/lib/types";

export function SamplesTable({ samples, showProject = true, tab }: { samples: Sample[]; showProject?: boolean; tab?: string }) {
  const t = useT();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="px-5 py-3 font-medium">{t("bulk.sampleId")}</th>
            <th className="px-3 py-3 font-medium">{t("samples.col.organism")}</th>
            {showProject && <th className="px-3 py-3 font-medium">{t("samples.col.project")}</th>}
            <th className="px-3 py-3 font-medium">{t("samples.col.technology")}</th>
            <th className="px-3 py-3 font-medium">{t("samples.col.files")}</th>
            <th className="hidden px-3 py-3 font-medium md:table-cell">{t("samples.col.updated")}</th>
            <th className="px-3 py-3" />
          </tr>
        </thead>
        <tbody>
          {samples.map((s) => (
            <tr key={s.id} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-5 py-3 font-medium">
                <Link to={`/samples/${s.id}${tab ? `?tab=${tab}` : ""}`} className="hover:underline">
                  {s.sample_code}
                </Link>
              </td>
              <td className="px-3 py-3 italic text-muted-foreground">{s.organism || "—"}</td>
              {showProject && (
                <td className="px-3 py-3">
                  <Link to={`/projects/${s.project_id}`} className="text-muted-foreground hover:underline">
                    {s.project_name}
                  </Link>
                </td>
              )}
              <td className="px-3 py-3">
                <Badge tone={s.sequencing_technology === "unknown" ? "neutral" : "blue"}>{technologyLabel(s.sequencing_technology)}</Badge>
              </td>
              <td className="px-3 py-3 tabular-nums">{s.file_count}</td>
              <td className="hidden px-3 py-3 text-xs text-muted-foreground md:table-cell">{fmtDate(s.updated_at)}</td>
              <td className="px-3 py-3 text-right">
                <Link to={`/samples/${s.id}${tab ? `?tab=${tab}` : ""}`} aria-label={t("samples.open", { sample: s.sample_code })}>
                  <ChevronRight className="inline h-4 w-4 text-muted-foreground" />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CONTEXT: Record<string, { title: TranslationKey; subtitle: TranslationKey; tab?: string; icon: typeof FlaskConical }> = {
  samples: { title: "samples.title", subtitle: "samples.subtitle", icon: FlaskConical },
  qc: {
    title: "nav.qc",
    subtitle: "samples.qcSubtitle",
    tab: "qc",
    icon: BarChart3,
  },
  reports: {
    title: "nav.reports",
    subtitle: "samples.reportsSubtitle",
    tab: "qc",
    icon: FileText,
  },
};

export function SamplesPage({ context = "samples" }: { context?: "samples" | "qc" | "reports" }) {
  const t = useT();
  const cfg = CONTEXT[context];
  const { data, isLoading, error } = useQuery({ queryKey: ["samples", "all"], queryFn: api.allSamples });
  return (
    <div className="animate-fade-in">
      <PageHeader title={t(cfg.title)} subtitle={t(cfg.subtitle)} />
      <ErrorNote error={error} />
      <Card>
        {isLoading ? (
          <Skeleton className="m-5 h-24" />
        ) : data?.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={<cfg.icon className="h-7 w-7" />} title={t("samples.noneYet")}>
              {t("samples.noneYetHint")}{" "}
              <Link to="/projects" className="text-arva-royal underline dark:text-arva-cyan">
                {t("samples.goToProjects")}
              </Link>
            </EmptyState>
          </div>
        ) : (
          <SamplesTable samples={data ?? []} tab={cfg.tab} />
        )}
      </Card>
    </div>
  );
}
