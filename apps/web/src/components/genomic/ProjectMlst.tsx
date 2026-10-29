import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { clonalComplexText, warningText } from "@/lib/mlst";
import { STATUS_TONE } from "@/lib/species";
import type { MlstRow, SpeciesRow } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

/** Every sample of the project with its most recent MLST result (or none yet), and the STs found. */
export function ProjectMlst({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["projectMlst", projectId], queryFn: () => api.mlstProject(projectId) });
  const species = useQuery({ queryKey: ["projectSpecies", projectId], queryFn: () => api.speciesProject(projectId) });
  if (overview.error || species.error) return <ErrorNote error={overview.error ?? species.error} />;
  const o = overview.data;
  const latestSpecies = new Map((species.data?.samples ?? []).filter((s) => s.latest).map((s) => [s.sample_id, s.latest as SpeciesRow]));
  if (!o || (!o.samples.some((s) => s.latest) && latestSpecies.size === 0)) return null;
  const typed = o.samples.filter((s) => s.latest).length;
  return (
    <Card className="mt-6 min-w-0" id="project-mlst">
      <CardHeader
        title={t("projectMlst.titleGenomic", { typed, identified: latestSpecies.size, total: o.samples.length })}
        description={t("projectMlst.subtitle")}
        action={
          <div className="flex items-center gap-2">
            <a href={api.mlstProjectCsvUrl(projectId)} className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {t("projectMlst.csv")}
            </a>
            {latestSpecies.size > 0 && (
              <a href={api.speciesProjectCsvUrl(projectId)} className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted">
                <Download className="h-3.5 w-3.5" aria-hidden /> {t("projectMlst.speciesCsv")}
              </a>
            )}
            <Explain id="mlst" compact />
          </div>
        }
      />
      <CardBody className="space-y-3 pt-3">
        {o.sequence_types.length > 0 && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {o.sequence_types.map((x) => (
              <Badge key={`${x.scheme}-${x.st}`} tone={x.st ? "blue" : "warning"}>
                {x.scheme ?? t("mlst.noScheme")} · {x.st ? t("mlst.stBadge", { st: x.st }) : t("mlst.stNotAssigned")} · {t("projectMlst.samples", { n: x.samples })}
              </Badge>
            ))}
          </div>
        )}
        <MlstTable rows={o.samples.map((s) => ({ sampleId: s.sample_id, sampleCode: s.sample_code, row: s.latest, species: latestSpecies.get(s.sample_id) ?? null }))} withSpecies />
      </CardBody>
    </Card>
  );
}

export function MlstTable({
  rows,
  showProject = false,
  withSpecies = false,
}: {
  rows: { sampleId: string; sampleCode: string; row: MlstRow | null; species?: SpeciesRow | null }[];
  showProject?: boolean;
  withSpecies?: boolean;
}) {
  const t = useT();
  const columns: TranslationKey[] = [
    "projectMlst.sample",
    ...(showProject ? (["projectMlst.project"] as TranslationKey[]) : []),
    ...(withSpecies ? (["projectMlst.species"] as TranslationKey[]) : []),
    "mlst.scheme",
    "mlst.st",
    "mlst.status",
    "mlst.clonalComplex",
    "projectMlst.assembly",
    "projectMlst.warnings",
    "projectMlst.date",
  ];
  return (
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
          {rows.map(({ sampleId, sampleCode, row, species }) => (
            <tr key={row?.id ?? sampleId}>
              <td className={TD}>
                <Link to={`/samples/${sampleId}?tab=genomic`} className="text-arva-royal hover:underline dark:text-arva-cyan">
                  {sampleCode}
                </Link>
              </td>
              {showProject && (
                <td className={TD}>
                  {row && (
                    <Link to={`/projects/${row.project_id}`} className="hover:underline">
                      {row.project_name}
                    </Link>
                  )}
                </td>
              )}
              {withSpecies && (
                <td className={TD}>
                  {species ? (
                    <span className="inline-flex items-center gap-1.5" title={t("projectMlst.speciesTitle", { method: species.tool, version: species.tool_version })}>
                      <Badge tone={STATUS_TONE[species.status]}>{t(`species.statusShort.${species.status}` as TranslationKey)}</Badge>
                      {species.species && <span className="italic">{species.species}</span>}
                      {species.consistency.some((c) => c.outcome === "differs") && <Badge tone="warning">{t("projectMlst.disagreement")}</Badge>}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">{t("projectMlst.notIdentified")}</span>
                  )}
                </td>
              )}
              {row ? (
                <>
                  <td className={`${TD} font-mono`}>{row.scheme ?? "—"}</td>
                  <td className={`${TD} font-semibold`}>{row.st ?? t("mlst.stNotAssigned")}</td>
                  <td className={TD}>
                    {row.status} · {row.score}
                  </td>
                  <td className={TD}>{clonalComplexText(t, row.clonal_complex)}</td>
                  <td className={TD}>
                    {row.assembler} {row.assembler_version}
                    {row.assembly_kind === "polished" && <span className="text-muted-foreground"> · {t("annotation.polished")}</span>}
                  </td>
                  <td className="max-w-md px-2 py-1.5" title={row.warnings.map((w) => warningText(t, w)).join("\n")}>
                    {row.warnings.length ? <Badge tone="warning">{t("projectMlst.warningCount", { n: row.warnings.length })}</Badge> : "—"}
                  </td>
                  <td className={TD}>{fmtDate(row.created_at)}</td>
                </>
              ) : (
                <td colSpan={columns.length - 1} className="px-2 py-1.5 text-muted-foreground">
                  {t("projectMlst.notTyped")}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
