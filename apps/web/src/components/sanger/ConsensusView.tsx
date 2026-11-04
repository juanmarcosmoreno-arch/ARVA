import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { fmtInt } from "@/lib/format";
import { consensusBlocks, type ConsensusColumn, type ConsensusResult, type Evidence, type SangerReadView, type TrimIn } from "@/lib/sanger";
import { cn } from "@/lib/utils";
import { ReadDialog } from "./ReadDialog";

// A sample of bases in the "single read" style, for the legend.
const SINGLE_SAMPLE = "ACGT";

/** Each status differs by more than colour: bases from one read only are underlined (dotted for the forward read,
 * dashed for the reverse), a resolved conflict is boxed and an unresolved one is bold and boxed. */
const STATUS_CLASS: Record<ConsensusColumn["status"], string> = {
  agree: "",
  forward_only: "text-muted-foreground underline decoration-dotted underline-offset-2",
  reverse_only: "text-muted-foreground underline decoration-dashed underline-offset-2",
  resolved: "bg-amber-200 text-amber-900 outline outline-1 outline-amber-700 dark:bg-amber-500/30 dark:text-amber-100",
  unresolved: "bg-danger/20 font-bold text-danger outline outline-2 outline-danger",
};

/** The consensus (or the trimmed read) in blocks of ten with its conflicts highlighted, and the table of every
 * conflict with each read's base, quality and position in its file, linked to that read's chromatogram. */
export function ConsensusView({ result, reads, trims }: { result: ConsensusResult; reads: { forward: SangerReadView | null; reverse: SangerReadView | null }; trims?: { forward?: TrimIn | null; reverse?: TrimIn | null } }) {
  const t = useT();
  const [open, setOpen] = useState<{ role: "forward" | "reverse"; origin: number } | null>(null);
  const blocks = result.columns.length ? consensusBlocks(result.columns) : [{ start: 1, bases: [...result.sequence].map((b, i) => ({ base: b, status: "agree" as const, column: i + 1 })) }];
  const conflictOrigins = (role: "forward" | "reverse") => result.conflicts.map((c) => c[role]?.origin).filter((x): x is number => x != null);
  const read = open ? reads[open.role] : null;
  return (
    <div className="space-y-3">
      <div>
        <h4 className="mb-1 text-xs font-semibold">{t("sanger.consensus.sequence", { n: fmtInt(result.length) })}</h4>
        <div role="region" tabIndex={0} className="max-h-56 overflow-y-auto rounded-lg border bg-surface p-2 font-mono text-[11px] leading-5" aria-label={t("sanger.consensus.sequenceLabel")}>
          {blocks.map((b) => (
            <span key={b.start} className="mr-2 inline-block whitespace-nowrap">
              <span className="mr-1 select-none text-[9px] text-muted-foreground">{b.start}</span>
              {b.bases.map((x) => (
                <span key={x.column} className={cn(STATUS_CLASS[x.status], "rounded-sm")} title={x.status === "agree" ? undefined : t(`sanger.column.${x.status}` as const)}>
                  {x.base}
                </span>
              ))}
            </span>
          ))}
        </div>
        <p className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          <span>
            <span className={cn(STATUS_CLASS.forward_only, "font-mono")}>{SINGLE_SAMPLE}</span> {t("sanger.column.forward_only")}
          </span>
          <span>
            <span className={cn(STATUS_CLASS.reverse_only, "font-mono")}>{SINGLE_SAMPLE}</span> {t("sanger.column.reverse_only")}
          </span>
          <span>
            <span className={cn(STATUS_CLASS.resolved, "px-1")}>N</span> {t("sanger.column.resolved")}
          </span>
          <span>
            <span className={cn(STATUS_CLASS.unresolved, "px-1")}>N</span> {t("sanger.column.unresolved")}
          </span>
        </p>
      </div>
      {result.status !== "single" && (
        <div>
          <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold">
            {t("sanger.consensus.conflicts", { n: result.conflicts.length })} <Explain id="sanger_conflicts" compact />
          </h4>
          {result.conflict_rule && <p className="mb-1 text-[11px] text-muted-foreground">{t("sanger.cite", { source: result.conflict_rule })}</p>}
          {result.conflicts.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("sanger.consensus.noConflicts")}</p>
          ) : (
            <div className="max-h-72 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-2 py-1 font-medium">{t("sanger.consensus.col.position")}</th>
                    <th className="px-2 py-1 font-medium">{t("sanger.consensus.col.kind")}</th>
                    <th className="px-2 py-1 font-medium">{t("sanger.build.forward")}</th>
                    <th className="px-2 py-1 font-medium">{t("sanger.build.reverse")}</th>
                    <th className="px-2 py-1 font-medium">{t("sanger.consensus.col.result")}</th>
                    <th className="px-2 py-1 font-medium">{t("sanger.consensus.col.rule")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.conflicts.map((c) => (
                    <tr key={c.column} className={cn("border-b last:border-0", c.status === "unresolved" && "bg-danger/5")}>
                      <td className="px-2 py-1 tabular-nums">{c.position != null ? fmtInt(c.position) : t("sanger.consensus.dropped")}</td>
                      <td className="px-2 py-1">{c.kind ? t(`sanger.consensus.kind.${c.kind}` as const) : ""}</td>
                      <EvidenceCell e={c.forward} read={reads.forward} onShow={(origin) => setOpen({ role: "forward", origin })} />
                      <EvidenceCell e={c.reverse} read={reads.reverse} onShow={(origin) => setOpen({ role: "reverse", origin })} />
                      <td className="px-2 py-1 font-mono">
                        {c.base || "—"} <span className="font-sans text-muted-foreground">{t(`sanger.column.${c.status}` as const)}</span>
                      </td>
                      <td className="px-2 py-1">{c.rule ? t(`sanger.rule.${c.rule}` as const) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {open && read && <ReadDialog read={read} onClose={() => setOpen(null)} initialTrim={trims?.[open.role] ?? null} conflicts={conflictOrigins(open.role)} focus={open.origin} />}
    </div>
  );
}

function EvidenceCell({ e, read, onShow }: { e: Evidence | null; read: SangerReadView | null; onShow: (origin: number) => void }) {
  const t = useT();
  if (!e) return <td className="px-2 py-1 text-muted-foreground">{t("sanger.consensus.gap")}</td>;
  return (
    <td className="px-2 py-1">
      <span className="font-mono">{e.base}</span>{" "}
      <span className="text-muted-foreground">{e.quality != null ? t("sanger.consensus.quality", { q: e.quality }) : t("sanger.consensus.noQuality")}</span>{" "}
      {read?.has_trace ? (
        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]" onClick={() => onShow(e.origin)} aria-label={t("sanger.consensus.showLabel", { name: read.name, position: e.origin })}>
          {t("sanger.consensus.show", { position: e.origin })}
        </Button>
      ) : (
        <span className="text-[11px] text-muted-foreground">{t("sanger.consensus.at", { position: e.origin })}</span>
      )}
    </td>
  );
}
