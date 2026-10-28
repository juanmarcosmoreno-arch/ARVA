import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt, fmtNum } from "@/lib/format";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 tabular-nums whitespace-nowrap";

/** Every assembly of the project's samples, one row each, with ARVA's statistics and the assembler's circularity. */
export function ProjectAssemblies({ projectId }: { projectId: string }) {
  const t = useT();
  const rows = useQuery({ queryKey: ["projectAssemblies", projectId], queryFn: () => api.projectAssemblies(projectId) });
  if (rows.error) return <ErrorNote error={rows.error} />;
  if (!rows.data?.length) return null;
  const columns: TranslationKey[] = [
    "projectAssemblies.sample",
    "projectAssemblies.assembler",
    "assembly.stat.contigs",
    "assembly.stat.totalLength",
    "assembly.stat.n50",
    "assembly.stat.largest",
    "assembly.stat.gc",
    "assembly.stat.circular",
    "assembly.stat.medianCoverage",
    "projectAssemblies.warnings",
    "projectAssemblies.date",
  ];
  return (
    <Card className="mt-6 min-w-0" id="project-assemblies">
      <CardHeader title={t("projectAssemblies.title", { count: rows.data.length })} description={t("projectAssemblies.subtitle")} action={<Explain id="assembly" compact />} />
      <CardBody className="pt-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                {columns.map((c) => (
                  <th key={c} className={TH}>
                    {t(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.data.map((r) => (
                <tr key={r.id}>
                  <td className="px-2 py-1.5">
                    <Link to={`/samples/${r.sample_id}?tab=assembly`} className="whitespace-nowrap text-arva-royal hover:underline dark:text-arva-cyan">
                      {r.sample_code}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    {r.assembler} {r.assembler_version} <span className="text-muted-foreground">· --{r.read_type}</span>
                  </td>
                  <td className={TD}>{fmtInt(r.contig_count)}</td>
                  <td className={TD} title={`${fmtInt(r.total_length)} bp`}>
                    {fmtBases(r.total_length)}
                  </td>
                  <td className={TD}>{fmtInt(r.n50)} bp</td>
                  <td className={TD}>{fmtInt(r.largest_contig)} bp</td>
                  <td className={TD}>{r.gc_percent === null ? "—" : `${fmtNum(r.gc_percent, 2)}%`}</td>
                  <td className={TD}>{t("assembly.circularValue", { circular: r.circular_contigs, total: r.contigs_with_circularity })}</td>
                  <td className={TD}>{r.median_coverage === null ? "—" : `${fmtNum(r.median_coverage, 0)}×`}</td>
                  <td className="px-2 py-1.5">
                    {r.warning_codes.length ? (
                      <Badge tone="warning" title={r.warning_codes.join(", ")}>
                        {t("projectAssemblies.warningCount", { count: r.warning_codes.length })}
                      </Badge>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={TD}>{fmtDate(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">{t("projectAssemblies.note")}</p>
      </CardBody>
    </Card>
  );
}
