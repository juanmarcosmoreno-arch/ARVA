import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, Pencil, Trash2, Undo2, Upload } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton, Tabs } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, technologyLabel } from "@/lib/format";
import {
  DELIMITERS,
  METADATA_FIELDS,
  applyCustomEdits,
  applyPlan,
  currentMapping,
  customDraft,
  customEditsChange,
  customEntries,
  delimiterName,
  duplicateTargets,
  filterRows,
  shortSha,
  showDateOrder,
  summariseMapping,
  type CustomEdit,
  type RowFilter,
} from "@/lib/metadataImport";
import type {
  DateOrder,
  MetadataAction,
  MetadataApplyResult,
  MetadataChange,
  MetadataImportMode,
  MetadataImportRecord,
  MetadataPreview,
  MetadataRowPreview,
  MetadataTableOptions,
  MetadataTarget,
  Sample,
} from "@/lib/types";
import { messageText, type ServerMessage } from "@/lib/messages";
import { cn } from "@/lib/utils";

type T = ReturnType<typeof useT>;

const ACCEPT = ".csv,.tsv,.txt,.xlsx";
const PAGE = 50;
const ACTIONS: MetadataAction[] = ["create", "update", "unchanged", "error"];
const ACTION_TONE: Record<MetadataAction, "teal" | "blue" | "neutral" | "danger"> = {
  create: "teal",
  update: "blue",
  unchanged: "neutral",
  error: "danger",
};

function targetLabel(t: T, target: MetadataTarget) {
  if (target === "custom") return t("metadata.target.custom");
  if (target === "ignore") return t("metadata.target.ignore");
  return t(`metadata.field.${target}`);
}

function delimiterLabel(t: T, value: string | null) {
  const name = delimiterName(value);
  return name ? t(`metadata.delimiter.${name}`) : value ?? "";
}

const changeLabel = (t: T, c: MetadataChange) =>
  c.field === "custom_metadata" ? t("metadata.customField", { key: c.key ?? "" }) : t(`metadata.field.${c.field}`);

const changeValue = (c: MetadataChange, value: string | null) =>
  c.field === "sequencing_technology" && value ? technologyLabel[value] ?? value : value;

/** Import dialog: choose a table, review the server's row-by-row preview, then apply it in one transaction. */
export function MetadataImportDialog({ open, onOpenChange, projectId }: { open: boolean; onOpenChange: (o: boolean) => void; projectId: string }) {
  const t = useT();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement | null>(null);
  const latest = useRef(0);
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<MetadataTableOptions>({});
  const [preview, setPreview] = useState<MetadataPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, MetadataTarget>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [headerInput, setHeaderInput] = useState("");
  const [filter, setFilter] = useState<RowFilter>("all");
  const [shown, setShown] = useState(PAGE);
  const [mode, setMode] = useState<MetadataImportMode>("create_and_update");
  const [confirmed, setConfirmed] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<unknown>(null);
  const [result, setResult] = useState<MetadataApplyResult | null>(null);

  const reset = () => {
    latest.current++;
    setFile(null);
    setOptions({});
    setPreview(null);
    setChoices({});
    setBusy(false);
    setError(null);
    setFilter("all");
    setShown(PAGE);
    setMode("create_and_update");
    setConfirmed(false);
    setApplyError(null);
    setResult(null);
  };

  useEffect(() => {
    if (open) reset();
  }, [open]);

  /** Only the newest request may update the dialog: choices can change faster than the server answers. */
  const run = async (f: File, next: MetadataTableOptions) => {
    const id = ++latest.current;
    setOptions(next);
    setBusy(true);
    setError(null);
    setApplyError(null);
    setConfirmed(false);
    try {
      const p = await api.previewMetadata(projectId, f, next);
      if (id !== latest.current) return;
      setPreview(p);
      setHeaderInput(String(p.file.header_row));
      setShown(PAGE);
    } catch (e) {
      if (id === latest.current) setError(e);
    } finally {
      if (id === latest.current) setBusy(false);
    }
  };

  const choose = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    setPreview(null);
    setChoices({});
    setFilter("all");
    void run(f, {});
  };

  // Columns depend on the sheet, header row and delimiter, so a change there starts the mapping afresh.
  const reread = (change: MetadataTableOptions) => {
    if (!file) return;
    setChoices({});
    void run(file, { ...options, mapping: null, ...change });
  };

  const mapping = preview ? currentMapping(preview.columns, choices) : {};
  const duplicates = duplicateTargets(mapping);

  const setTarget = (header: string, target: MetadataTarget) => {
    if (!file || !preview) return;
    const next = { ...mapping, [header]: target };
    setChoices(next);
    if (duplicateTargets(next).length === 0) void run(file, { ...options, mapping: next });
  };

  const commitHeaderRow = () => {
    const n = Number(headerInput);
    if (preview && Number.isInteger(n) && n >= 1 && n !== preview.file.header_row) reread({ headerRow: n });
  };

  const plan = preview ? applyPlan(preview.counts, mode) : null;
  const upToDate = !!preview && !busy && !error && duplicates.length === 0;
  const canApply = upToDate && confirmed && !applying && !!plan && plan.create + plan.update > 0;

  const apply = async () => {
    if (!file || !preview) return;
    setApplying(true);
    setApplyError(null);
    try {
      const sent: MetadataTableOptions = {
        sheet: preview.file.sheet,
        headerRow: preview.file.header_row,
        delimiter: preview.file.delimiter,
        dateOrder: options.dateOrder ?? null,
        mapping,
      };
      const r = await api.applyMetadata(projectId, file, sent, preview.file.sha256, mode);
      setResult(r);
      for (const key of [["samples"], ["sample"], ["project", projectId], ["projects"], ["dashboard"], ["metadataImports", projectId]]) {
        qc.invalidateQueries({ queryKey: key });
      }
    } catch (e) {
      setApplyError(e);
    } finally {
      setApplying(false);
    }
  };

  const rows = preview ? filterRows(preview.rows, filter) : [];

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !applying && onOpenChange(o)}
      title={t("metadata.dialogTitle")}
      description={t("metadata.dialogSubtitle")}
      className="max-w-3xl"
    >
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        aria-label={t("metadata.choose")}
        onChange={(e) => {
          choose(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {result ? (
        <ApplyResult result={result} onClose={() => onOpenChange(false)} />
      ) : !file ? (
        <div className="space-y-3">
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center">
            <FileSpreadsheet className="mb-3 h-9 w-9 text-muted-foreground" aria-hidden />
            <Button variant="outline" onClick={() => input.current?.click()}>
              <Upload className="h-4 w-4" /> {t("metadata.choose")}
            </Button>
            <p className="mt-3 max-w-md text-xs text-muted-foreground">{t("metadata.accepted")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t("metadata.template")}:</span>
            <DownloadLink href={api.metadataTemplateUrl("csv")} label={`${t("metadata.template")} ${t("metadata.exportCsv")}`}>
              {t("metadata.exportCsv")}
            </DownloadLink>
            <DownloadLink href={api.metadataTemplateUrl("xlsx")} label={`${t("metadata.template")} ${t("metadata.exportXlsx")}`}>
              {t("metadata.exportXlsx")}
            </DownloadLink>
            <Explain id="metadata_import" className="ml-auto" />
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 break-all text-sm font-medium">{file.name}</span>
            {preview && (
              <span className="font-mono text-xs text-muted-foreground" title={preview.file.sha256}>
                SHA-256 {shortSha(preview.file.sha256)}
              </span>
            )}
            <Button size="sm" variant="ghost" className="ml-auto" disabled={applying} onClick={() => input.current?.click()}>
              {t("metadata.otherFile")}
            </Button>
          </div>

          {!preview && busy && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
              <Loader2 className="h-4 w-4 animate-spin" /> {t("metadata.reading")}
            </p>
          )}
          <ErrorNote error={error} />

          {preview && (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                {preview.file.kind === "csv" ? (
                  <>
                    <Field label={t("metadata.encoding")}>
                      <p className="flex h-10 items-center text-sm">{preview.file.encoding}</p>
                    </Field>
                    <Field label={t("metadata.delimiter")}>
                      <Select value={options.delimiter ?? ""} disabled={applying} onChange={(e) => reread({ delimiter: e.target.value || null, headerRow: null })}>
                        <option value="">
                          {t("metadata.delimiterAuto")}
                          {!options.delimiter && preview.file.delimiter ? `: ${delimiterLabel(t, preview.file.delimiter)}` : ""}
                        </option>
                        {DELIMITERS.map((d) => (
                          <option key={d.name} value={d.value}>
                            {t(`metadata.delimiter.${d.name}`)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </>
                ) : (
                  <Field label={t("metadata.sheet")} className="sm:col-span-2">
                    <Select
                      value={preview.file.sheet ?? ""}
                      disabled={applying || preview.file.sheets.length < 2}
                      onChange={(e) => reread({ sheet: e.target.value, headerRow: null })}
                    >
                      {preview.file.sheets.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                <Field label={t("metadata.headerRow")} hint={t("metadata.headerRowHint")}>
                  <Input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={headerInput}
                    disabled={applying}
                    onChange={(e) => setHeaderInput(e.target.value)}
                    onBlur={commitHeaderRow}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitHeaderRow();
                      }
                    }}
                  />
                </Field>
              </div>

              <section className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold">{t("metadata.columns")}</h4>
                  <Explain id="metadata_import" compact />
                </div>
                <p className="text-xs text-muted-foreground">{t("metadata.columnsHint")}</p>
                <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
                  {preview.columns.map((c) => (
                    <li key={c.header} className="grid gap-1 sm:grid-cols-2 sm:items-center sm:gap-3">
                      <span className="min-w-0 break-words text-sm">{c.header}</span>
                      <Select
                        aria-label={`${t("metadata.columns")}: ${c.header}`}
                        className="h-9"
                        value={mapping[c.header]}
                        disabled={applying}
                        aria-invalid={(duplicates as MetadataTarget[]).includes(mapping[c.header])}
                        onChange={(e) => setTarget(c.header, e.target.value as MetadataTarget)}
                      >
                        {[...METADATA_FIELDS, "custom" as const, "ignore" as const].map((target) => (
                          <option key={target} value={target}>
                            {targetLabel(t, target)}
                            {target === c.suggested_field ? ` (${t("metadata.suggested")})` : ""}
                          </option>
                        ))}
                      </Select>
                    </li>
                  ))}
                </ul>
                {duplicates.length > 0 && (
                  <ErrorNote error={t("metadata.duplicateMapping", { fields: duplicates.map((f) => t(`metadata.field.${f}`)).join(", ") })} />
                )}
              </section>

              {showDateOrder(preview) && (
                <fieldset className="space-y-2">
                  <legend className="text-sm font-semibold">{t("metadata.dateOrder")}</legend>
                  {preview.ambiguous_dates > 0 && (
                    <p className="text-xs text-muted-foreground">{t("metadata.dateOrderHint", { count: preview.ambiguous_dates })}</p>
                  )}
                  {preview.date_order_source === "header" && !options.dateOrder && (
                    <p className="text-xs text-muted-foreground">{t("metadata.dateOrderHeader")}</p>
                  )}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    {(preview.date_order_source === "header" ? (["DMY", "MDY"] as const) : (["", "DMY", "MDY"] as const)).map((v) => (
                      <label key={v} className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="metadata-date-order"
                          className="accent-[#00B4A6]"
                          checked={(options.dateOrder ?? preview.date_order ?? "") === v}
                          disabled={applying}
                          onChange={() => file && void run(file, { ...options, dateOrder: (v || null) as DateOrder | null })}
                        />
                        {v ? t(`metadata.dateOrder.${v}`) : t("metadata.dateOrder.none")}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}

              {preview.errors.length > 0 && (
                <div className="space-y-1">
                  {preview.errors.map((m, i) => (
                    <ErrorNote key={i} error={messageText(t, "metadata.msg", m)} />
                  ))}
                </div>
              )}
              {preview.warnings.length > 0 && (
                <Messages title={t("metadata.warnings")} items={preview.warnings} />
              )}

              <section className="space-y-2">
                <p className="text-sm font-medium" aria-live="polite">
                  {busy ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" /> {t("metadata.updating")}
                    </span>
                  ) : (
                    t("metadata.counts", { ...preview.counts })
                  )}
                </p>
                <Tabs<RowFilter>
                  value={filter}
                  onChange={(f) => {
                    setFilter(f);
                    setShown(PAGE);
                  }}
                  items={[
                    { value: "all", label: `${t("metadata.filter.all")} (${preview.counts.rows})` },
                    ...ACTIONS.map((a) => ({ value: a, label: `${t(`metadata.action.${a}`)} (${preview.counts[a]})` })),
                  ]}
                />
                {rows.length === 0 ? (
                  <p className="py-3 text-sm text-muted-foreground">{t("metadata.noRows")}</p>
                ) : (
                  <ul className={cn("max-h-[40vh] space-y-2 overflow-y-auto pr-1", busy && "opacity-60")}>
                    {rows.slice(0, shown).map((r) => (
                      <RowItem key={r.row} row={r} />
                    ))}
                  </ul>
                )}
                {rows.length > shown && (
                  <Button size="sm" variant="ghost" onClick={() => setShown((s) => s + PAGE)}>
                    {t("metadata.showMore", { count: Math.min(PAGE, rows.length - shown) })}
                  </Button>
                )}
              </section>

              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold">{t("metadata.mode")}</legend>
                {(
                  [
                    ["create_and_update", t("metadata.modeCreateUpdate")],
                    ["create_only", t("metadata.modeCreateOnly")],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value} className="flex items-start gap-2 text-sm">
                    <input
                      type="radio"
                      name="metadata-mode"
                      className="mt-1 accent-[#00B4A6]"
                      checked={mode === value}
                      disabled={applying}
                      onChange={() => {
                        setMode(value);
                        setConfirmed(false);
                      }}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>

              <p className="text-xs text-muted-foreground">{t("metadata.rules")}</p>
              {plan && plan.create + plan.update === 0 && upToDate && <ErrorNote error={t("metadata.nothingToApply")} />}
              {plan && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 accent-[#00B4A6]"
                    checked={confirmed}
                    disabled={!upToDate || applying || plan.create + plan.update === 0}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>{t("metadata.confirm", { ...plan })}</span>
                </label>
              )}
              <ErrorNote error={applyError} />
              <div className="flex flex-wrap justify-end gap-2">
                <Button variant="ghost" disabled={applying} onClick={() => onOpenChange(false)}>
                  {t("common.cancel")}
                </Button>
                <Button disabled={!canApply} onClick={apply}>
                  {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {t("metadata.apply")}
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

function Messages({ title, items }: { title: string; items: ServerMessage[] }) {
  const t = useT();
  return (
    <div className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2">
      <p className="flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-warning">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {title}
      </p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
        {items.map((m, i) => (
          <li key={i} className="break-words">
            {messageText(t, "metadata.msg", m)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RowItem({ row }: { row: MetadataRowPreview }) {
  const t = useT();
  return (
    <li className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-muted-foreground">{t("metadata.row", { row: row.row })}</span>
        <span className="min-w-0 break-all font-medium">{row.sample_code ?? t("metadata.noCode")}</span>
        <Badge tone={ACTION_TONE[row.action]}>{t(`metadata.action.${row.action}`)}</Badge>
      </div>
      {row.matched_by === "case_insensitive" && (
        <p className="mt-1 text-xs text-muted-foreground">{t("metadata.matchedCase", { code: row.matched_sample_code ?? "" })}</p>
      )}
      {row.changes.length > 0 && (
        <dl className="mt-2 grid gap-x-3 gap-y-0.5 text-xs sm:grid-cols-[minmax(8rem,auto)_1fr]">
          {row.changes.map((c, i) => (
            <Fragment key={i}>
              <dt className="min-w-0 break-words text-muted-foreground">{changeLabel(t, c)}</dt>
              <dd className="min-w-0 break-words">
                {row.action === "update" && (
                  <>
                    <span className="text-muted-foreground line-through decoration-muted-foreground/50">
                      {changeValue(c, c.old) ?? t("metadata.empty")}
                    </span>
                    {" → "}
                  </>
                )}
                {changeValue(c, c.new)}
              </dd>
            </Fragment>
          ))}
        </dl>
      )}
      {row.errors.map((m, i) => (
        <p key={`e${i}`} className="mt-1 break-words text-xs text-danger">
          {messageText(t, "metadata.msg", m)}
        </p>
      ))}
      {row.warnings.map((m, i) => (
        <p key={`w${i}`} className="mt-1 flex gap-1 break-words text-xs text-amber-700 dark:text-warning">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          <span className="min-w-0">{messageText(t, "metadata.msg", m)}</span>
        </p>
      ))}
    </li>
  );
}

function ApplyResult({ result, onClose }: { result: MetadataApplyResult; onClose: () => void }) {
  const t = useT();
  const r = result.record;
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 text-sm" aria-live="polite">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
        {t("metadata.done", { created: r.created_count, updated: r.updated_count, unchanged: r.unchanged_count, skipped: r.skipped_count })}
      </p>
      {result.skipped.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold">{t("metadata.skippedRows")}</h4>
          <ul className="mt-2 max-h-[40vh] space-y-1 overflow-y-auto text-xs">
            {result.skipped.map((s) => (
              <li key={s.row} className="break-words">
                <span className="font-medium">
                  {t("metadata.row", { row: s.row })} · {s.sample_code ?? t("metadata.noCode")}
                </span>
                : {s.reasons.map((m) => messageText(t, "metadata.msg", m)).join("; ")}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex justify-end">
        <Button onClick={onClose}>{t("common.close")}</Button>
      </div>
    </div>
  );
}

function DownloadLink({ href, label, children }: { href: string; label: string; children: ReactNode }) {
  return (
    <a
      href={href}
      download
      aria-label={label}
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground hover:bg-muted"
    >
      <Download className="h-3.5 w-3.5" aria-hidden />
      {children}
    </a>
  );
}

/** Project page: import, export and template actions, and the history of applied imports. */
export function MetadataSection({ projectId }: { projectId: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const imports = useQuery({ queryKey: ["metadataImports", projectId], queryFn: () => api.metadataImports(projectId) });
  return (
    <Card className="mt-6">
      <CardHeader title={t("metadata.cardTitle")} description={t("metadata.cardSubtitle")} action={<Explain id="metadata_import" compact />} />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button onClick={() => setOpen(true)}>
            <Upload className="h-4 w-4" /> {t("metadata.import")}
          </Button>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t("metadata.export")}:</span>
            <DownloadLink href={api.metadataExportUrl(projectId, "csv")} label={`${t("metadata.export")} ${t("metadata.exportCsv")}`}>
              {t("metadata.exportCsv")}
            </DownloadLink>
            <DownloadLink href={api.metadataExportUrl(projectId, "xlsx")} label={`${t("metadata.export")} ${t("metadata.exportXlsx")}`}>
              {t("metadata.exportXlsx")}
            </DownloadLink>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t("metadata.template")}:</span>
            <DownloadLink href={api.metadataTemplateUrl("csv")} label={`${t("metadata.template")} ${t("metadata.exportCsv")}`}>
              {t("metadata.exportCsv")}
            </DownloadLink>
            <DownloadLink href={api.metadataTemplateUrl("xlsx")} label={`${t("metadata.template")} ${t("metadata.exportXlsx")}`}>
              {t("metadata.exportXlsx")}
            </DownloadLink>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{t("metadata.templateHint")}</p>

        <section>
          <h4 className="mb-2 text-sm font-semibold">{t("metadata.history")}</h4>
          {imports.isLoading ? (
            <Skeleton className="h-12" />
          ) : imports.error ? (
            <ErrorNote error={imports.error} />
          ) : !imports.data?.length ? (
            <p className="text-sm text-muted-foreground">{t("metadata.historyEmpty")}</p>
          ) : (
            <ul className="space-y-2">
              {imports.data.map((r) => (
                <HistoryItem key={r.id} record={r} />
              ))}
            </ul>
          )}
        </section>
      </CardBody>
      <MetadataImportDialog open={open} onOpenChange={setOpen} projectId={projectId} />
    </Card>
  );
}

function HistoryItem({ record: r }: { record: MetadataImportRecord }) {
  const t = useT();
  const summary = summariseMapping(r.mapping);
  const read = [
    r.kind.toUpperCase(),
    r.sheet,
    r.delimiter ? delimiterLabel(t, r.delimiter) : null,
    r.encoding,
    t("metadata.historyHeaderRow", { row: r.header_row }),
    r.date_order ? t(`metadata.dateOrder.${r.date_order}`) : null,
    t(`metadata.mode.${r.mode}`),
  ].filter(Boolean);
  return (
    <li className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 break-all font-medium">{r.filename}</span>
        <span className="text-xs text-muted-foreground">{fmtDate(r.created_at)}</span>
      </div>
      <p className="mt-1 break-words text-xs text-muted-foreground">
        <span className="font-mono" title={r.sha256}>
          SHA-256 {shortSha(r.sha256)}
        </span>
        {" · "}
        {read.join(" · ")}
      </p>
      <p className="mt-1 text-xs">
        {t("metadata.historyCounts", { created: r.created_count, updated: r.updated_count, unchanged: r.unchanged_count, skipped: r.skipped_count })}
      </p>
      <details className="mt-1 text-xs">
        <summary className="cursor-pointer text-muted-foreground">{t("metadata.mappingDetails")}</summary>
        <ul className="mt-1 space-y-0.5">
          {summary.fields.map(([header, field]) => (
            <li key={header} className="break-words">
              {header} → {t(`metadata.field.${field}`)}
            </li>
          ))}
          {summary.custom.length > 0 && (
            <li className="break-words">
              {t("metadata.target.custom")}: {summary.custom.join(", ")}
            </li>
          )}
          {summary.ignored.length > 0 && (
            <li className="break-words">
              {t("metadata.target.ignore")}: {summary.ignored.join(", ")}
            </li>
          )}
        </ul>
      </details>
    </li>
  );
}

/** A sample's custom metadata (e.g. extra columns of an imported table); values can be edited or removed. */
export function CustomMetadataList({ sample }: { sample: Sample }) {
  const t = useT();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<CustomEdit[] | null>(null);
  const save = useMutation({
    mutationFn: (custom: Record<string, unknown> | null) => api.updateSample(sample.id, { custom_metadata: custom }),
    onSuccess: (s) => {
      qc.setQueryData(["sample", s.id], s);
      qc.invalidateQueries({ queryKey: ["samples"] });
      setDraft(null);
    },
  });
  const entries = customEntries(sample.custom_metadata);
  if (entries.length === 0) return null;
  const update = (i: number, change: Partial<CustomEdit>) => setDraft((d) => d && d.map((e, j) => (j === i ? { ...e, ...change } : e)));
  return (
    <section className="mt-6 border-t pt-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold">{t("metadata.customTitle")}</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">{draft ? t("metadata.customEditHint") : t("metadata.customHint")}</p>
        </div>
        {!draft && (
          <Button size="sm" variant="outline" onClick={() => setDraft(customDraft(sample.custom_metadata))}>
            <Pencil className="h-3.5 w-3.5" aria-hidden />
            {t("metadata.customEdit")}
          </Button>
        )}
      </div>
      {!draft ? (
        <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr]">
          {entries.map(([k, v]) => (
            <Fragment key={k}>
              <dt className="min-w-0 break-words text-muted-foreground">{k}</dt>
              <dd className="min-w-0 break-words">{v}</dd>
            </Fragment>
          ))}
        </dl>
      ) : (
        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(applyCustomEdits(sample.custom_metadata, draft));
          }}
        >
          <ul className="space-y-2">
            {draft.map((e, i) => (
              <li key={e.key} className="grid gap-2 sm:grid-cols-[minmax(8rem,auto)_1fr_auto] sm:items-center">
                <label htmlFor={`custom-${i}`} className={cn("min-w-0 break-words text-sm text-muted-foreground", e.removed && "line-through")}>
                  {e.key}
                </label>
                <Input id={`custom-${i}`} value={e.text} disabled={e.removed} onChange={(ev) => update(i, { text: ev.target.value })} />
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={t(e.removed ? "metadata.customKeep" : "metadata.customRemove", { key: e.key })}
                  onClick={() => update(i, { removed: !e.removed })}
                >
                  {e.removed ? <Undo2 className="h-3.5 w-3.5" aria-hidden /> : <Trash2 className="h-3.5 w-3.5" aria-hidden />}
                  {e.removed ? t("metadata.customUndo") : t("metadata.customRemoveShort")}
                </Button>
              </li>
            ))}
          </ul>
          <ErrorNote error={save.error} />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setDraft(null)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending || !customEditsChange(sample.custom_metadata, draft)}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
