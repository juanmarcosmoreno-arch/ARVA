import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { technologyLabel } from "@/lib/format";
import { ASSEMBLERS, type Assembler, availableData, defaultAssembler, recommendedAssemblers } from "@/lib/shortReads";
import type { AnalysisJob, AnalysisJobDetail, FlyeRequest, RawFile, SequencingTechnology, SpadesRequest, UnicyclerRequest } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CHECK, FlyePanel, type PanelState, Section } from "./FlyePanel";
import { SpadesPanel, UnicyclerPanel } from "./ShortReadPanels";

const NAME: Record<Assembler, TranslationKey> = {
  flye: "assembly.assembler.flye",
  spades: "assembly.assembler.spades",
  unicycler: "assembly.assembler.unicycler",
};
const HINT: Record<Assembler, TranslationKey> = {
  flye: "assembly.assembler.flyeHint",
  spades: "assembly.assembler.spadesHint",
  unicycler: "assembly.assembler.unicyclerHint",
};
const START: Record<Assembler, (sampleId: string, request: unknown) => Promise<AnalysisJob>> = {
  flye: (id, r) => api.runFlye(id, r as FlyeRequest),
  spades: (id, r) => api.runSpades(id, r as SpadesRequest),
  unicycler: (id, r) => api.runUnicycler(id, r as UnicyclerRequest),
};

/** The "New assembly" dialog: the assembler that fits the sample's reads (or several, one job each, to compare
 * strategies), each assembler's inputs and options explained, a summary of every run, and one explicit
 * confirmation before anything starts. The reads are never changed. */
export function AssemblyDialog({
  open,
  onOpenChange,
  sampleId,
  files,
  jobs = [],
  technology = "unknown",
  onStarted,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  files: RawFile[];
  jobs?: AnalysisJobDetail[];
  technology?: SequencingTechnology;
  onStarted?: () => void;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const data = availableData(files, technology);
  const [several, setSeveral] = useState(false);
  const [chosen, setChosen] = useState<Assembler[]>([]);
  const [states, setStates] = useState<Partial<Record<Assembler, PanelState>>>({});
  const [reviewed, setReviewed] = useState(false);
  const [started, setStarted] = useState(0);
  useEffect(() => {
    if (!open) return;
    setSeveral(false);
    setChosen([defaultAssembler(data)]);
    setReviewed(false);
    setStarted(0);
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const report = useCallback((a: Assembler, s: PanelState) => setStates((cur) => ({ ...cur, [a]: s })), []);
  const requestsKey = JSON.stringify(chosen.map((a) => states[a]?.request ?? null));
  useEffect(() => setReviewed(false), [requestsKey]);

  const choose = (a: Assembler) =>
    setChosen((cur) => (several ? (cur.includes(a) ? cur.filter((x) => x !== a) : ASSEMBLERS.filter((x) => x === a || cur.includes(x))) : [a]));
  const toggleSeveral = (on: boolean) => {
    setSeveral(on);
    if (!on) setChosen((cur) => cur.slice(0, 1));
  };

  const problems = chosen.flatMap((a) =>
    (states[a]?.problems ?? [t("assembly.problem.checking")]).map((p) => (chosen.length > 1 ? `${t(NAME[a])}: ${p}` : p)),
  );
  if (!chosen.length) problems.push(t("assembly.problem.noAssembler"));
  const blocked = problems.length > 0;
  if (!reviewed && !blocked) problems.push(t("flye.problem.reviewed"));
  const run = useMutation({
    mutationFn: async () => {
      setStarted(0);
      for (const a of chosen) {
        await START[a](sampleId, states[a]?.request);
        setStarted((n) => n + 1);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] }),
    onSuccess: () => {
      onOpenChange(false);
      onStarted?.();
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("assembly.dialog.title")} description={t("assembly.dialog.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <AssemblerChoice technology={technology} data={data} chosen={chosen} several={several} onChoose={choose} onSeveral={toggleSeveral} />
        {chosen.map((a, i) => (
          <section key={a} aria-label={t(NAME[a])} className={cn(chosen.length > 1 && "rounded-xl border p-3")}>
            {chosen.length > 1 && (
              <h3 className="mb-3 text-sm font-semibold">
                {i + 1}. {t(NAME[a])}
              </h3>
            )}
            {a === "flye" && <FlyePanel open={open} sampleId={sampleId} files={files} jobs={jobs} report={report} />}
            {a === "spades" && <SpadesPanel open={open} sampleId={sampleId} files={files} jobs={jobs} report={report} />}
            {a === "unicycler" && <UnicyclerPanel open={open} sampleId={sampleId} files={files} jobs={jobs} report={report} />}
          </section>
        ))}
        {!blocked && (
          <label className="flex items-start gap-2 rounded-lg border border-arva-teal/40 bg-arva-teal/5 p-2.5 text-xs">
            <input type="checkbox" className={CHECK} checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            <span>
              <span className="font-medium">{chosen.length > 1 ? t("assembly.several.confirm", { count: chosen.length }) : t("assembly.confirm")}</span>
              <span className="block text-muted-foreground">{t("assembly.confirmHint")}</span>
            </span>
          </label>
        )}
        {problems.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        {run.isError && started > 0 && <p className="text-xs text-amber-700 dark:text-warning">{t("assembly.several.partial", { started, total: chosen.length })}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={problems.length > 0 || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("flye.starting") : chosen.length > 1 ? t("assembly.several.start", { count: chosen.length }) : t("flye.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The assemblers, with the ones that fit the sample's reads marked; one is chosen, or several to compare. */
function AssemblerChoice({
  technology,
  data,
  chosen,
  several,
  onChoose,
  onSeveral,
}: {
  technology: SequencingTechnology;
  data: { short: boolean; long: boolean };
  chosen: Assembler[];
  several: boolean;
  onChoose: (a: Assembler) => void;
  onSeveral: (on: boolean) => void;
}) {
  const t = useT();
  const recommended = recommendedAssemblers(data);
  const tools = { flye: useTool("flye"), spades: useTool("spades"), unicycler: useTool("unicycler") };
  const fit = data.short && data.long ? "both" : data.short ? "short" : data.long ? "long" : "none";
  return (
    <Section title={t("assembly.assembler.title")} hint={t("assembly.assembler.hint")} action={<Explain id="assembly" compact />}>
      <div role={several ? "group" : "radiogroup"} aria-label={t("assembly.assembler.title")} className="grid gap-2 sm:grid-cols-3">
        {ASSEMBLERS.map((a) => {
          const on = chosen.includes(a);
          const tool = tools[a];
          return (
            <label key={a} className={cn("flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-xs", on ? "border-2 border-arva-teal bg-arva-teal/5" : "hover:bg-muted/50")}>
              <input type={several ? "checkbox" : "radio"} name="assembler" className={CHECK} checked={on} onChange={() => onChoose(a)} />
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-1.5 font-medium">
                  {t(NAME[a])}
                  {recommended.includes(a) && <Badge tone="teal">{t("assembly.assembler.fits")}</Badge>}
                  {tool && tool.status !== "available" && <Badge tone="warning">{tool.status === "not_installed" ? t("assembly.assembler.notInstalled") : t("assembly.assembler.unavailable")}</Badge>}
                </span>
                <span className="mt-1 block text-muted-foreground">{t(HINT[a])}</span>
              </span>
            </label>
          );
        })}
      </div>
      <p className={cn("text-xs", fit === "none" ? "text-amber-700 dark:text-warning" : "text-muted-foreground")}>
        {t(`assembly.assembler.fit.${fit}`, { technology: technologyLabel(technology) })}
      </p>
      <label className="flex items-start gap-2 text-xs">
        <input type="checkbox" className={CHECK} checked={several} onChange={(e) => onSeveral(e.target.checked)} />
        <span>
          <span className="font-medium">{t("assembly.several.label")}</span>
          <span className="block text-muted-foreground">{t("assembly.several.hint")}</span>
        </span>
      </label>
    </Section>
  );
}
