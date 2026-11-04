import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, Trash2, UploadCloud, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { filesFromDrop } from "@/lib/dropFiles";
import { fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { SANGER_ACCEPT, type Direction, type ImportResult, type SangerOverview, type SangerReadView } from "@/lib/sanger";
import { cn } from "@/lib/utils";
import { ReadDialog } from "./ReadDialog";

/** The sample's Sanger reads: drop .ab1 files (or FASTA/.seq text), see each read's direction and pair as ARVA
 * proposed them from the file names (changeable), its default trimming and quality, and open its chromatogram. */
export function SangerReads({ sampleId, overview }: { sampleId: string; overview: SangerOverview }) {
  const t = useT();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [open, setOpen] = useState<SangerReadView | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["sanger", sampleId] });
  const upload = useMutation({
    mutationFn: (files: File[]) => api.importSangerReads(sampleId, files),
    onSuccess: (r) => {
      setResult(r);
      refresh();
    },
  });
  const send = (files: File[]) => files.length && upload.mutate(files);

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1">
            {t("sanger.reads.title")} <Explain id="sanger_reads" compact />
          </span>
        }
        description={t("sanger.reads.subtitle")}
      />
      <CardBody className="space-y-4">
        <div
          role="button"
          tabIndex={0}
          aria-label={t("sanger.reads.dropLabel")}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              input.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={async (e) => {
            e.preventDefault();
            setDragging(false);
            send(await filesFromDrop(e));
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center text-sm transition-colors focus-visible:ring-2",
            dragging ? "border-arva-teal bg-arva-teal/5" : "hover:bg-muted/40",
          )}
        >
          <UploadCloud className="h-6 w-6 text-muted-foreground" aria-hidden />
          <span className="font-medium">{upload.isPending ? t("sanger.reads.uploading") : t("sanger.reads.drop")}</span>
          <span className="text-xs text-muted-foreground">{t("sanger.reads.dropHint")}</span>
          <input
            ref={input}
            type="file"
            multiple
            accept={SANGER_ACCEPT}
            className="hidden"
            onChange={(e) => {
              send(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </div>
        <ErrorNote error={upload.error} />
        {result && <ImportList result={result} />}

        {overview.reads.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("sanger.reads.none")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-2 py-1.5 font-medium">{t("sanger.reads.col.name")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.reads.col.direction")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.reads.col.pair")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.reads.col.primer")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.reads.col.called")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.reads.col.kept")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.reads.col.q20")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.reads.col.data")}</th>
                  <th className="px-2 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {overview.reads.map((r) => (
                  <ReadRow key={r.id} read={r} onOpen={() => setOpen(r)} onChanged={refresh} />
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-muted-foreground">{t("sanger.reads.pairingNote")}</p>
          </div>
        )}
      </CardBody>
      {open && <ReadDialog read={open} onClose={() => setOpen(null)} />}
    </Card>
  );
}

function ImportList({ result }: { result: ImportResult }) {
  const t = useT();
  return (
    <ul className="space-y-1 text-xs" aria-live="polite">
      {result.imported.length > 0 && (
        <li className="flex items-center gap-2 rounded-lg border bg-surface px-3 py-2">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
          {t("sanger.reads.imported", { n: result.imported.length, names: result.imported.map((r) => r.name).join(", ") })}
        </li>
      )}
      {result.skipped.map((s, i) => (
        <li key={`${s.file}-${i}`} className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          <span>{messageText(t, "api.error", { code: s.code, params: s.params, text: s.detail })}</span>
        </li>
      ))}
    </ul>
  );
}

function ReadRow({ read, onOpen, onChanged }: { read: SangerReadView; onOpen: () => void; onChanged: () => void }) {
  const t = useT();
  const [pair, setPair] = useState(read.pair_key ?? "");
  const update = useMutation({ mutationFn: (body: { direction?: Direction; pair_key?: string }) => api.updateSangerRead(read.id, body), onSuccess: onChanged });
  const remove = useMutation({ mutationFn: () => api.deleteSangerRead(read.id), onSuccess: onChanged });
  const trim = read.summary.default_trim;
  return (
    <tr className="border-b align-top last:border-0">
      <td className="px-2 py-1.5">
        <div className="font-medium">{read.name}</div>
        <div className="text-[11px] text-muted-foreground">{read.original_filename}</div>
        <ErrorNote error={update.error ?? remove.error} />
      </td>
      <td className="px-2 py-1.5">
        <Select
          className="h-8 w-32 text-xs"
          aria-label={t("sanger.reads.directionOf", { name: read.name })}
          value={read.direction}
          onChange={(e) => update.mutate({ direction: e.target.value as Direction })}
        >
          {(["forward", "reverse", "unknown"] as const).map((d) => (
            <option key={d} value={d}>
              {t(`sanger.direction.${d}` as const)}
            </option>
          ))}
        </Select>
        <div className="mt-0.5 text-[10px] text-muted-foreground">{t(`sanger.directionSource.${read.direction_source}` as const)}</div>
      </td>
      <td className="px-2 py-1.5">
        <Input
          className="h-8 w-28 text-xs"
          aria-label={t("sanger.reads.pairOf", { name: read.name })}
          value={pair}
          onChange={(e) => setPair(e.target.value)}
          onBlur={() => pair !== (read.pair_key ?? "") && update.mutate({ pair_key: pair })}
        />
      </td>
      <td className="px-2 py-1.5">{read.primer ?? "—"}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">{fmtInt(read.length)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">
        {trim?.start != null ? (
          <>
            {fmtInt(trim.length)}
            <div className="text-[10px] text-muted-foreground">{t("sanger.read.keptRange", { start: fmtInt(trim.start), end: fmtInt(trim.end ?? 0) })}</div>
          </>
        ) : trim ? (
          <Badge tone="danger">{t("sanger.reads.nothingKept")}</Badge>
        ) : (
          "—"
        )}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">
        {trim?.q20_percent != null ? fmtPct(trim.q20_percent) : "—"}
        {trim?.mean_quality != null && <div className="text-[10px] text-muted-foreground">{t("sanger.reads.meanQ", { q: fmtNum(trim.mean_quality, 1) })}</div>}
      </td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap gap-1">
          {read.has_trace ? <Badge tone="teal">{t("sanger.read.hasTrace")}</Badge> : <Badge tone="warning">{t("sanger.read.noTrace")}</Badge>}
          {!read.has_qualities && <Badge tone="warning">{t("sanger.read.noQualities")}</Badge>}
          {read.chromatogram_twin && <Badge tone="warning">{t("sanger.reads.twin")}</Badge>}
        </div>
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-right">
        <Button size="sm" variant="outline" onClick={onOpen} aria-label={t("sanger.reads.open", { name: read.name })}>
          <Eye className="h-3.5 w-3.5" aria-hidden /> {t("sanger.reads.view")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="ml-1"
          disabled={read.used_by > 0 || remove.isPending}
          title={read.used_by > 0 ? t("sanger.reads.inUse", { n: read.used_by }) : undefined}
          aria-label={t("sanger.reads.delete", { name: read.name })}
          onClick={() => window.confirm(t("sanger.reads.confirmDelete", { name: read.name })) && remove.mutate()}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </td>
    </tr>
  );
}
