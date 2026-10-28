import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { MAX_COMPARED, assemblyLabel, compared } from "@/lib/assembly";
import { fmtBases, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { COVERAGE_LABEL, coverageKind, fmtCoverage } from "@/lib/shortReads";
import type { Assembly, RawFile } from "@/lib/types";
import { CompareCumulativeChart } from "./AssemblyCharts";
import { inputLineage } from "./AssemblyResult";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground";
const TD = "px-2 py-1.5 align-top tabular-nums";

/** ARVA's statistics of the sample's assemblies side by side (same definitions for every assembly), and their
 * cumulative length curves on shared axes. */
export function AssemblyComparison({ assemblies, files }: { assemblies: Assembly[]; files: RawFile[] }) {
  const t = useT();
  const shown = compared(assemblies);
  const rows: { label: TranslationKey; value: (a: Assembly) => string }[] = [
    { label: "assembly.compare.created", value: (a) => fmtDate(a.created_at) },
    { label: "assembly.compare.inputs", value: (a) => inputLineage(a, files) },
    { label: "assembly.stat.contigs", value: (a) => fmtInt(a.stats.contig_count) },
    { label: "assembly.stat.totalLength", value: (a) => `${fmtInt(a.stats.total_length)} bp (${fmtBases(a.stats.total_length)})` },
    { label: "assembly.stat.largest", value: (a) => `${fmtInt(a.stats.largest_contig)} bp` },
    { label: "assembly.stat.n50", value: (a) => `${fmtInt(a.stats.n50)} bp` },
    { label: "assembly.stat.l50", value: (a) => fmtInt(a.stats.l50) },
    { label: "assembly.stat.n90", value: (a) => `${fmtInt(a.stats.n90)} bp` },
    { label: "assembly.stat.l90", value: (a) => fmtInt(a.stats.l90) },
    { label: "assembly.stat.gc", value: (a) => (a.stats.gc_percent === null ? "—" : `${fmtNum(a.stats.gc_percent, 2)}%`) },
    {
      label: "assembly.stat.circular",
      value: (a) => t("assembly.circularValue", { circular: a.stats.circularity.circular_contigs, total: a.stats.circularity.contigs_with_circularity }),
    },
    {
      label: "assembly.stat.medianCoverage",
      value: (a) => {
        const kind = coverageKind(a);
        return `${fmtCoverage(a.stats.coverage.length_weighted_median, kind)}${kind ? ` (${t(COVERAGE_LABEL[kind])})` : ""}`;
      },
    },
    { label: "assembly.compare.warnings", value: (a) => (a.warnings.length ? a.warnings.map((w) => w.code).join(", ") : "—") },
  ];
  return (
    <Card>
      <CardHeader
        title={t("assembly.compare.title", { count: shown.length })}
        description={assemblies.length > MAX_COMPARED ? t("assembly.compare.newest", { max: MAX_COMPARED, total: assemblies.length }) : t("assembly.compare.description")}
      />
      <CardBody className="space-y-4 pt-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className={TH}>{t("assembly.compare.metric")}</th>
                {shown.map((a) => (
                  <th key={a.id} className={`${TH} font-mono`}>
                    {assemblyLabel(a)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.label}>
                  <th scope="row" className="px-2 py-1.5 text-left align-top font-normal">
                    {t(r.label)}
                  </th>
                  {shown.map((a) => (
                    <td key={a.id} className={TD}>
                      {r.value(a)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-muted-foreground">{t("assembly.compare.note")}</p>
        {new Set(shown.map((a) => coverageKind(a))).size > 1 && (
          <p className="text-[11px] text-amber-700 dark:text-warning">{t("assembly.compare.coverageKinds")}</p>
        )}
        <CompareCumulativeChart assemblies={shown} />
      </CardBody>
    </Card>
  );
}
