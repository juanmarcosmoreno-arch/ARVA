import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, ChevronDown, Download, XCircle } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtBp, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { type QcSortKey, type SortDirection, filterQcRows, missingStatsReason, sortQcRows, technologiesIn } from "@/lib/overview";
import type { QcOverviewRow, SequencingTechnology } from "@/lib/types";
import { cn } from "@/lib/utils";

const LINK_BUTTON =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border bg-surface px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted";
const TD = "whitespace-nowrap px-2 py-2 align-top";
const NUM = cn(TD, "text-right tabular-nums");
const RULES: TranslationKey[] = [
  "qcOverview.rule.files",
  "qcOverview.rule.totals",
  "qcOverview.rule.largest",
  "qcOverview.rule.pooled",
  "qcOverview.rule.depth",
  "qcOverview.rule.filtering",
  "qcOverview.rule.fastqc",
  "qcOverview.rule.seqkit",
];
const COLUMNS: { key: QcSortKey; title: TranslationKey; sub?: TranslationKey; numeric?: boolean }[] = [
  { key: "sample", title: "qcOverview.col.sample" },
  { key: "technology", title: "qcOverview.col.technology" },
  { key: "files", title: "qcOverview.col.files", sub: "qcOverview.col.filesSub", numeric: true },
  { key: "reads", title: "qcOverview.col.reads", sub: "qcOverview.col.importedSub", numeric: true },
  { key: "bases", title: "qcOverview.col.bases", sub: "qcOverview.col.importedSub", numeric: true },
  { key: "n50", title: "qcOverview.col.n50", sub: "qcOverview.col.largestSub", numeric: true },
  { key: "quality", title: "qcOverview.col.quality", sub: "qcOverview.col.largestSub", numeric: true },
  { key: "q30", title: "qcOverview.col.q30", sub: "qcOverview.col.pooledSub", numeric: true },
  { key: "gc", title: "qcOverview.col.gc", sub: "qcOverview.col.pooledSub", numeric: true },
  { key: "depth", title: "qcOverview.col.depth", sub: "qcOverview.col.depthSub", numeric: true },
  { key: "kept", title: "qcOverview.col.filtering", sub: "qcOverview.col.filteringSub" },
  { key: "fastqc", title: "qcOverview.col.fastqc", sub: "qcOverview.col.fastqcSub" },
  { key: "seqkit", title: "qcOverview.col.seqkit" },
];

/** Project page card: one row per sample with the headline QC values, each chosen by a stated rule. */
export function ProjectQcOverview({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["qcOverview", projectId], queryFn: () => api.qcOverview(projectId) });
  const [technology, setTechnology] = useState<SequencingTechnology | "all">("all");
  const [sort, setSort] = useState<{ key: QcSortKey; direction: SortDirection }>({ key: "sample", direction: "asc" });
  const all = overview.data?.rows;
  const rows = useMemo(
    () => (all ? sortQcRows(filterQcRows(all, technology), sort.key, sort.direction) : []),
    [all, technology, sort],
  );
  const technologies = all ? technologiesIn(all) : [];
  const versions = [...new Set((all ?? []).flatMap((r) => r.stats_tool_versions))];
  const toggleSort = (key: QcSortKey) =>
    setSort((s) => ({ key, direction: s.key === key && s.direction === "asc" ? "desc" : "asc" }));

  return (
    <Card className="mt-6 min-w-0" id="project-qc-overview">
      <CardHeader title={t("qcOverview.title")} description={t("qcOverview.subtitle")} action={<Explain id="qc_overview" compact />} />
      <CardBody className="space-y-4">
        <ErrorNote error={overview.error} />
        {overview.isLoading && <Skeleton className="h-24" />}
        {all && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <Field label={t("qcOverview.technology")} className="w-full max-w-xs">
                <Select value={technology} onChange={(e) => setTechnology(e.target.value as SequencingTechnology | "all")}>
                  <option value="all">{t("qcOverview.allTechnologies")}</option>
                  {technologies.map((tech) => (
                    <option key={tech} value={tech}>
                      {t(`technology.${tech}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs text-muted-foreground" aria-live="polite">
                  {t("qcOverview.count", { shown: rows.length, total: all.length })}
                </span>
                <a className={LINK_BUTTON} href={api.qcOverviewCsvUrl(projectId)} download>
                  <Download className="h-4 w-4" aria-hidden /> {t("qcOverview.csv")}
                </a>
              </div>
            </div>
            {!all.some((r) => r.imported_read_files_with_stats > 0) && (
              <p role="status" className="rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground">
                {t("qcOverview.noStats")}
              </p>
            )}
            <div className="relative max-h-[560px] overflow-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="sticky top-0 z-10 bg-surface">
                  <tr className="border-b">
                    {COLUMNS.map((c) => (
                      <SortHeader key={c.key} column={c} sort={sort} onSort={toggleSort} />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <OverviewRow key={r.sample_id} row={r} />
                  ))}
                </tbody>
              </table>
              {rows.length === 0 && <p className="px-3 py-4 text-sm text-muted-foreground">{t("qcOverview.empty")}</p>}
            </div>
            {versions.length > 0 && <p className="text-xs text-muted-foreground">{t("qcOverview.versions", { versions: versions.join(", ") })}</p>}
            <details className="group text-xs">
              <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
                <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" aria-hidden /> {t("qcOverview.rulesTitle")}
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                {RULES.map((k) => (
                  <li key={k}>{t(k)}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function SortHeader({
  column,
  sort,
  onSort,
}: {
  column: (typeof COLUMNS)[number];
  sort: { key: QcSortKey; direction: SortDirection };
  onSort: (key: QcSortKey) => void;
}) {
  const t = useT();
  const active = sort.key === column.key;
  const Icon = active ? (sort.direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  const title = t(column.title);
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
      className={cn("px-2 py-1.5 align-bottom font-medium", column.numeric ? "text-right" : "text-left")}
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className={cn("inline-flex items-start gap-1 rounded hover:text-foreground", column.numeric && "flex-row-reverse text-right", !active && "text-muted-foreground")}
        aria-label={t("qcOverview.sortBy", { column: title })}
      >
        <span>
          <span className="whitespace-nowrap">{title}</span>
          {column.sub && <span className="block whitespace-nowrap font-normal text-muted-foreground">{t(column.sub)}</span>}
        </span>
        <Icon className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
      </button>
    </th>
  );
}

function Missing({ children }: { children?: ReactNode }) {
  return (
    <>
      —{children && <span className="block text-[11px] font-normal text-muted-foreground">{children}</span>}
    </>
  );
}

function OverviewRow({ row }: { row: QcOverviewRow }) {
  const t = useT();
  const reason = missingStatsReason(row);
  const reasonText =
    reason === "incomplete"
      ? t("qcOverview.hint.incomplete", { done: row.imported_read_files_with_stats, total: row.imported_read_files })
      : reason
        ? t(`qcOverview.hint.${reason}`)
        : undefined;
  const largest = row.largest_file ? t("qcOverview.largestFile", { file: row.largest_file.filename }) : undefined;
  const noQuality = reason ? undefined : t("qcOverview.hint.noQuality");
  return (
    <tr className="border-b border-border/50 last:border-0 hover:bg-muted/40">
      <th scope="row" className="px-2 py-2 text-left align-top font-medium">
        <Link to={`/samples/${row.sample_id}?tab=qc`} className="whitespace-nowrap text-arva-royal hover:underline dark:text-arva-cyan">
          {row.sample_code}
        </Link>
      </th>
      <td className={TD}>
        <Badge tone={row.sequencing_technology === "unknown" ? "neutral" : "blue"}>{t(`technology.${row.sequencing_technology}`)}</Badge>
      </td>
      <td className={NUM}>
        {row.imported_files} / {row.derived_files}
      </td>
      <td className={NUM}>{row.total_reads == null ? <Missing>{reasonText}</Missing> : fmtInt(row.total_reads)}</td>
      <td className={NUM} title={row.total_bases == null ? undefined : fmtBp(row.total_bases)}>
        {row.total_bases == null ? <Missing /> : fmtBases(row.total_bases)}
      </td>
      <td className={NUM} title={largest}>
        {row.n50 == null ? <Missing /> : fmtBp(row.n50)}
      </td>
      <td className={NUM} title={largest}>
        {row.mean_read_quality == null ? <Missing>{noQuality}</Missing> : `Q${fmtNum(row.mean_read_quality)}`}
      </td>
      <td className={NUM}>{row.q30_percent == null ? <Missing>{noQuality}</Missing> : fmtPct(row.q30_percent)}</td>
      <td className={NUM}>{row.gc_percent == null ? <Missing /> : fmtPct(row.gc_percent, 2)}</td>
      <td className={NUM}>
        <Depth row={row} />
      </td>
      <td className={TD}>
        <Filtering row={row} />
      </td>
      <td className={TD}>
        <Fastqc row={row} />
      </td>
      <td className={TD}>
        <Seqkit row={row} />
      </td>
    </tr>
  );
}

function Depth({ row }: { row: QcOverviewRow }) {
  const t = useT();
  if (row.estimated_depth != null && row.expected_genome_size_bp != null) {
    return (
      <>
        {fmtNum(row.estimated_depth)}×
        <span className="block text-[11px] text-muted-foreground">{t("qcOverview.depthFor", { size: fmtBases(row.expected_genome_size_bp) })}</span>
      </>
    );
  }
  const status = row.genome_size_status;
  return <Missing>{status === "not_given" || status === "inconsistent" ? t(`qcOverview.hint.${status}`) : undefined}</Missing>;
}

function Filtering({ row }: { row: QcOverviewRow }) {
  const t = useT();
  const f = row.filtering;
  if (!f) return <span className="text-muted-foreground">{t("qcOverview.filteringNone")}</span>;
  const kept = f.bases_kept_percent;
  const detail =
    f.reads_kept_percent != null && kept != null
      ? t("qcOverview.filteringDetail", { reads: fmtNum(f.reads_kept_percent), bases: fmtNum(kept), inputs: f.input_files.join(" + ") })
      : undefined;
  return (
    <div title={detail}>
      <div>
        {f.tool_name} {f.tool_version}
      </div>
      <div className="text-[11px] text-muted-foreground">
        {kept == null ? t("qcOverview.filteringPending") : t("qcOverview.filteringKept", { percent: fmtNum(kept) })}
        {f.runs > 1 && ` · ${t("qcOverview.moreRuns", { count: f.runs })}`}
      </div>
    </div>
  );
}

function Fastqc({ row }: { row: QcOverviewRow }) {
  const t = useT();
  const q = row.fastqc;
  if (q.files_total === 0) return <span className="text-muted-foreground">{t("qcOverview.fastqcNoFastq")}</span>;
  if (q.files === 0) return <span className="text-muted-foreground">{t("qcOverview.fastqcNotRun")}</span>;
  const flags: [number, TranslationKey, typeof CheckCircle2, string][] = [
    [q.pass_count, "qcOverview.fastqcPass", CheckCircle2, "text-success"],
    [q.warn_count, "qcOverview.fastqcWarn", AlertTriangle, "text-warning"],
    [q.fail_count, "qcOverview.fastqcFail", XCircle, "text-danger"],
  ];
  return (
    <div>
      <div className="flex items-center gap-2 tabular-nums">
        {flags.map(([n, label, Icon, tone]) => (
          <span key={label} className="inline-flex items-center gap-0.5">
            <Icon className={cn("h-3.5 w-3.5", tone)} aria-hidden />
            {n}
            <span className="sr-only"> {t(label)}</span>
          </span>
        ))}
      </div>
      <div className="text-[11px] text-muted-foreground">{t("qcOverview.fastqcFiles", { files: q.files, total: q.files_total })}</div>
    </div>
  );
}

function Seqkit({ row }: { row: QcOverviewRow }) {
  const t = useT();
  const s = row.seqkit;
  const label = t(`qcOverview.seqkit.${s.status}`, { checked: s.files_checked, total: s.files_total });
  if (s.status === "not_run") return <span className="text-muted-foreground">{label}</span>;
  const Icon = s.status === "disagree" ? XCircle : CheckCircle2;
  return (
    <div>
      <Badge tone={s.status === "disagree" ? "danger" : s.status === "agree" ? "success" : "neutral"}>
        <Icon className="h-3 w-3" aria-hidden /> {label}
      </Badge>
      {s.differing_metrics.length > 0 && (
        <div className="mt-0.5 whitespace-normal text-[11px] text-danger">{t("qcOverview.seqkitDiffers", { metrics: s.differing_metrics.join(", ") })}</div>
      )}
    </div>
  );
}
