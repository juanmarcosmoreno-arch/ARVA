import { ArrowRight, Loader2 } from "lucide-react";
import { CompareGcChart, CompareQualityChart, CompareYieldChart } from "@/components/charts/CompareCharts";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { fmtBases, fmtInt, fmtNum } from "@/lib/format";
import { pct } from "@/lib/filters";
import type { AnalysisJobDetail, FastpSummary, RawFile, SequenceStats } from "@/lib/types";
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
                {rows(b, a).map((r) =>
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

const REASONS: Record<string, string> = {
  low_quality_reads: "Low quality",
  too_many_N_reads: "Too many N",
  too_short_reads: "Too short",
  too_long_reads: "Too long",
  low_complexity_reads: "Low complexity",
  duplicated_reads: "Duplicated",
};

function FastpBreakdown({ s }: { s: FastpSummary }) {
  const removed = Object.entries(s.filtering_result).filter(([k]) => k !== "passed_filter_reads");
  return (
    <Card>
      <CardHeader title="fastp report summary" description={`${s.sequencing} · reads counted individually (both mates for paired-end)`} action={<Explain id="fastp" />} />
      <CardBody className="grid gap-3 pt-3 sm:grid-cols-2 lg:grid-cols-4">
        {removed.map(([k, v]) => (
          <div key={k} className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">Removed · {REASONS[k] ?? k.replace(/_/g, " ")}</div>
            <div className="text-lg font-semibold tabular-nums">{fmtInt(v)}</div>
          </div>
        ))}
        <div className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">Reads with adapter trimmed (kept)</div>
          <div className="text-lg font-semibold tabular-nums">{fmtInt(s.adapter_trimmed_reads ?? 0)}</div>
          <div className="text-[11px] text-muted-foreground">{fmtInt(s.adapter_trimmed_bases ?? 0)} bases trimmed</div>
        </div>
        {s.insert_size_peak ? (
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">Insert size peak (from read overlap)</div>
            <div className="text-lg font-semibold tabular-nums">{fmtInt(s.insert_size_peak)} bp</div>
          </div>
        ) : null}
        {s.duplication_rate != null && (
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">Duplication rate (fastp estimate)</div>
            <div className="text-lg font-semibold tabular-nums">{fmtNum(100 * s.duplication_rate, 2)}%</div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
