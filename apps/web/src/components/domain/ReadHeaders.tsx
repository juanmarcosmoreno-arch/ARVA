import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Sparkles } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt, technologyLabel } from "@/lib/format";
import { codeKey, distinctRows, documentationLinks, dominantFormat, suggestionState } from "@/lib/headers";
import type { HeaderMetadata, HeaderSummary, MateCheck, RawFile, Sample, SequencingTechnology } from "@/lib/types";
import { cn } from "@/lib/utils";

type T = ReturnType<typeof useT>;

/** Re-fetched whenever the sample's technology or a file's header metadata changes. */
export function useHeaderSummary(sample: Sample | undefined, files: RawFile[] | undefined) {
  const signature = (files ?? []).map((f) => `${f.id}:${f.header_metadata ? 1 : 0}`).join(",");
  return useQuery({
    queryKey: ["headerSummary", sample?.id, sample?.sequencing_technology, signature],
    queryFn: () => api.headerSummary(sample!.id),
    enabled: !!sample && files !== undefined,
  });
}

const platformText = (t: T, platform: string) => (platform === "unknown" ? t("headers.notInferable") : technologyLabel[platform] ?? platform);

function formatText(t: T, fmt: string) {
  const label = (code: string) => {
    const key = codeKey("headers.format", code);
    return key ? t(key) : code;
  };
  return fmt.includes("+") ? t("headers.format.conflict", { formats: fmt.split("+").map(label).join(" + ") }) : label(fmt);
}

/** Chip next to the sample's technology. Changes the sample only when the user clicks "Use this". */
export function TechnologySuggestion({ sample, summary }: { sample: Sample; summary: HeaderSummary | undefined }) {
  const t = useT();
  const qc = useQueryClient();
  const hintId = useId();
  const apply = useMutation({
    mutationFn: (technology: SequencingTechnology) => api.updateSample(sample.id, { sequencing_technology: technology }),
    onSuccess: (s) => {
      qc.setQueryData(["sample", s.id], s);
      qc.invalidateQueries({ queryKey: ["samples"] });
    },
  });
  const suggested = summary?.suggested_technology;
  if (!suggested?.value) return null;
  const value = suggested.value;
  const technology = technologyLabel[value];
  const state = suggestionState(sample.sequencing_technology, value);
  return (
    <>
      <Badge tone="neutral" className="whitespace-normal border border-dashed">
        <Sparkles className="h-3 w-3" aria-hidden />
        {t("headers.suggested", { technology, confidence: t(`headers.confidence.${suggested.confidence}`) })}
      </Badge>
      {state === "offer" && (
        <>
          <Button size="sm" variant="outline" className="h-6 px-2" disabled={apply.isPending} onClick={() => apply.mutate(value)} aria-describedby={hintId}>
            {t("headers.useThis")}
          </Button>
          <span id={hintId} className="text-xs">
            {t("headers.useThisExplain", { technology })}
          </span>
        </>
      )}
      {state === "mismatch" && (
        <span className="text-xs">{t("headers.mismatch", { suggested: technology, user: technologyLabel[sample.sequencing_technology] })}</span>
      )}
      {apply.error && (
        <span role="alert" className="text-xs text-danger">
          {apply.error.message}
        </span>
      )}
    </>
  );
}

export function ReadHeadersCard({ files, summary }: { files: RawFile[]; summary: HeaderSummary | undefined }) {
  const t = useT();
  const sequenceFiles = files.filter((f) => f.file_format !== "unknown");
  if (!sequenceFiles.length) return null;
  const names = new Map(files.map((f) => [f.id, f.original_filename]));
  return (
    <Card>
      <CardHeader title={t("headers.title")} description={t("headers.subtitle")} action={<Explain id="read_headers" />} />
      <CardBody className="space-y-4 pt-3">
        {summary && <SampleSuggestion t={t} summary={summary} />}
        {summary && summary.mate_check.length > 0 && <MateChecks t={t} checks={summary.mate_check} names={names} />}
        <ul className="divide-y rounded-lg border">
          {sequenceFiles.map((f) => (
            <FileHeaders key={f.id} t={t} file={f} />
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function SampleSuggestion({ t, summary }: { t: T; summary: HeaderSummary }) {
  const st = summary.suggested_technology;
  const platforms = st.platforms.map((p) => platformText(t, p)).join(", ");
  let text: string;
  if (st.basis === "no_evidence") text = st.files_considered ? t("headers.noEvidence") : t("headers.noneRead");
  else if (st.basis === "conflicting_platforms") text = t("headers.conflict", { platforms });
  else {
    text = t("headers.basis", { withEvidence: st.files_with_evidence, considered: st.files_considered });
    if (st.platforms.length > 1) text += ` ${t("headers.platforms", { platforms })}`;
  }
  return (
    <div className="space-y-1 text-sm">
      {st.value && (
        <div className="font-medium">
          {t("headers.suggested", { technology: technologyLabel[st.value], confidence: t(`headers.confidence.${st.confidence}`) })}
        </div>
      )}
      <p className="text-xs text-muted-foreground">{text}</p>
    </div>
  );
}

function MateChecks({ t, checks, names }: { t: T; checks: MateCheck[]; names: Map<string, string> }) {
  return (
    <section aria-label={t("headers.mateCheck")} className="space-y-2">
      <h4 className="text-xs font-medium text-muted-foreground">{t("headers.mateCheck")}</h4>
      {checks.map((c) => {
        const warn = c.looks_like_pair === false;
        const text = t(`headers.mate.${c.note}`, {
          r1: names.get(c.r1_file_id) ?? "R1",
          r2: names.get(c.r2_file_id) ?? "R2",
          matched: fmtInt(c.matched),
          compared: fmtInt(c.compared),
        });
        return (
          <div
            key={`${c.r1_file_id}-${c.r2_file_id}`}
            className={cn(
              "flex items-start gap-2 break-words rounded-lg px-3 py-2 text-xs",
              warn ? "border border-warning/40 bg-warning/5" : "bg-muted/60 text-muted-foreground",
            )}
          >
            {warn ? (
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
            ) : (
              <CheckCircle2 className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", c.looks_like_pair ? "text-success" : "text-muted-foreground")} aria-hidden />
            )}
            <span className="min-w-0">{text}</span>
          </div>
        );
      })}
    </section>
  );
}

function FileHeaders({ t, file }: { t: T; file: RawFile }) {
  const meta = file.header_metadata;
  const fmt = dominantFormat(meta);
  const st = meta?.suggested_technology;
  return (
    <li>
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2 text-sm hover:bg-muted/40 [&::-webkit-details-marker]:hidden">
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition group-open:rotate-180" aria-hidden />
          <span className="min-w-0 break-all font-medium">{file.original_filename}</span>
          {!meta ? (
            <Badge tone="neutral">{t("headers.notRead")}</Badge>
          ) : st?.value ? (
            <Badge tone="teal">
              {technologyLabel[st.value]} · {t(`headers.confidence.${st.confidence}`)}
            </Badge>
          ) : (
            <Badge tone="neutral">{t("headers.notInferable")}</Badge>
          )}
          {fmt && <span className="min-w-0 break-words text-xs text-muted-foreground">{formatText(t, fmt)}</span>}
        </summary>
        <div className="space-y-3 px-3 pb-3 text-sm sm:pl-9">
          {meta ? <FileHeaderDetails t={t} meta={meta} /> : <p className="text-xs text-muted-foreground">{t("headers.notReadHint")}</p>}
        </div>
      </details>
    </li>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words">{children}</dd>
    </div>
  );
}

function FileHeaderDetails({ t, meta }: { t: T; meta: HeaderMetadata }) {
  const st = meta.suggested_technology;
  const layoutKey = codeKey("headers.mateLayout", meta.mate_layout);
  const rows = distinctRows(meta);
  const evidence = Object.entries(meta.evidence ?? {}).filter(([, lines]) => lines?.length);
  const warnings = Object.entries(meta.warning_counts ?? {});
  const links = documentationLinks(meta.sources);
  return (
    <>
      <p className="text-xs text-muted-foreground">
        {t("headers.basedOn", { count: fmtInt(meta.n_headers_read) })} {!st?.value && t("headers.fileNoEvidence")}
      </p>
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Detail label={t("headers.platformHint")}>
          {st?.value ? `${technologyLabel[st.value]} (${t(`headers.confidence.${st.confidence}`)})` : t("headers.notInferable")}
          <span className="block text-xs text-muted-foreground">
            {Object.entries(meta.platform_counts ?? {})
              .map(([p, n]) => `${platformText(t, p)}: ${fmtInt(n)}`)
              .join(" · ")}
          </span>
        </Detail>
        <Detail label={t("headers.mateMarkers")}>{layoutKey ? t(layoutKey) : meta.mate_layout}</Detail>
        <Detail label={t("headers.formatsSeen")}>
          <ul>
            {Object.entries(meta.format_counts ?? {}).map(([f, n]) => (
              <li key={f}>
                {formatText(t, f)} × {fmtInt(n)}
              </li>
            ))}
          </ul>
        </Detail>
      </dl>
      <div>
        <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t("headers.values")}</h4>
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("headers.noValues")}</p>
        ) : (
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {rows.map((r) => (
              <Detail key={r.key} label={t(`headers.field.${r.key}`)}>
                <span className="break-all font-mono text-xs">{r.values.join(", ")}</span>
                {(r.n_distinct > r.values.length || r.truncated) && (
                  <span className="block text-[11px] text-muted-foreground">
                    {t("headers.distinct", { count: fmtInt(r.n_distinct) })}
                    {r.truncated && ` · ${t("headers.truncated", { shown: r.values.length })}`}
                  </span>
                )}
              </Detail>
            ))}
          </dl>
        )}
      </div>
      {evidence.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t("headers.evidence")}</h4>
          <ul className="space-y-1 text-[11px]">
            {evidence.map(([f, lines]) => (
              <li key={f} className="break-words">
                <span className="font-medium">{formatText(t, f)}:</span> <span className="font-mono">{lines.join("; ")}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t("headers.warnings")}</h4>
          <p className="break-words font-mono text-[11px]">{warnings.map(([w, n]) => `${w} × ${fmtInt(n)}`).join(" · ")}</p>
        </div>
      )}
      {links.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t("headers.sources")}</h4>
          <ul className="space-y-0.5 text-xs">
            {links.map((l) => (
              <li key={l.text} className="break-all">
                {l.href ? (
                  <a href={l.href} target="_blank" rel="noreferrer noopener" className="inline-flex items-start gap-1 text-arva-royal hover:underline dark:text-arva-cyan">
                    <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    {l.text}
                  </a>
                ) : (
                  l.text
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
