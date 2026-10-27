import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FilePlus, FolderOpen, Loader2, UploadCloud } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { UploadResultList } from "@/components/domain/FileDropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { capacityCheck, totalBytes } from "@/lib/capacity";
import { filesFromDrop } from "@/lib/dropFiles";
import { fmtBytes, technologyLabel } from "@/lib/format";
import { groupFilesBySample, isSequenceFile, type Mate } from "@/lib/sampleNames";
import type { Sample, SequencingTechnology, StorageCapacity, UploadResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".fastq,.fq,.fasta,.fa,.fna,.fas,.gz";
const MAX_IGNORED_LISTED = 8;

interface Row {
  id: number;
  code: string;
  include: boolean;
  technology: SequencingTechnology;
  files: { file: File; mate: Mate }[];
  warnings: string[];
}

type RowStatus =
  | { state: "waiting" }
  | { state: "creating" }
  | { state: "uploading"; pct: number }
  | { state: "done"; sampleId: string; result: UploadResult }
  | { state: "error"; message: string };

function buildRows(files: File[]): Row[] {
  const byName = new Map<string, File[]>();
  for (const f of files) byName.set(f.name, [...(byName.get(f.name) ?? []), f]);
  return groupFilesBySample(files.map((f) => f.name)).map((g, i) => ({
    id: i,
    code: g.sampleName,
    include: true,
    technology: "unknown",
    files: g.files.map((gf) => ({ file: byName.get(gf.name)!.shift()!, mate: gf.mate })),
    warnings: g.warnings,
  }));
}

export function BulkImportDialog({
  open,
  onOpenChange,
  projectId,
  samples,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  projectId: string;
  samples: Sample[];
}) {
  const t = useT();
  const qc = useQueryClient();
  const filesInput = useRef<HTMLInputElement | null>(null);
  const folderInput = useRef<HTMLInputElement | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [ignored, setIgnored] = useState<string[]>([]);
  const [noneFound, setNoneFound] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<Record<number, RowStatus>>({});
  const [phase, setPhase] = useState<"review" | "running" | "finished">("review");
  const [refusal, setRefusal] = useState<string | null>(null);
  // The plan shown while and after running: refetched samples must not turn "new" rows into "existing".
  const [frozen, setFrozen] = useState<Map<string, Sample> | null>(null);
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage, enabled: open });

  const choose = (all: File[]) => {
    const sequence = all.filter((f) => isSequenceFile(f.name));
    setIgnored(all.filter((f) => !isSequenceFile(f.name)).map((f) => f.name));
    setNoneFound(all.length > 0 && sequence.length === 0);
    setRows(buildRows(sequence));
    setStatus({});
    setPhase("review");
    setRefusal(null);
    setFrozen(null);
  };

  useEffect(() => {
    if (open) choose([]);
  }, [open]);

  const existing = useMemo(() => new Map(samples.map((s) => [s.sample_code.trim().toLowerCase(), s])), [samples]);
  const match = (row: Row) => (frozen ?? existing).get(row.code.trim().toLowerCase());
  const update = (id: number, change: Partial<Row>) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...change } : r)));
  const setRowStatus = (id: number, st: RowStatus) => setStatus((s) => ({ ...s, [id]: st }));

  const included = rows.filter((r) => r.include);
  const codes = included.map((r) => r.code.trim().toLowerCase());
  const duplicated = [...new Set(codes.filter((c, i) => c && codes.indexOf(c) !== i))].map(
    (c) => included.find((r) => r.code.trim().toLowerCase() === c)?.code.trim() ?? c,
  );
  const emptyId = included.some((r) => !r.code.trim());
  const selectedBytes = totalBytes(included.flatMap((r) => r.files.map((f) => f.file)));
  const fits = capacityCheck(selectedBytes, storage.data);
  const newCount = included.filter((r) => !match(r)).length;
  const fileCount = included.reduce((n, r) => n + r.files.length, 0);
  const canStart = phase === "review" && included.length > 0 && duplicated.length === 0 && !emptyId && fits !== "insufficient";
  const doneCount = Object.values(status).filter((s) => s.state === "done").length;

  const insufficient = (c: StorageCapacity) =>
    t("storage.insufficient", {
      needed: fmtBytes(selectedBytes),
      available: fmtBytes(c.available_for_data_bytes),
      reserve: fmtBytes(c.min_free_bytes),
    });

  const run = async () => {
    const capacity = await qc.fetchQuery({ queryKey: ["storage"], queryFn: api.storage, staleTime: 0 }).catch(() => null);
    if (capacity && capacityCheck(selectedBytes, capacity) === "insufficient") {
      setRefusal(insufficient(capacity));
      return;
    }
    setRefusal(null);
    setFrozen(existing);
    setPhase("running");
    setStatus(Object.fromEntries(included.map((r) => [r.id, { state: "waiting" } as RowStatus])));
    const touched = new Set<string>();
    for (const row of included) {
      let target = match(row);
      let created = false;
      try {
        if (!target) {
          setRowStatus(row.id, { state: "creating" });
          target = await api.createSample(projectId, { sample_code: row.code.trim(), sequencing_technology: row.technology });
          created = true;
        }
        const sampleId = target.id;
        touched.add(sampleId);
        setRowStatus(row.id, { state: "uploading", pct: 0 });
        const result = await api.uploadFiles(
          sampleId,
          row.files.map((f) => f.file),
          (p) => setRowStatus(row.id, { state: "uploading", pct: p.total ? Math.round((100 * p.loaded) / p.total) : 0 }),
        );
        setRowStatus(row.id, { state: "done", sampleId, result });
      } catch (e) {
        const reason = e instanceof Error ? e.message : String(e);
        setRowStatus(row.id, {
          state: "error",
          message: created && target ? t("bulk.createdButFailed", { sample: target.sample_code, reason }) : reason,
        });
      }
    }
    setPhase("finished");
    const keys = [["samples"], ["projects"], ["project", projectId], ["dashboard"], ["storage"], ...[...touched].flatMap((id) => [["files", id], ["sample", id]])];
    for (const key of keys) qc.invalidateQueries({ queryKey: key });
  };

  const techOptions = Object.entries(technologyLabel).map(([v, l]) => (
    <option key={v} value={v}>
      {l}
    </option>
  ));

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => phase !== "running" && onOpenChange(o)}
      title={t("bulk.title")}
      description={t("bulk.subtitle")}
      className="max-w-3xl"
    >
      {rows.length === 0 ? (
        <div className="space-y-3">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={async (e) => {
              e.preventDefault();
              setDragging(false);
              choose(await filesFromDrop(e));
            }}
            className={cn(
              "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging && "border-arva-teal bg-arva-teal/5",
            )}
          >
            <UploadCloud className={cn("mb-3 h-9 w-9", dragging ? "text-arva-teal" : "text-muted-foreground")} aria-hidden />
            <p className="text-sm font-medium">{t("bulk.drop")}</p>
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              <Button size="sm" variant="outline" onClick={() => filesInput.current?.click()}>
                <FilePlus className="h-4 w-4" /> {t("bulk.chooseFiles")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => folderInput.current?.click()}>
                <FolderOpen className="h-4 w-4" /> {t("bulk.chooseFolder")}
              </Button>
            </div>
            <input
              ref={filesInput}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                choose(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <input
              ref={(el) => {
                folderInput.current = el;
                el?.setAttribute("webkitdirectory", "");
              }}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                choose(Array.from(e.target.files ?? []).filter((f) => !f.name.startsWith(".")));
                e.target.value = "";
              }}
            />
          </div>
          {noneFound && <ErrorNote error={t("bulk.noSequenceFiles")} />}
          <IgnoredNote names={ignored} />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">
              {t("bulk.summary", {
                groups: included.length,
                new: newCount,
                existing: included.length - newCount,
                files: fileCount,
                size: fmtBytes(selectedBytes),
              })}
            </p>
            {phase === "review" && (
              <Button size="sm" variant="ghost" onClick={() => choose([])}>
                {t("bulk.other")}
              </Button>
            )}
          </div>
          <IgnoredNote names={ignored} />

          {phase === "review" && newCount > 0 && (
            <Field label={t("bulk.technologyAll")} className="sm:max-w-xs">
              <Select
                value=""
                onChange={(e) => {
                  const technology = e.target.value as SequencingTechnology;
                  setRows((rs) => rs.map((r) => (match(r) ? r : { ...r, technology })));
                }}
              >
                <option value="">—</option>
                {techOptions}
              </Select>
            </Field>
          )}

          <ul className="max-h-[50vh] space-y-2 overflow-y-auto pr-1">
            {rows.map((row) => {
              const target = match(row);
              const st = status[row.id];
              const locked = phase !== "review";
              return (
                <li key={row.id} className={cn("rounded-lg border p-3", !row.include && "opacity-60")}>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-[#00B4A6]"
                      aria-label={`${t("bulk.include")} ${row.code}`}
                      checked={row.include}
                      disabled={locked}
                      onChange={() => update(row.id, { include: !row.include })}
                    />
                    <Input
                      aria-label={t("bulk.sampleId")}
                      value={row.code}
                      maxLength={255}
                      disabled={locked}
                      aria-invalid={row.include && !row.code.trim()}
                      onChange={(e) => update(row.id, { code: e.target.value })}
                      className="h-9 min-w-[10rem] flex-1"
                    />
                    {target ? <Badge tone="blue">{t("bulk.existing")}</Badge> : <Badge tone="teal">{t("bulk.new")}</Badge>}
                    {!target && (
                      <Select
                        aria-label={t("bulk.technology")}
                        value={row.technology}
                        disabled={locked}
                        onChange={(e) => update(row.id, { technology: e.target.value as SequencingTechnology })}
                        className="h-9 w-full sm:w-44"
                      >
                        {techOptions}
                      </Select>
                    )}
                  </div>
                  <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
                    {row.files.map((f, i) => (
                      <li key={i} className="flex min-w-0 items-center gap-2">
                        <span className="min-w-0 truncate" title={f.file.name}>
                          {f.file.name}
                        </span>
                        {f.mate && <Badge tone="blue">{f.mate}</Badge>}
                        <span className="ml-auto shrink-0 tabular-nums">{fmtBytes(f.file.size)}</span>
                      </li>
                    ))}
                  </ul>
                  {row.warnings.map((w) => (
                    <p key={w} className="mt-1 flex gap-1 break-words text-xs text-amber-700 dark:text-warning">
                      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                      <span className="min-w-0">{w}</span>
                    </p>
                  ))}
                  {st && <RowProgress status={st} />}
                </li>
              );
            })}
          </ul>

          <p className="text-xs text-muted-foreground" aria-live="polite">
            {t("storage.selected", {
              selected: fmtBytes(selectedBytes),
              free: storage.data ? fmtBytes(storage.data.available_for_data_bytes) : "—",
            })}
          </p>
          {duplicated.length > 0 && <ErrorNote error={t("bulk.duplicateIds", { ids: duplicated.join(", ") })} />}
          {emptyId && <ErrorNote error={t("bulk.emptyId")} />}
          {fits === "insufficient" && storage.data && <ErrorNote error={insufficient(storage.data)} />}
          <ErrorNote error={refusal} />
          {phase === "review" && <p className="text-xs text-muted-foreground">{t("bulk.explain")}</p>}

          <div className="flex flex-wrap items-center justify-end gap-2">
            {phase === "finished" ? (
              <>
                <span className="mr-auto text-sm" aria-live="polite">
                  {t("bulk.finished", { ok: doneCount, total: Object.keys(status).length })}
                </span>
                <Button onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
              </>
            ) : (
              <>
                <Button variant="ghost" disabled={phase === "running"} onClick={() => onOpenChange(false)}>
                  {t("common.cancel")}
                </Button>
                <Button disabled={!canStart} onClick={run}>
                  {phase === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                  {t("bulk.start")}
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

function IgnoredNote({ names }: { names: string[] }) {
  const t = useT();
  if (!names.length) return null;
  const listed = names.slice(0, MAX_IGNORED_LISTED).join(", ") + (names.length > MAX_IGNORED_LISTED ? ", …" : "");
  return <p className="break-words text-xs text-muted-foreground">{t("bulk.ignored", { count: names.length, names: listed })}</p>;
}

function RowProgress({ status }: { status: RowStatus }) {
  const t = useT();
  switch (status.state) {
    case "waiting":
      return <p className="mt-2 text-xs text-muted-foreground">{t("bulk.waiting")}</p>;
    case "creating":
      return (
        <p className="mt-2 flex items-center gap-1 text-xs">
          <Loader2 className="h-3 w-3 animate-spin" /> {t("bulk.creating")}
        </p>
      );
    case "uploading":
      return (
        <div className="mt-2" aria-live="polite">
          <div className="mb-1 text-xs tabular-nums">{status.pct < 100 ? t("bulk.uploading", { pct: status.pct }) : t("bulk.validating")}</div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-arva-teal transition-all" style={{ width: `${status.pct}%` }} />
          </div>
        </div>
      );
    case "error":
      return (
        <div className="mt-2">
          <ErrorNote error={`${t("bulk.failed")}: ${status.message}`} />
        </div>
      );
    case "done":
      return (
        <div className="mt-2 space-y-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-1 text-success">
              <CheckCircle2 className="h-3.5 w-3.5" /> {t("bulk.done")}
            </span>
            <Link to={`/samples/${status.sampleId}`} className="text-arva-royal hover:underline dark:text-arva-cyan">
              {t("serverImport.openSample")}
            </Link>
          </div>
          <UploadResultList result={status.result} />
        </div>
      );
  }
}
