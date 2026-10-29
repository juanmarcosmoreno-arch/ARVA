import { CheckCircle2, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { useT, type TranslationKey } from "@/i18n";
import { recordBadges } from "@/lib/databases";
import { fmtBytes, fmtPct } from "@/lib/format";
import { messageText, serverText } from "@/lib/messages";
import type { Compatibility, DatabaseKind, DetectionProblem, ReferenceDatabase } from "@/lib/types";

type T = ReturnType<typeof useT>;

export function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  if (!/^https?:\/\//.test(href)) return <span className="break-all">{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 break-all text-arva-royal hover:underline dark:text-arva-cyan">
      {children} <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}

export function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 justify-between gap-2 lg:block">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function RecordBadges({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  return (
    <>
      {recordBadges(record).map((b) => (
        <Badge key={b.key} tone={b.tone}>
          {b.key === "ready" && <CheckCircle2 className="h-3 w-3" aria-hidden />}
          {b.key === "unavailable" ? t(`databases.unavailable.${record.unavailable_reason ?? "folder_missing"}` as TranslationKey) : t(`databases.badge.${b.key}` as TranslationKey)}
        </Badge>
      ))}
    </>
  );
}

export function ProgressBar({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  const p = record.progress;
  const done = p?.bytes_done ?? 0;
  const total = p?.bytes_total ?? 0;
  const pct = total ? Math.min(100, Math.floor((done / total) * 100)) : 0;
  const phase = p?.phase ?? "queued";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span>{t(`databases.phase.${phase}` as TranslationKey)}</span>
        <span className="text-muted-foreground">{total ? `${fmtBytes(done)} / ${fmtBytes(total)} (${fmtPct(pct, 0)})` : "—"}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-arva-teal transition-all" style={{ width: `${pct}%` }} />
      </div>
      {record.cancel_requested_at && <p className="text-xs text-muted-foreground">{t("databases.cancelling")}</p>}
    </div>
  );
}

/** A kind's fact in the interface language when this version knows the server's English text exactly. */
export function kindText(t: T, kind: DatabaseKind, field: "name" | "description" | "recognise" | "version_from" | "typical_size" | "download_note" | "licence"): string {
  return serverText(t, `databases.kind.${kind.key}.${field}`, kind[field]);
}

export function kindToolText(t: T, kind: DatabaseKind, i: number): string {
  return serverText(t, `databases.kind.${kind.key}.tool${i}`, kind.tools[i].versions);
}

export function kindUnconfirmed(t: T, kind: DatabaseKind, i: number): string {
  return serverText(t, `databases.kind.${kind.key}.unconfirmed${i}`, kind.unconfirmed[i]);
}

export function compatibilityText(t: T, c: Compatibility | null | undefined): string | null {
  if (!c) return null;
  return t(`databases.compat.${c.code}` as TranslationKey, { tool: "?", version: "?", schema: "?", found: "?", ...c.params });
}

export function CompatibilityBadge({ compatibility }: { compatibility: Compatibility | null | undefined }) {
  const t = useT();
  if (!compatibility) return null;
  const tone = compatibility.status === "compatible" ? "success" : compatibility.status === "incompatible" ? "danger" : "neutral";
  return (
    <Badge tone={tone} title={compatibilityText(t, compatibility) ?? undefined}>
      {t(`databases.compatStatus.${compatibility.status}` as TranslationKey)}
    </Badge>
  );
}

export function problemText(t: T, p: DetectionProblem): string {
  return messageText(t, "databases.problem", { code: p.code, params: p.params, text: p.text });
}
