import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, UploadCloud, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api, type UploadProgress } from "@/lib/api";
import { totalBytes, uploadSpace } from "@/lib/capacity";
import { filesFromDrop } from "@/lib/dropFiles";
import { fmtBytes, fmtPct, formatLabel } from "@/lib/format";
import type { StorageCapacity, UploadResult } from "@/lib/types";
import { cn } from "@/lib/utils";
import { fileValidation, rejectionText } from "@/lib/messages";

const ACCEPT = ".fastq,.fq,.fasta,.fa,.fna,.fas,.gz,.pod5";

export function UploadResultList({ result }: { result: UploadResult }) {
  const t = useT();
  return (
    <ul className="space-y-1.5 text-sm" aria-live="polite">
      {result.files.map((f) => (
        <li key={f.id} className="flex items-start gap-2 rounded-lg border bg-surface px-3 py-2">
          {f.is_valid ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          )}
          <div className="min-w-0">
            <div className="truncate font-medium">
              {f.original_filename} <span className="font-normal text-muted-foreground">· {formatLabel(f.file_format)} · {fmtBytes(f.size_bytes)}</span>
            </div>
            <div className="break-words text-xs text-muted-foreground">{fileValidation(t, f)}</div>
          </div>
        </li>
      ))}
      {result.rejected.map((r, i) => (
        <li key={`${r.filename}-${i}`} className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div className="min-w-0">
            <div className="truncate font-medium">{r.filename}</div>
            <div className="break-words text-xs text-muted-foreground">{rejectionText(t, r)}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function FileDropzone({ sampleId, onUploaded }: { sampleId: string; onUploaded?: (r: UploadResult) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [pending, setPending] = useState<File[]>([]);
  const [selection, setSelection] = useState<{ bytes: number; capacity: StorageCapacity | null } | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadFiles(sampleId, files, setProgress),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["files", sampleId] });
      qc.invalidateQueries({ queryKey: ["sample", sampleId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onUploaded?.(r);
    },
    onSettled: () => {
      setProgress(null);
      setPending([]);
      qc.invalidateQueries({ queryKey: ["storage"] });
    },
  });

  const start = async (files: File[]) => {
    if (files.length === 0 || upload.isPending || checking) return;
    setResult(null);
    upload.reset();
    const needed = totalBytes(files);
    setChecking(true);
    // Fresh figures: another upload or import may have used space since the page loaded.
    const capacity = await qc.fetchQuery({ queryKey: ["storage"], queryFn: api.storage, staleTime: 0 }).catch(() => null);
    setChecking(false);
    setSelection({ bytes: needed, capacity });
    const { refusal } = uploadSpace(t, needed, [needed], capacity);
    setRefusal(refusal);
    if (refusal) return;
    setPending(files);
    upload.mutate(files);
  };

  const pct = progress && progress.total ? Math.round((100 * progress.loaded) / progress.total) : 0;
  const busy = upload.isPending || checking;

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={async (e) => {
          e.preventDefault();
          setDragging(false);
          start(await filesFromDrop(e));
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-arva-teal bg-arva-teal/5" : "hover:border-arva-teal/60 hover:bg-muted/50",
          busy && "pointer-events-none opacity-80",
        )}
      >
        <UploadCloud className={cn("mb-3 h-9 w-9", dragging ? "text-arva-teal" : "text-muted-foreground")} />
        <p className="text-sm font-medium">{t("import.drop")}</p>
        <p className="mt-1 max-w-md text-xs text-muted-foreground">{t("import.dropHint")}</p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            start(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      {selection && (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {uploadSpace(t, selection.bytes, [selection.bytes], selection.capacity).line}
        </p>
      )}
      <ErrorNote error={refusal} />

      {upload.isPending && (
        <div className="rounded-lg border bg-surface p-3" aria-live="polite">
          <div className="mb-2 flex justify-between gap-2 text-xs">
            <span>{t("import.uploading", { count: pending.length, size: fmtBytes(totalBytes(pending)) })}</span>
            <span className="tabular-nums">{pct < 100 ? fmtPct(pct, 0) : t("import.checksumming")}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-arva-teal transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      <ErrorNote error={upload.error} />

      {result && <UploadResultList result={result} />}
    </div>
  );
}
