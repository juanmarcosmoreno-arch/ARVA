import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt, fmtMax, fmtNum, fmtPct } from "@/lib/format";
import { codedKey, DEFAULT_MIXED_RATIO, DEFAULT_TRIM_LIMIT, trimRequest, type SangerReadView, type TrimIn } from "@/lib/sanger";
import { Chromatogram } from "./Chromatogram";

/** One read: its chromatogram, the trimming (modified Mott limit or a manual range, both editable here and only
 * previewed: an identification records the trimming it was built with) and the bases to review. */
export function ReadDialog({
  read,
  onClose,
  initialTrim,
  conflicts = [],
  focus,
}: {
  read: SangerReadView;
  onClose: () => void;
  initialTrim?: TrimIn | null;
  conflicts?: number[];
  focus?: number | null;
}) {
  const t = useT();
  const [limit, setLimit] = useState(String(initialTrim?.limit ?? DEFAULT_TRIM_LIMIT));
  const [start, setStart] = useState(initialTrim?.manual_start != null ? String(initialTrim.manual_start) : "");
  const [end, setEnd] = useState(initialTrim?.manual_end != null ? String(initialTrim.manual_end) : "");
  const [ratio, setRatio] = useState(String(DEFAULT_MIXED_RATIO));
  // The base to show, with a counter so that asking again for the same base brings the chromatogram back to it.
  const [target, setTarget] = useState<{ origin: number; n: number } | null>(focus != null ? { origin: focus, n: 0 } : null);
  const limitValue = Number.parseFloat(limit.replace(",", "."));
  const ratioValue = Number.parseFloat(ratio.replace(",", "."));
  const valid = limitValue > 0 && limitValue < 1 && ratioValue > 0 && ratioValue <= 1;
  const trim = trimRequest(valid ? limitValue : DEFAULT_TRIM_LIMIT, start, end);
  const detail = useQuery({
    queryKey: ["sangerRead", read.id, trim, ratioValue],
    queryFn: () => api.sangerRead(read.id, { ...trim, mixed_ratio: valid ? ratioValue : DEFAULT_MIXED_RATIO }),
    placeholderData: keepPreviousData,
  });
  const d = detail.data;
  const review = d?.mixed_peaks.map((m) => m.origin) ?? [];
  const keptReview = d?.mixed_peaks.filter((m) => m.kept) ?? [];
  const instrument = read.summary.instrument ?? {};

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={read.name} description={t("sanger.read.dialogDescription", { file: read.original_filename })} className="max-w-5xl">
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge tone="blue">{t(`sanger.direction.${read.direction}`)}</Badge>
          {read.primer && <Badge>{t("sanger.read.primer", { primer: read.primer })}</Badge>}
          <Badge tone={read.has_trace ? "teal" : "warning"}>{read.has_trace ? t("sanger.read.hasTrace") : t("sanger.read.noTrace")}</Badge>
          {!read.has_qualities && <Badge tone="warning">{t("sanger.read.noQualities")}</Badge>}
          {Object.keys(instrument).length > 0 && (
            <span className="text-muted-foreground">
              {t("sanger.read.instrument", { model: instrument.model ?? "?", basecaller: instrument.basecaller ?? "?", date: instrument.run_date ?? "?", well: instrument.well ?? "?" })}
            </span>
          )}
          <a className={buttonClass("outline", "sm", "ml-auto")} href={api.sangerReadFileUrl(read.id)} download>
            <Download className="h-3.5 w-3.5" aria-hidden /> {t("sanger.read.download")}
          </a>
        </div>

        <fieldset className="grid gap-3 rounded-lg border p-3 sm:grid-cols-4">
          <legend className="flex items-center gap-1 px-1 text-xs font-semibold">
            {t("sanger.trim.title")} <Explain id="sanger_trimming" compact />
          </legend>
          <Field label={t("sanger.trim.limit")} hint={t("sanger.trim.limitHint")}>
            <Input inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} disabled={!read.has_qualities} />
          </Field>
          <Field label={t("sanger.trim.manualStart")} hint={t("sanger.trim.manualHint")}>
            <Input inputMode="numeric" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label={t("sanger.trim.manualEnd")}>
            <Input inputMode="numeric" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <Field label={t("sanger.mixed.ratio")} hint={t("sanger.mixed.ratioHint")}>
            <Input inputMode="decimal" value={ratio} onChange={(e) => setRatio(e.target.value)} disabled={!read.has_trace} />
          </Field>
          {!valid && <p className="text-xs text-danger sm:col-span-4">{t("sanger.trim.invalid")}</p>}
          <p className="text-[11px] text-muted-foreground sm:col-span-4">{t("sanger.read.previewOnly")}</p>
        </fieldset>

        <ErrorNote error={detail.error} />
        {d ? (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-5">
              <Stat label={t("sanger.read.called")} value={fmtInt(d.length)} />
              <Stat label={t("sanger.read.kept")} value={d.trim?.start != null ? t("sanger.read.keptRange", { start: fmtInt(d.trim.start), end: fmtInt(d.trim.end ?? 0) }) : "—"} />
              <Stat label={t("sanger.read.keptLength")} value={fmtInt(d.kept_bases.length)} />
              <Stat label={t("sanger.read.meanQ")} value={d.trim?.mean_quality != null ? fmtNum(d.trim.mean_quality, 1) : "—"} />
              <Stat label={t("sanger.read.q20")} value={d.trim?.q20_percent != null ? fmtPct(d.trim.q20_percent) : "—"} />
            </dl>
            <p className="text-[11px] text-muted-foreground">
              {d.trim?.method === "manual" ? t("sanger.trim.manualUsed") : d.trim?.method === "none" ? t("sanger.trim.noneUsed") : t("sanger.trim.mottUsed", { limit: fmtMax(d.trim?.limit ?? DEFAULT_TRIM_LIMIT, 4) })}{" "}
              {t("sanger.cite", { source: d.trim_source })}
            </p>
            {d.warnings.map((w) => (
              <p key={w.code} className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-warning">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t(...codedKey("sanger.warning", w))}
              </p>
            ))}
            {read.has_trace ? (
              <Chromatogram readId={read.id} name={read.name} length={d.length} trim={d.trim} review={review} conflicts={conflicts} focus={target?.origin ?? null} focusKey={target?.n} />
            ) : (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">{t("sanger.read.noTraceHint")}</p>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-2 font-mono text-[11px]">{d.bases}</pre>
              </div>
            )}
            {read.has_trace && (
              <div className="space-y-1">
                <h4 className="flex items-center gap-1 text-xs font-semibold">
                  {t("sanger.mixed.title", { n: keptReview.length, total: d.mixed_peaks.length })} <Explain id="sanger_mixed_peaks" compact />
                </h4>
                <p className="text-[11px] text-muted-foreground">{t("sanger.cite", { source: d.mixed_source })}</p>
                {keptReview.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t("sanger.mixed.none")}</p>
                ) : (
                  <ul className="flex max-h-28 flex-wrap gap-1 overflow-y-auto">
                    {keptReview.slice(0, 200).map((m) => (
                      <li key={m.origin}>
                        <Button size="sm" variant="outline" className="h-7 px-2 font-mono text-[11px]" onClick={() => setTarget((x) => ({ origin: m.origin, n: (x?.n ?? 0) + 1 }))}>
                          {t("sanger.mixed.item", { position: m.origin, base: m.base, second: m.second_base ?? "?", ratio: m.ratio != null ? fmtNum(m.ratio, 2) : "—" })}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        ) : (
          <Skeleton className="h-72" />
        )}
      </div>
    </Dialog>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}
