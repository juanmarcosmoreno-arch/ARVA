import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { matrixCell } from "@/lib/amr";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const MARK = { found: "●", incomplete: "◐", absent: "·", not_searched: "" } as const;
const CELL = {
  found: "text-arva-royal dark:text-arva-cyan",
  incomplete: "text-amber-700 dark:text-warning",
  absent: "text-muted-foreground",
  not_searched: "bg-muted/40",
} as const;

/** The presence/absence matrix of the elements AMRFinderPlus found across the project's samples (each sample's most
 * recent run): found, found only partly (partial, at a contig end, internal stop), not found, or not searched. */
export function ProjectAmr({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["projectAmr", projectId], queryFn: () => api.amrProject(projectId) });
  if (overview.error) return <ErrorNote error={overview.error} />;
  const o = overview.data;
  if (!o || o.searched === 0) return null;
  return (
    <Card className="mt-6 min-w-0" id="project-amr">
      <CardHeader
        title={t("projectAmr.title", { searched: o.searched, total: o.samples.length })}
        description={t("projectAmr.subtitle", { versions: o.versions.join("; ") })}
        action={
          <div className="flex items-center gap-2">
            <a href={api.amrMatrixCsvUrl(projectId)} className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {t("projectAmr.matrixCsv")}
            </a>
            <a href={api.amrProjectCsvUrl(projectId)} className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {t("projectAmr.csv")}
            </a>
            <Explain id="amr" compact />
          </div>
        }
      />
      <CardBody className="space-y-3 pt-3">
        <p className="text-xs text-muted-foreground">{t("amr.disclaimer")}</p>
        {o.elements.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("projectAmr.noneFound")}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="text-xs">
              <thead className="bg-muted/50">
                <tr>
                  <th className="sticky left-0 bg-muted/50 px-2 py-1.5 text-left font-medium text-muted-foreground">{t("projectMlst.sample")}</th>
                  {o.elements.map((e) => (
                    <th key={e.element_symbol} className="px-1 py-1.5 align-bottom font-medium text-muted-foreground" title={`${e.type}${e.subtype ? `/${e.subtype}` : ""}${e.class ? ` · ${e.class}` : ""}`}>
                      <span className="block max-h-32 whitespace-nowrap font-mono [writing-mode:vertical-rl] rotate-180">{e.element_symbol}</span>
                    </th>
                  ))}
                </tr>
                <tr>
                  <th className="sticky left-0 bg-muted/50 px-2 py-1 text-left text-[10px] font-normal text-muted-foreground">{t("projectAmr.type")}</th>
                  {o.elements.map((e) => (
                    <th key={e.element_symbol} className="px-1 py-1 text-[10px] font-normal text-muted-foreground">
                      {t(`projectAmr.typeShort.${e.subtype === "POINT" || e.subtype === "POINT_DISRUPT" ? "POINT" : e.type}` as TranslationKey)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {o.samples.map((s) => (
                  <tr key={s.sample_id}>
                    <td className="sticky left-0 whitespace-nowrap bg-surface px-2 py-1">
                      <Link to={`/samples/${s.sample_id}?tab=genomic`} className="text-arva-royal hover:underline dark:text-arva-cyan">
                        {s.sample_code}
                      </Link>
                      {!s.latest && <span className="ml-1 text-muted-foreground">{t("projectAmr.notSearched")}</span>}
                    </td>
                    {o.elements.map((e) => {
                      const cell = matrixCell(Boolean(s.latest), s.present[e.element_symbol]);
                      return (
                        <td key={e.element_symbol} className={cn("px-1 py-1 text-center", CELL[cell])} title={t(`projectAmr.cell.${cell}`)}>
                          {MARK[cell]}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">{t("projectAmr.legend")}</p>
      </CardBody>
    </Card>
  );
}
