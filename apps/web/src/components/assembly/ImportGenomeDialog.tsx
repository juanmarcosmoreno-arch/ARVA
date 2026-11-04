import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileInput, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { referenceCandidates } from "@/lib/quast";
import type { RawFile } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";
/** The characters the API accepts for what the user states (AssemblyImportRequest in apps/api/app/schemas). */
const SOURCE = /^[A-Za-z0-9][A-Za-z0-9 ._:/()+-]*$/;
const stated = (s: string) => SOURCE.test(s.trim()) && s.trim().length <= 100;

/** Registers a genome FASTA of the sample as an imported assembly: a finished genome (e.g. an NCBI RefSeq genome), or a
 * draft the user declares they assembled outside ARVA from this sample's reads (which ARVA then lets them polish). */
export function ImportGenomeDialog({ open, onOpenChange, sampleId, files }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string; files: RawFile[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const fastas = referenceCandidates(files);
  const [fileId, setFileId] = useState("");
  const [source, setSource] = useState("");
  const [draft, setDraft] = useState(false);
  const [assembler, setAssembler] = useState("");
  const [version, setVersion] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!open) return;
    setFileId(fastas[0]?.id ?? "");
    setSource("");
    setDraft(false);
    setAssembler("");
    setVersion("");
    setConfirmed(false);
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const run = useMutation({
    mutationFn: () =>
      api.importAssembly(sampleId, {
        raw_file_id: fileId,
        source: source.trim(),
        ...(draft ? { draft: { from_this_sample_reads: true as const, assembler: assembler.trim(), assembler_version: version.trim() } } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["assemblies", sampleId] });
      onOpenChange(false);
    },
  });
  const sourceOk = stated(source) && (!draft || (stated(assembler) && stated(version)));
  const file = fastas.find((f) => f.id === fileId);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("assembly.imported.dialogTitle")} description={t("assembly.imported.dialogHint")} className="max-w-xl">
      <div className="space-y-4 text-sm">
        {fastas.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("assembly.imported.noFasta")}</p>
        ) : (
          <Field label={t("assembly.imported.file")}>
            <Select value={fileId} onChange={(e) => setFileId(e.target.value)} aria-label={t("assembly.imported.file")}>
              {fastas.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.original_filename} · {fmtBytes(f.size_bytes)}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label={t("assembly.imported.source")} hint={t("assembly.imported.sourceHint")}>
          <Input value={source} maxLength={100} onChange={(e) => setSource(e.target.value)} placeholder="NCBI RefSeq GCF_000013465.1" aria-label={t("assembly.imported.source")} />
        </Field>
        {file && <p className="break-all text-xs text-muted-foreground">{t("assembly.imported.checksum", { sha: file.checksum_sha256 ?? "?" })}</p>}
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            className={CHECK}
            checked={draft}
            onChange={(e) => {
              setDraft(e.target.checked);
              setConfirmed(false);
            }}
          />
          <span>
            <span className="font-medium">{t("assembly.imported.draft")}</span>
            <span className="block text-muted-foreground">{t("assembly.imported.draftHint")}</span>
          </span>
        </label>
        {draft && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("assembly.imported.draftAssembler")} hint={t("assembly.imported.draftAssemblerHint")}>
              <Input value={assembler} maxLength={100} onChange={(e) => setAssembler(e.target.value)} placeholder="Flye" aria-label={t("assembly.imported.draftAssembler")} />
            </Field>
            <Field label={t("assembly.imported.draftVersion")} hint={t("assembly.imported.draftVersionHint")}>
              <Input value={version} maxLength={100} onChange={(e) => setVersion(e.target.value)} placeholder="2.9.6" aria-label={t("assembly.imported.draftVersion")} />
            </Field>
          </div>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t(draft ? "assembly.imported.draftConfirm" : "assembly.imported.confirm")}</span>
        </label>
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!file || !sourceOk || !confirmed || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileInput className="h-4 w-4" />}
            {t("assembly.imported.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
