import { useQuery } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Map as MapIcon, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorNote } from "@/components/ui/misc";
import { dictionaries, type TranslationKey, useT } from "@/i18n";
import { safeExternalUrl } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import type { Annotation, AnnotationFeatureDetail, AnnotationSequenceRecord, ProteinCheck, SequenceCheck } from "@/lib/types";
import { cn } from "@/lib/utils";

type T = ReturnType<typeof useT>;

export const typeLabel = (t: T, type: string) => t(`annotation.type.${type}` as "annotation.type.cds");

const has = (key: string): key is TranslationKey => key in dictionaries.en;

/**
 * One feature as spec §11 lists it: identifier, coordinates, orientation, predicted function, the annotator's
 * nucleotide and protein sequences, the tool, version and database that produced it, its evidence and links for the
 * identifiers it reported. Everything is a prediction; strings from databases are rendered as text only.
 */
export function FeatureDetail({ annotation, featureId, onClose, variant = "inline", children }: {
  annotation: Annotation;
  featureId: number;
  onClose: () => void;
  variant?: "inline" | "panel";
  children?: React.ReactNode;
}) {
  const t = useT();
  const d = useQuery({ queryKey: ["annotationFeature", annotation.id, featureId], queryFn: () => api.annotationFeature(annotation.id, featureId) });
  const f = d.data;
  return (
    <div className={cn("rounded-xl border bg-surface p-4 text-xs", variant === "panel" && "max-h-[calc(100vh-7rem)] overflow-y-auto")} role="region" aria-label={t("annotation.detail")}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <h5 className="break-words text-sm font-semibold">{f ? `${f.locus_tag ?? f.tool_id ?? f.id} · ${f.product ?? typeLabel(t, f.type)}` : t("common.loading")}</h5>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label={t("annotation.close")}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ErrorNote error={d.error} />
      {f && <Body annotation={annotation} f={f} variant={variant} />}
      {children}
    </div>
  );
}

function Body({ annotation, f, variant }: { annotation: Annotation; f: AnnotationFeatureDetail; variant: "inline" | "panel" }) {
  const t = useT();
  const table = (annotation.parameters as { translation_table?: number }).translation_table ?? f.checks.protein.table;
  const orientation = f.strand === "+" ? t("explorer.strand.forward") : f.strand === "-" ? t("explorer.strand.reverse") : t("explorer.strand.none");
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">{t("annotation.predictions")}</p>
      <dl className={cn("grid gap-x-3 gap-y-1", variant === "panel" ? "grid-cols-[110px_1fr]" : "grid-cols-[150px_1fr]")}>
        <dt className="text-muted-foreground">{t("explorer.detail.identifier")}</dt>
        <dd className="break-all font-mono">
          {f.locus_tag ?? "—"}
          {f.tool_id && f.tool_id !== f.locus_tag && <span className="text-muted-foreground"> · {f.tool_id}</span>}
          <span className="text-muted-foreground"> · ARVA #{f.id}</span>
        </dd>
        <dt className="text-muted-foreground">{t("annotation.col.type")}</dt>
        <dd>
          {typeLabel(t, f.type)} <span className="text-muted-foreground">({f.tool_type})</span>
          {f.pseudo && <Badge className="ml-1" tone="warning">{t("annotation.pseudoBadge")}</Badge>}
          {f.partial && <Badge className="ml-1" tone="neutral">{t("annotation.partialBadge", { end: f.partial })}</Badge>}
        </dd>
        <dt className="text-muted-foreground">{t("explorer.detail.coordinates")}</dt>
        <dd className="break-all">
          {f.contig_in_assembly}
          {f.contig !== f.contig_in_assembly ? ` (${f.contig})` : ""}: {fmtInt(f.start)}–{fmtInt(f.end)} · {fmtInt(f.length)} bp
          {f.edge ? ` · ${t("annotation.edge")}` : ""}
        </dd>
        <dt className="text-muted-foreground">{t("explorer.detail.orientation")}</dt>
        <dd>{orientation}</dd>
        <dt className="text-muted-foreground">{t("explorer.detail.function")}</dt>
        <dd className="break-words">
          {f.product ?? "—"}
          {f.gene && <span className="italic"> · {f.gene}</span>}
          {f.hypothetical && <span className="block text-muted-foreground">{t("annotation.hypotheticalNote")}</span>}
        </dd>
        {f.ec.length > 0 && (
          <>
            <dt className="text-muted-foreground">EC</dt>
            <dd>{f.ec.join(", ")}</dd>
          </>
        )}
        {(f.cog.length > 0 || f.cog_categories.length > 0) && (
          <>
            <dt className="text-muted-foreground">COG</dt>
            <dd>{[...f.cog, ...f.cog_categories.map((c) => t("annotation.cogCategory", { c }))].join(", ")}</dd>
          </>
        )}
        {f.go.length > 0 && (
          <>
            <dt className="text-muted-foreground">GO</dt>
            <dd>{f.go.join(", ")}</dd>
          </>
        )}
        <dt className="text-muted-foreground">{t("explorer.detail.annotatedBy")}</dt>
        <dd>
          {annotation.tool} {annotation.tool_version}
          {annotation.database_name ? (
            <span className="block" title={annotation.database_checksum ?? undefined}>
              {annotation.database_name} {annotation.database_version ?? ""}
              {annotation.database_checksum && <span className="font-mono text-muted-foreground"> · {annotation.database_checksum.slice(0, 19)}…</span>}
            </span>
          ) : null}
          <span className="block text-muted-foreground">{t("explorer.detail.table", { table })}</span>
        </dd>
        <dt className="text-muted-foreground">{t("annotation.evidence")}</dt>
        <dd>
          {f.inference.length ? (
            <ul className="list-disc pl-4">
              {f.inference.map((x, i) => (
                <li key={i} className="break-words">
                  {x}
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-muted-foreground">{t("explorer.detail.noEvidence")}</span>
          )}
        </dd>
        {f.db_xrefs.length > 0 && (
          <>
            <dt className="text-muted-foreground">{t("annotation.xrefs")}</dt>
            <dd className="break-all">{f.db_xrefs.join(", ")}</dd>
          </>
        )}
      </dl>
      {f.links.length > 0 && (
        <div>
          <div className="mb-1 text-muted-foreground">{t("annotation.links")}</div>
          <ul className="flex flex-wrap gap-2">
            {f.links.map((l) => {
              const url = safeExternalUrl(l.url);
              return url ? (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 text-arva-royal hover:underline dark:text-arva-cyan">
                    {l.xref} <ExternalLink className="h-3 w-3" aria-hidden />
                  </a>
                </li>
              ) : null;
            })}
          </ul>
          <p className="mt-1 text-[11px] text-muted-foreground">{t("annotation.linksNote")}</p>
        </div>
      )}
      <Checks t={t} nucleotide={f.checks.nucleotide} protein={f.checks.protein} coding={f.type === "cds" || f.type === "sorf"} />
      {f.nucleotide && <SequenceBlock title={t("annotation.nucleotide")} seq={f.nucleotide} unit="bp" />}
      {f.protein && <SequenceBlock title={t("annotation.protein")} seq={f.protein} unit="aa" />}
      {!f.nucleotide && <p className="text-muted-foreground">{t("annotation.noSequence")}</p>}
      {variant === "inline" && (
        <Link
          to={`/explorer/${annotation.id}?${new URLSearchParams({ contig: f.contig, feature: String(f.id) })}`}
          className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan"
        >
          <MapIcon className="h-3.5 w-3.5" aria-hidden /> {t("explorer.showInExplorer")}
        </Link>
      )}
    </div>
  );
}

function Checks({ t, nucleotide, protein, coding }: { t: T; nucleotide: SequenceCheck; protein: ProteinCheck; coding: boolean }) {
  const line = (check: SequenceCheck, what: "nucleotide" | "protein", vars: Record<string, string | number>) => {
    const key = `explorer.check.${what}.${check.status === "not_checked" ? `not_checked.${check.reason}` : check.status}`;
    return has(key) ? t(key, vars) : t(`explorer.check.${what}.not_checked.other` as TranslationKey);
  };
  return (
    <div className="rounded-lg bg-muted/50 p-2">
      <div className="mb-0.5 font-medium">{t("explorer.check.title")}</div>
      <ul className="space-y-0.5">
        <li className={cn(nucleotide.status === "differs" && "text-danger")}>{line(nucleotide, "nucleotide", {})}</li>
        {coding && (
          <li className={cn(protein.status === "differs" && "text-danger")}>
            {line(protein, "protein", { table: protein.table, at: protein.first_difference ?? "?", stops: protein.internal_stops ?? 0 })}
          </li>
        )}
      </ul>
      <p className="mt-1 text-[11px] text-muted-foreground">{t("explorer.check.note")}</p>
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const t = useT();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  };
  return (
    <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={copy} aria-label={label}>
      {state === "copied" ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
      {state === "copied" ? t("explorer.copied") : state === "failed" ? t("explorer.copyFailed") : t("explorer.copy")}
    </Button>
  );
}

function SequenceBlock({ title, seq, unit }: { title: string; seq: AnnotationSequenceRecord; unit: "bp" | "aa" }) {
  const t = useT();
  const fasta = `>${seq.header}\n${seq.sequence.match(/.{1,60}/g)?.join("\n") ?? ""}\n`;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-muted-foreground">
        <span>
          {title} · {fmtInt(seq.length)} {unit} · {t("annotation.from")} {seq.source}
          {seq.truncated && ` · ${t("annotation.truncated")}`}
        </span>
        <span className="ml-auto flex gap-1">
          <CopyButton text={seq.sequence} label={t("explorer.copySequence", { what: title.toLowerCase() })} />
          <CopyButton text={fasta} label={t("explorer.copyFasta", { what: title.toLowerCase() })} />
        </span>
      </div>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2 font-mono text-[11px]">{seq.sequence}</pre>
    </div>
  );
}
