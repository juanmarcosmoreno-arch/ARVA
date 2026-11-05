import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileInput, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ProjectGenomeRow } from "@/lib/types";
import { stated } from "./ImportGenomeDialog";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Registers the genome FASTA of every sample of the project as an imported (finished) genome with one stated source:
 * the per-sample "Register a genome FASTA" dialog, for a whole batch. Samples without a FASTA, with several, or whose
 * FASTA is already registered are listed and skipped. A draft to polish is still declared sample by sample. */
export function RegisterGenomesDialog({ open, onOpenChange, projectId }: { open: boolean; onOpenChange: (o: boolean) => void; projectId: string }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [source, setSource] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const plan = useQuery({ queryKey: ["projectGenomes", projectId], queryFn: () => api.projectGenomes(projectId), enabled: open });
  useEffect(() => {
    if (!open) return;
    setSource("");
    setConfirmed(false);
  }, [open]);
  const rows = plan.data ?? [];
  const ready = rows.filter((r) => r.status === "ready");
  const run = useMutation({
    mutationFn: () => api.registerProjectGenomes(projectId, { source: source.trim(), sample_ids: ready.map((r) => r.sample_id) }),
    onSuccess: (res) => {
      for (const s of res.started) {
        queryClient.invalidateQueries({ queryKey: ["jobs", s.sample_id] });
        queryClient.invalidateQueries({ queryKey: ["assemblies", s.sample_id] });
      }
      queryClient.invalidateQueries({ queryKey: ["projectGenomes", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projectAssemblies", projectId] });
    },
  });
  const status = (r: ProjectGenomeRow) =>
    r.status === "ready" ? r.file_name : t(`genomes.status.${r.status}` as "genomes.status.registered", { count: r.fasta_files });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("genomes.title")} description={t("genomes.hint")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        {plan.isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <div className="max-h-72 overflow-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead className="bg-muted text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">{t("genomes.sample")}</th>
                  <th className="px-3 py-2 font-medium">{t("genomes.file")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.sample_id} className="border-t">
                    <td className="px-3 py-1.5">{r.sample_code}</td>
                    <td className={r.status === "ready" ? "px-3 py-1.5 font-mono" : "px-3 py-1.5 text-muted-foreground"}>{status(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted-foreground">{t("genomes.count", { ready: ready.length, total: rows.length })}</p>
        <Field label={t("assembly.imported.source")} hint={t("genomes.sourceHint")}>
          <Input value={source} maxLength={100} onChange={(e) => setSource(e.target.value)} aria-label={t("assembly.imported.source")} />
        </Field>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("genomes.confirm")}</span>
        </label>
        <ErrorNote error={plan.error ?? run.error} />
        {run.data && (
          <p role="status" className="text-xs text-success">
            {t("genomes.started", { count: run.data.started.length })}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {run.data ? t("common.close") : t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!ready.length || !stated(source) || !confirmed || run.isPending || !!run.data}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileInput className="h-4 w-4" />}
            {t("genomes.run", { count: ready.length })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
