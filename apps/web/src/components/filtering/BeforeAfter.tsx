import { ArrowRight, Loader2 } from "lucide-react";
import { CompareGcChart, CompareQualityChart, CompareYieldChart } from "@/components/charts/CompareCharts";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { fmtBases, fmtInt, fmtNum } from "@/lib/format";
import { pct } from "@/lib/filters";
import type { AnalysisJobDetail, FastpSummary, FiltlongParams, FiltlongSummary, RawFile, SequenceStats } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = { label: string; before: number | null; after: number | null; fmt: (v: number) => string; retained?: boolean };

function rows(b: SequenceStats, a: SequenceStats): Row[] {
  const r: Row[] = [
    { label: "Reads", before: b.read_count, after: a.read_count, fmt: fmtInt, retained: true },
    { label: "Total bases", before: b.total_bases, after: a.total_bases, fmt: fmtBases, retained: true },
    { label: "Mean length (bp)", before: b.mean_length, after: a.mean_length, fmt: (v) => fmtNum(v, 1) },
    { label: "Median length (bp)", before: b.median_length, after: a.median_length, fmt: (v) => fmtNum(v, 1) },
    { label: "N50 (bp)", before: b.n50, after: a.n50, fmt: fmtInt },
    { label: "Min / max length (bp)", before: null, after: null, fmt: fmtInt },
    { label: "GC (%)", before: b.gc_percent, after: a.gc_percent, fmt: (v) => fmtNum(v, 2) },
  ];
  if (b.quality && a.quality) {
    r.push(
      { label: "Mean read quality (Q)", before: b.quality.mean_read_quality, after: a.quality.mean_read_quality, fmt: (v) => fmtNum(v, 2) },
      { label: "Bases ≥ Q20 (%)", before: b.quality.q20_bases_percent, after: a.quality.q20_bases_percent, fmt: (v) => fmtNum(v, 2) },
      { label: "Bases ≥ Q30 (%)", before: b.quality.q30_bases_percent, after: a.quality.q30_bases_percent, fmt: (v) => fmtNum(v, 2) },
    );
  }
  return r;
}

function signed(v: number, fmt: (v: number) => string) {
  if (v === 0) return "0";
  return `${v > 0 ? "+" : "−"}${fmt(Math.abs(v))}`;
}

export function BeforeAfter({
  parent,
  derived,
  parentStats,
  derivedStats,
  filterJob,
  pending,
}: {
  parent: RawFile;
  derived: RawFile;
  parentStats?: SequenceStats;
  derivedStats?: SequenceStats;
  filterJob?: AnalysisJobDetail;
  pending: boolean;
}) {
  const t = useT();
  if (!parentStats || !derivedStats) {
    return (
      <Card className="flex items-center gap-3 p-5 text-sm text-muted-foreground">
        {pending ? <Loader2 className="h-4 w-4 animate-spin text-arva-teal" /> : null}
        {pending
          ? "Computing ARVA statistics for the original and filtered files…"
          : "Statistics are missing for one of the files; run read statistics on both to compare."}
      </Card>
    );
  }
  const b = parentStats;
  const a = derivedStats;
  const prefix = `ARVA_${derived.original_filename}`.replace(/[^A-Za-z0-9._-]+/g, "_");
  const fastp = filterJob?.job_type === "fastp" ? (filterJob.result_summary as unknown as FastpSummary) : null;
  const filtlong = filterJob?.job_type === "filtlong" ? filterJob : null;
  // The genome size entered for a Filtlong coverage target, else the one given for the read statistics; never assumed.
  const genome =
    (filtlong?.parameters as FiltlongRunParams | null)?.genome_size_bp ??
    b.coverage_estimate?.expected_genome_size_bp ??
    a.coverage_estimate?.expected_genome_size_bp ??
    null;
  const table = rows(b, a);
  if (genome) table.splice(2, 0, { label: t("beforeAfter.depth", { genome: fmtInt(genome) }), before: b.total_bases / genome, after: a.total_bases / genome, fmt: (v) => fmtNum(v, 1) });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex flex-wrap items-center gap-2">
              {parent.original_filename} <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" /> {derived.original_filename}
            </span>
          }
          description={`${filterJob ? `${filterJob.tool_name} ${filterJob.tool_version}` : "Filtering"} · both sides computed with ARVA read statistics`}
          action={<Explain id="before_after" />}
        />
        <CardBody className="pt-3">
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Retained label="Reads kept" value={pct(a.read_count, b.read_count)} sub={`${fmtInt(a.read_count)} of ${fmtInt(b.read_count)}`} />
            <Retained label="Bases kept" value={pct(a.total_bases, b.total_bases)} sub={`${fmtBases(a.total_bases)} of ${fmtBases(b.total_bases)}`} />
            <Delta label="Mean length" before={b.mean_length} after={a.mean_length} unit=" bp" digits={0} />
            {b.quality && a.quality ? (
              <Delta label="Mean read quality" before={b.quality.mean_read_quality} after={a.quality.mean_read_quality} prefix="Q" digits={1} />
            ) : (
              <Delta label="N50" before={b.n50} after={a.n50} unit=" bp" digits={0} />
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Metric</th>
                  <th className="py-2 pr-3 text-right font-medium">Before</th>
                  <th className="py-2 pr-3 text-right font-medium">After</th>
                  <th className="py-2 pr-3 text-right font-medium">Change</th>
                </tr>
              </thead>
              <tbody>
                {table.map((r) =>
                  r.label.startsWith("Min / max") ? (
                    <tr key={r.label} className="border-b border-border/50">
                      <td className="py-1.5 pr-3">{r.label}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(b.min_length)} / {fmtInt(b.max_length)}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(a.min_length)} / {fmtInt(a.max_length)}</td>
                      <td />
                    </tr>
                  ) : (
                    <tr key={r.label} className="border-b border-border/50">
                      <td className="py-1.5 pr-3">{r.label}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{r.before != null ? r.fmt(r.before) : "—"}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{r.after != null ? r.fmt(r.after) : "—"}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                        {r.before != null && r.after != null
                          ? r.retained
                            ? `${fmtNum(pct(r.after, r.before), 1)}% kept`
                            : signed(r.after - r.before, r.fmt)
                          : ""}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      {fastp && <FastpBreakdown s={fastp} />}
      {filtlong && <FiltlongBreakdown job={filtlong} after={a} genome={genome} />}

      <div className="grid gap-6 lg:grid-cols-2">
        <CompareYieldChart before={b} after={a} prefix={prefix} />
        {b.quality && a.quality && <CompareQualityChart before={b} after={a} prefix={prefix} />}
        <CompareGcChart before={b} after={a} prefix={prefix} />
      </div>
    </div>
  );
}

function Retained({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="rounded-xl bg-muted/60 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{fmtNum(value, 1)}%</div>
      <div className="text-[11px] text-muted-foreground">{sub}</div>
    </div>
  );
}

function Delta({ label, before, after, unit = "", prefix = "", digits }: { label: string; before: number; after: number; unit?: string; prefix?: string; digits: number }) {
  const d = after - before;
  return (
    <div className="rounded-xl bg-muted/60 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums">
        {prefix}
        {fmtNum(after, digits)}
        {unit}
      </div>
      <div className={cn("text-[11px] tabular-nums", d === 0 ? "text-muted-foreground" : "text-foreground/80")}>
        from {prefix}
        {fmtNum(before, digits)}
        {unit} ({d >= 0 ? "+" : "−"}
        {fmtNum(Math.abs(d), digits)})
      </div>
    </div>
  );
}

const REASONS = new Set(["low_quality_reads", "too_many_N_reads", "too_short_reads", "too_long_reads", "low_complexity_reads", "duplicated_reads"]);

function FastpBreakdown({ s }: { s: FastpSummary }) {
  const t = useT();
  const removed = Object.entries(s.filtering_result).filter(([k]) => k !== "passed_filter_reads");
  return (
    <Card>
      <CardHeader title={t("fastpSummary.title")} description={t("fastpSummary.subtitle", { sequencing: s.sequencing })} action={<Explain id="fastp" />} />
      <CardBody className="grid gap-3 pt-3 sm:grid-cols-2 lg:grid-cols-4">
        {removed.map(([k, v]) => (
          <div key={k} className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">
              {t("fastpSummary.removed", { reason: REASONS.has(k) ? t(`fastpSummary.reason.${k}` as TranslationKey) : k.replace(/_/g, " ") })}
            </div>
            <div className="text-lg font-semibold tabular-nums">{fmtInt(v)}</div>
          </div>
        ))}
        <div className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">{t("fastpSummary.adapterTrimmed")}</div>
          <div className="text-lg font-semibold tabular-nums">{s.adapter_trimmed_reads == null ? "—" : fmtInt(s.adapter_trimmed_reads)}</div>
          <div className="text-[11px] text-muted-foreground">
            {s.adapter_trimmed_reads == null ? t("fastpSummary.noAdapter") : t("fastpSummary.basesTrimmed", { bases: fmtInt(s.adapter_trimmed_bases ?? 0) })}
          </div>
        </div>
        {s.insert_size_peak ? (
          <div className="rounded-lg border p-3">
            <div className="flex items-start justify-between gap-1 text-xs text-muted-foreground">
              {t("fastpSummary.insertPeak")} <Explain id="insert_size" compact />
            </div>
            <div className="text-lg font-semibold tabular-nums">{fmtInt(s.insert_size_peak)} bp</div>
            {s.insert_size && s.insert_size.evaluated_pairs > 0 && (
              <div className="text-[11px] text-muted-foreground">
                {t("fastpSummary.insertOverlap", {
                  overlap: fmtNum((100 * s.insert_size.overlapping_pairs) / s.insert_size.evaluated_pairs, 1),
                  evaluated: fmtInt(s.insert_size.evaluated_pairs),
                })}
              </div>
            )}
            <div className="text-[11px] text-muted-foreground">{t("fastpSummary.insertNote")}</div>
          </div>
        ) : null}
        {s.duplication_rate != null && (
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{t("qcdata.fastp.dupRate")}</div>
            <div className="text-lg font-semibold tabular-nums">{fmtNum(100 * s.duplication_rate, 2)}%</div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

type FiltlongRunParams = Partial<FiltlongParams> & { genome_size_bp?: number | null; target_coverage_x?: number | null };

function FiltlongBreakdown({ job, after, genome }: { job: AnalysisJobDetail; after: SequenceStats; genome: number | null }) {
  const t = useT();
  const s = (job.result_summary ?? {}) as FiltlongSummary;
  const p = (job.parameters ?? {}) as FiltlongRunParams;
  if (s.target_bases_reported == null) return null;
  const noRemoval = s.not_enough_reads_for_target ? "filtlongSummary.notEnough" : s.below_target_after_filtering ? "filtlongSummary.below" : null;
  const hard = [p.min_length, p.max_length, p.min_mean_q, p.min_window_q].some((v) => v != null);
  const targetDepth = p.target_coverage_x ?? (genome ? s.target_bases_reported / genome : null);
  return (
    <Card>
      <CardHeader title={t("filtlongSummary.title")} description={t("filtlongSummary.subtitle")} action={<Explain id="filtlong" />} />
      <CardBody className="space-y-3 pt-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{t("filtlongSummary.target")}</div>
            <div className="text-lg font-semibold tabular-nums">{fmtInt(s.target_bases_reported)}</div>
            {p.genome_size_bp != null && p.target_coverage_x != null && (
              <div className="text-[11px] text-muted-foreground">
                {t("filtlongSummary.coverage", { depth: fmtNum(p.target_coverage_x, 1), genome: fmtInt(p.genome_size_bp) })}
              </div>
            )}
          </div>
          {s.kept_bases_reported != null && (
            <div className="rounded-lg border p-3">
              <div className="text-xs text-muted-foreground">{t("filtlongSummary.kept")}</div>
              <div className="text-lg font-semibold tabular-nums">{fmtInt(s.kept_bases_reported)}</div>
              <div className="text-[11px] text-muted-foreground">{t("filtlongSummary.overshoot")}</div>
            </div>
          )}
          {genome != null && targetDepth != null && (
            <div className="rounded-lg border p-3">
              <div className="text-xs text-muted-foreground">{t("filtlongSummary.depth")}</div>
              <div className="text-lg font-semibold tabular-nums">{fmtNum(after.total_bases / genome, 1)}×</div>
              <div className="text-[11px] text-muted-foreground">
                {t("filtlongSummary.depthSub", { target: `${fmtNum(targetDepth, 1)}×`, genome: fmtInt(genome) })}
              </div>
            </div>
          )}
        </div>
        {noRemoval && (
          <p className="text-sm">
            {t(noRemoval)} {hard && t("filtlongSummary.hardStill")}
          </p>
        )}
      </CardBody>
    </Card>
  );
}
