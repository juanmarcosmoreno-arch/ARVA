import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Download, Sparkles } from "lucide-react";
import { useState } from "react";
import { Segmented } from "@/components/charts/ChartCard";
import { MetricTile } from "@/components/domain/bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { dictionaries, type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { type ContigSortKey, type SortDir, assemblyLabel, lineageNames, sortContigs } from "@/lib/assembly";
import { flyeContigRows } from "@/lib/flye";
import { fmtBases, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { lineage, polishedFrom } from "@/lib/polishing";
import { basename } from "@/lib/results";
import { COVERAGE_LABEL, coverageKind, fmtCoverage } from "@/lib/shortReads";
import type { AnalysisJobDetail, Assembly, AssemblyContig, RawFile } from "@/lib/types";
import { ContigLengthHistogram, ContigScatter, CumulativeChart, NxChart } from "./AssemblyCharts";
import { AssemblyGraphView } from "./AssemblyGraph";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground";
const TD = "px-2 py-1.5 tabular-nums";
const LINK_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted";
const ROWS_SHOWN = 20;

type View = "contigs" | "charts" | "graph";

/** English reasons from arva_core.assembly_stats.assembly_warnings, translated for display. */
const SKIPPED_REASON: Record<string, TranslationKey> = {
  "no expected genome size is known for this sample": "assembly.skipped.noGenomeSize",
  "the assembler reported coverage for fewer than two contigs": "assembly.skipped.coverage",
  "no contig is chromosome-sized": "assembly.skipped.noChromosome",
  "the assembler reported no circularity": "assembly.skipped.noCircularity",
  "fewer than two contigs are long enough": "assembly.skipped.gc",
};

/** The read files an assembly used, each with the files it was derived from ("filtered ← original"). */
export function inputLineage(a: Pick<Assembly, "input_file_ids">, files: RawFile[]): string {
  return a.input_file_ids
    .map((id) => {
      const f = files.find((x) => x.id === id);
      return f ? lineageNames(f, files).join(" ← ") : id;
    })
    .join(", ");
}

/** The card's title: assembler, version and reads, or the polisher and the reads it used. */
function cardTitle(t: ReturnType<typeof useT>, a: Assembly): string {
  if (a.kind === "polished") return t("polishing.cardTitle", { polisher: a.assembler, version: a.assembler_version, reads: a.read_type });
  return t("assembly.result", { assembler: a.assembler, version: a.assembler_version, readType: a.assembler === "Flye" ? `--${a.read_type}` : t("assembly.layout", { mode: t(`assembly.mode.${a.mode}`), layout: a.read_type }) });
}

export function AssemblyCard({
  assembly: a,
  job,
  files,
  assemblies = [],
  onPolish,
}: {
  assembly: Assembly;
  job: AnalysisJobDetail | undefined;
  files: RawFile[];
  assemblies?: Assembly[];
  onPolish?: () => void;
}) {
  const t = useT();
  const chain = lineage(a, assemblies);
  const parent = chain.length > 1 ? chain[chain.length - 2] : undefined;
  const children = polishedFrom(a, assemblies);
  const [view, setView] = useState<View>("contigs");
  const detail = useQuery({ queryKey: ["assembly", a.id], queryFn: () => api.assembly(a.id) });
  const s = a.stats;
  const outputs = (job?.output_paths ?? []).map(basename).filter((n) => n !== "assembly.fasta");
  const genome = s.expected_genome_size;
  const median = s.coverage.length_weighted_median;
  const kind = coverageKind(a);
  const skipped = (s.warning_checks ?? []).filter((c) => !c.evaluated && c.code !== "genome_size_mismatch");
  return (
    <Card>
      <CardHeader
        title={cardTitle(t, a)}
        description={`${fmtDate(a.created_at)} · ${t("assembly.inputs", { files: inputLineage(a, files) })}`}
        action={
          <div className="flex flex-wrap gap-2">
            {onPolish && (
              <button type="button" className={LINK_BUTTON} onClick={onPolish}>
                <Sparkles className="h-3.5 w-3.5" /> {t("polishing.polishThis")}
              </button>
            )}
            <a className={LINK_BUTTON} href={api.assemblyContigsUrl(a.id)}>
              <Download className="h-3.5 w-3.5" /> {t("assembly.download")}
            </a>
            {job &&
              outputs.map((n) => (
                <a key={n} className={LINK_BUTTON} href={api.jobOutputUrl(job.id, n, true)}>
                  <Download className="h-3.5 w-3.5" /> {n}
                </a>
              ))}
          </div>
        }
      />
      <CardBody className="space-y-5 pt-3">
        {(a.kind === "polished" || children.length > 0) && (
          <div className="space-y-0.5 text-xs">
            {a.kind === "polished" && (
              <p>
                <Badge tone="teal">{t("polishing.polishedTag")}</Badge>{" "}
                {parent ? t("polishing.polishedFrom", { label: assemblyLabel(parent) }) : t("polishing.parentGone")}
                {chain.length > 2 && <span className="text-muted-foreground"> · {t("polishing.chain", { chain: chain.map((x) => x.assembler).join(" → ") })}</span>}
              </p>
            )}
            {children.length > 0 && <p className="text-muted-foreground">{t("polishing.polishedVersions", { labels: children.map(assemblyLabel).join(", ") })}</p>}
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <MetricTile label={t("assembly.stat.contigs")} value={fmtInt(s.contig_count)} />
          <MetricTile label={t("assembly.stat.totalLength")} value={fmtBases(s.total_length)} sub={`${fmtInt(s.total_length)} bp`} />
          <MetricTile label={t("assembly.stat.largest")} value={`${fmtInt(s.largest_contig)} bp`} />
          <MetricTile label={t("assembly.stat.n50")} value={`${fmtInt(s.n50)} bp`} explain="assembly_n50" />
          <MetricTile label={t("assembly.stat.l50")} value={fmtInt(s.l50)} sub={t("assembly.stat.lSub", { x: 50 })} />
          <MetricTile label={t("assembly.stat.n90")} value={`${fmtInt(s.n90)} bp`} />
          <MetricTile label={t("assembly.stat.l90")} value={fmtInt(s.l90)} sub={t("assembly.stat.lSub", { x: 90 })} />
          <MetricTile label={t("assembly.stat.gc")} value={s.gc_percent === null ? "—" : `${fmtNum(s.gc_percent, 2)}%`} explain="gc_content" />
          <MetricTile
            label={t("assembly.stat.circular")}
            value={s.circularity.contigs_with_circularity ? t("assembly.circularValue", { circular: s.circularity.circular_contigs, total: s.circularity.contigs_with_circularity }) : "—"}
            sub={
              a.kind === "polished"
                ? t("polishing.circularFromDraft", { assembler: chain[0]?.assembler ?? "?" })
                : s.circularity.contigs_with_circularity
                  ? t("assembly.byAssembler", { assembler: a.assembler })
                  : t("assembly.circularNotReported", { assembler: a.assembler })
            }
            explain="circularity"
          />
          <MetricTile
            label={t("assembly.stat.medianCoverage")}
            value={fmtCoverage(median, kind)}
            sub={kind ? t(COVERAGE_LABEL[kind]) : t("assembly.byAssembler", { assembler: a.assembler })}
            explain={kind === "kmer_coverage" ? "kmer_coverage" : kind === "mapped_read_depth" ? "polishing" : "assembly_coverage"}
          />
        </div>

        <div className="text-xs text-muted-foreground">
          {genome.bp
            ? t("assembly.genomeSize", { size: `${fmtInt(genome.bp)} bp`, source: lookup(t, "assembly.genomeSource.", genome.basis ?? genome.source) })
            : t("assembly.genomeSizeNone")}
        </div>

        <div>
          <div className="mb-1.5 text-xs font-medium">{t("assembly.warningsTitle")}</div>
          {a.warnings.length ? (
            <ul className="space-y-1.5">
              {a.warnings.map((w) => (
                <li key={w.code} className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                  <span>
                    <Badge tone="warning" className="mr-1.5">
                      {t("flye.heuristic")}
                    </Badge>
                    {messageText(t, "assembly.warning", { code: w.code, params: w.params, text: w.message })}
                    {w.contigs.length > 0 && (
                      <span className="block text-muted-foreground">
                        {w.contigs.join(", ")}
                        {w.contigs_total > w.contigs.length ? " …" : ""}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t("assembly.noWarnings")}</p>
          )}
          {skipped.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
              {skipped.map((c) => (
                <li key={c.code}>
                  {t("assembly.skipped.line", {
                    check: lookup(t, "assembly.check.", c.code),
                    reason: c.skipped_reason && SKIPPED_REASON[c.skipped_reason] ? t(SKIPPED_REASON[c.skipped_reason]) : (c.skipped_reason ?? ""),
                  })}
                </li>
              ))}
            </ul>
          )}
        </div>

        <Segmented<View>
          label={t("assembly.view.label")}
          value={view}
          onChange={setView}
          options={[
            { value: "contigs", label: t("assembly.view.contigs") },
            { value: "charts", label: t("assembly.view.charts") },
            ...(s.files.graph ? [{ value: "graph" as const, label: t("assembly.view.graph") }] : []),
          ]}
        />
        {detail.isLoading && view !== "graph" && <Skeleton className="h-40" />}
        <ErrorNote error={detail.error} />
        {view === "contigs" && detail.data && <ContigTable assembly={a} contigs={detail.data.contigs} job={job} />}
        {view === "charts" && detail.data && (
          <div className="grid gap-4 xl:grid-cols-2">
            <ContigLengthHistogram assembly={a} />
            <NxChart assembly={a} />
            <CumulativeChart assembly={a} />
            <ContigScatter assembly={a} contigs={detail.data.contigs} x="length" />
            <ContigScatter assembly={a} contigs={detail.data.contigs} x="gc" />
          </div>
        )}
        {view === "graph" && <AssemblyGraphView assembly={a} />}
      </CardBody>
    </Card>
  );
}

function lookup(t: ReturnType<typeof useT>, prefix: string, value: string | null | undefined) {
  const key = `${prefix}${value}`;
  return key in dictionaries.en ? t(key as TranslationKey) : (value ?? "");
}

const COLUMNS: { key: ContigSortKey; label: TranslationKey }[] = [
  { key: "rank", label: "assembly.col.rank" },
  { key: "name", label: "assembly.col.name" },
  { key: "length", label: "assembly.col.length" },
  { key: "coverage", label: "assembly.col.coverage" },
  { key: "gc_percent", label: "assembly.col.gc" },
  { key: "circular", label: "assembly.col.circular" },
  { key: "repeat", label: "assembly.col.repeat" },
];

/** Contigs with ARVA's and the assembler's columns; click a column header to sort by it. */
export function ContigTable({ assembly: a, contigs, job }: { assembly: Assembly; contigs: AssemblyContig[]; job: AnalysisJobDetail | undefined }) {
  const t = useT();
  const [sort, setSort] = useState<{ key: ContigSortKey; dir: SortDir }>({ key: "rank", dir: "asc" });
  const [all, setAll] = useState(false);
  const flyeRows = flyeContigRows(job);
  const flye = a.assembler === "Flye";
  const kind = coverageKind(a);
  const sorted = sortContigs(contigs, sort.key, sort.dir);
  const shown = all ? sorted : sorted.slice(0, ROWS_SHOWN);
  const s = a.stats;
  const toggle = (key: ContigSortKey) =>
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "name" || key === "rank" ? "asc" : "desc" }));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{t("assembly.contigs")}</span>
        {s.contig_rows.truncated && <span className="text-xs text-muted-foreground">{t("assembly.contigsTruncated", { shown: fmtInt(s.contig_rows.stored), total: fmtInt(s.contig_rows.total) })}</span>}
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} className={TH} aria-sort={sort.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
                  <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => toggle(c.key)}>
                    {c.key === "coverage" && kind ? t(COVERAGE_LABEL[kind]) : t(c.label)}
                    {sort.key === c.key && (sort.dir === "asc" ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />)}
                  </button>
                </th>
              ))}
              {(flye ? (["multiplicity", "altGroup", "graphPath"] as const) : []).map((c) => (
                <th key={c} className={TH}>
                  {t(`assembly.col.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {shown.map((c) => {
              const f = flyeRows.get(c.name);
              return (
                <tr key={c.name}>
                  <td className={TD}>{c.rank}</td>
                  <td className="px-2 py-1.5 font-mono">{c.name}</td>
                  <td className={TD}>{fmtInt(c.length)}</td>
                  <td className={TD}>{fmtCoverage(c.coverage, kind)}</td>
                  <td className={TD}>{c.gc_percent === null ? "—" : fmtNum(c.gc_percent, 2)}</td>
                  <td className="px-2 py-1.5">
                    {c.circular === null ? "—" : c.circular ? <Badge tone="teal">{t("assembly.badge.circular")}</Badge> : <Badge tone="neutral">{t("assembly.badge.linear")}</Badge>}
                  </td>
                  <td className="px-2 py-1.5">{c.repeat === null ? "—" : c.repeat ? <Badge tone="warning">{t("assembly.badge.repeat")}</Badge> : t("assembly.no")}</td>
                  {flye && (
                    <>
                      <td className={TD}>{f ? f.multiplicity : "—"}</td>
                      <td className={TD}>{f?.alt_group ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{f?.graph_path ?? "—"}</td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {contigs.length > shown.length && (
        <Button size="sm" variant="ghost" className="mt-1" onClick={() => setAll(true)}>
          {t("assembly.showAll", { count: fmtInt(contigs.length) })}
        </Button>
      )}
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        {a.kind === "polished"
          ? t("polishing.columnsNote")
          : a.assembler === "SPAdes"
            ? t("assembly.columnsNote.spades")
            : a.assembler === "Unicycler"
              ? t("assembly.columnsNote.unicycler")
              : t("assembly.columnsNote")}
      </p>
    </div>
  );
}
