import { useQuery } from "@tanstack/react-query";
import { Construction, Microscope } from "lucide-react";
import { Link } from "react-router-dom";
import { MlstTable } from "@/components/genomic/ProjectMlst";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";

/** Genomic analysis across projects: which samples have an MLST result, the most recent results, and the Phase 5
 * analyses that are still planned. */
export function GenomicPage() {
  const t = useT();
  const overview = useQuery({ queryKey: ["mlstOverview"], queryFn: () => api.mlstOverview() });
  const species = useQuery({ queryKey: ["speciesOverview"], queryFn: () => api.speciesOverview() });
  const o = overview.data;
  const identified = new Map((species.data?.projects ?? []).map((p) => [p.project_id, p.identified_samples]));
  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title={t("nav.genomic")} subtitle={t("genomic.subtitle")} actions={<><Explain id="ani" /><Explain id="mlst" /></>} />
      {overview.isLoading && <Skeleton className="h-40" />}
      <ErrorNote error={overview.error ?? species.error} />
      {o && (
        <Card>
          <CardHeader title={t("genomic.projectsTitle")} description={t("genomic.projectsSubtitle", { n: o.total_results })} />
          <CardBody className="pt-3">
            {o.projects.length === 0 ? (
              <EmptyState icon={<Microscope className="h-7 w-7" />} title={t("genomic.noProjects")} />
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("projectMlst.project")}</th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("genomic.samples")}</th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("genomic.identified")}</th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("genomic.typed")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {o.projects.map((p) => (
                      <tr key={p.project_id}>
                        <td className="px-2 py-1.5">
                          <Link to={`/projects/${p.project_id}#project-mlst`} className="text-arva-royal hover:underline dark:text-arva-cyan">
                            {p.project_name}
                          </Link>{" "}
                          {p.is_demo && <Badge tone="warning">{t("common.demo")}</Badge>}
                        </td>
                        <td className="px-2 py-1.5 tabular-nums">{p.samples}</td>
                        <td className="px-2 py-1.5 tabular-nums">{identified.get(p.project_id) ?? 0}</td>
                        <td className="px-2 py-1.5 tabular-nums">{p.typed_samples}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>
      )}
      {o && o.recent.length > 0 && (
        <Card>
          <CardHeader title={t("genomic.recentTitle")} description={t("genomic.recentSubtitle")} />
          <CardBody className="pt-3">
            <MlstTable rows={o.recent.map((r) => ({ sampleId: r.sample_id, sampleCode: r.sample_code, row: r }))} showProject />
          </CardBody>
        </Card>
      )}
      <Card className="px-5 py-4">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Construction className="h-4 w-4 text-muted-foreground" aria-hidden /> {t("genomic.plannedTitle")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{t("genomic.plannedText")}</p>
      </Card>
    </div>
  );
}
