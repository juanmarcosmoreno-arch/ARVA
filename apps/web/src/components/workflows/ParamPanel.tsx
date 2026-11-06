import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Input, Select, Textarea } from "@/components/ui/form";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fieldProblem, getPath, nodeDatabaseKind, paramFields, paramLabel, setPath, type NodeKind, type ParamField, type Problem } from "@/lib/workflows";

/** A node's parameters, as fields built from the analysis's own request model (the schema the API sends). Values are
 * checked here for type and range, and on the server with the same model as the analysis's dialog. Each option shows
 * its translated name with the identifier the API (and the exported definition) uses for it. */
export function ParamPanel({
  kind,
  params,
  problems,
  onChange,
  readOnly = false,
}: {
  kind: NodeKind;
  params: Record<string, unknown>;
  problems: Problem[];
  onChange: (params: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const t = useT();
  const fields = useMemo(() => paramFields(kind.params_schema), [kind]);
  const dbKind = nodeDatabaseKind(kind, params);
  const serverProblems = new Map(problems.filter((p) => p.code === "wf_param").map((p) => [String(p.params.field), String(p.params.message)]));
  if (!fields.length) return <p className="text-xs text-muted-foreground">{t("wf.param.none")}</p>;
  return (
    <div className="space-y-2.5">
      {fields.map((f) => (
        <FieldRow key={f.path} field={f} value={getPath(params, f.path)} serverProblem={serverProblems.get(f.path)} readOnly={readOnly}
          databaseKind={f.path === "database_id" ? dbKind : undefined} onChange={(v) => onChange(setPath(params, f.path, v))} />
      ))}
    </div>
  );
}

function FieldRow({ field: f, value, serverProblem, onChange, readOnly, databaseKind }: {
  field: ParamField;
  value: unknown;
  serverProblem?: string;
  onChange: (v: unknown) => void;
  readOnly: boolean;
  /** For database_id: the kind of registered database it names (null: the method uses none). */
  databaseKind?: string | null;
}) {
  const t = useT();
  const [draft, setDraft] = useState<string | null>(null);
  const local = fieldProblem(f, value);
  const range = f.min !== undefined || f.max !== undefined ? t("wf.param.rangeHint", { min: f.min ?? "−∞", max: f.max ?? "∞" }) : "";
  const name = paramLabel(t, f.path);
  const label = name ? (
    <span>
      {name} <span className="font-mono text-[10px] text-muted-foreground">{f.path}</span>
    </span>
  ) : (
    <span className="font-mono text-[11px]">{f.path}</span>
  );
  let control;
  if (databaseKind !== undefined) {
    control = <DatabaseSelect kind={databaseKind} value={typeof value === "string" ? value : null} readOnly={readOnly} onChange={onChange} />;
  } else if (f.kind === "boolean") {
    control = <input type="checkbox" className="h-4 w-4 accent-arva-teal" checked={Boolean(value)} disabled={readOnly} onChange={(e) => onChange(e.target.checked)} />;
  } else if (f.kind === "enum") {
    control = (
      <Select className="h-8 text-xs" value={value === null || value === undefined ? "" : String(value)} disabled={readOnly}
        onChange={(e) => {
          const raw = e.target.value;
          const opt = f.options?.find((o) => String(o) === raw);
          onChange(raw === "" ? null : opt ?? raw);
        }}>
        {(f.nullable || value === null || value === undefined) && <option value="">{t("wf.param.unset")}</option>}
        {f.options?.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
      </Select>
    );
  } else if (f.kind === "integer" || f.kind === "number") {
    control = (
      <Input className="h-8 text-xs" type="number" value={value === null || value === undefined ? "" : String(value)} disabled={readOnly}
        step={f.kind === "integer" ? 1 : "any"} placeholder={f.nullable ? t("wf.param.unset") : undefined}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    );
  } else if (f.kind === "string") {
    control = (
      <Input className="h-8 text-xs" value={value === null || value === undefined ? "" : String(value)} disabled={readOnly}
        placeholder={f.nullable ? t("wf.param.unset") : undefined} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)} />
    );
  } else {
    const text = draft ?? JSON.stringify(value ?? null);
    let bad = false;
    try {
      JSON.parse(text);
    } catch {
      bad = true;
    }
    control = (
      <Textarea className="min-h-[40px] font-mono text-[11px]" value={text} disabled={readOnly}
        onChange={(e) => {
          setDraft(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
          } catch {
            /* kept as a draft until it is valid JSON */
          }
        }} aria-invalid={bad} />
    );
  }
  return (
    <div className={f.kind === "boolean" ? "flex items-center justify-between gap-2" : "space-y-1"}>
      <label className="block text-xs">{label}</label>
      {control}
      {range && f.kind !== "boolean" && <p className="text-[10px] text-muted-foreground">{range}</p>}
      {local && !readOnly && <p className="text-[11px] text-danger">{t(local)}</p>}
      {serverProblem && <p className="text-[11px] text-danger">{t("wf.param.server", { message: serverProblem })}</p>}
    </div>
  );
}

/** database_id as a choice among the registered databases of the node's kind (the Database Manager's records), as
 * the analysis dialogs offer them. Empty: the kind's default database, which the step resolves when it runs. The
 * stored value stays the record's id (or null). */
function DatabaseSelect({ kind, value, readOnly, onChange }: {
  kind: string | null;
  value: string | null;
  readOnly: boolean;
  onChange: (v: string | null) => void;
}) {
  const t = useT();
  const records = useQuery({ queryKey: ["databases"], queryFn: api.databases, enabled: kind !== null });
  if (kind === null && !value) return <p className="text-[11px] text-muted-foreground">{t("wf.param.dbNone")}</p>;
  const options = (records.data ?? []).filter((r) => r.kind === kind);
  const known = !value || options.some((r) => r.id === value);
  return (
    <div className="space-y-1">
      <Select className="h-8 text-xs" value={value ?? ""} disabled={readOnly} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}>
        <option value="">{t("wf.param.dbDefaultOption")}</option>
        {options.map((r) => {
          const usable = (r.status === "installed" || r.status === "registered") && r.available !== false;
          return (
            <option key={r.id} value={r.id} disabled={!usable && r.id !== value}>
              {[r.name, r.version, r.is_default ? t("wf.param.dbDefault") : null, usable ? null : t("wf.param.dbUnusable")].filter(Boolean).join(" · ")}
            </option>
          );
        })}
        {!known && value && <option value={value}>{t("wf.param.dbUnknown", { id: value })}</option>}
      </Select>
      {records.isError && <p className="text-[11px] text-danger">{t("wf.param.dbLoadError")}</p>}
      {!records.isLoading && kind !== null && options.length === 0 && <p className="text-[11px] text-muted-foreground">{t("wf.param.dbNoneRegistered")}</p>}
    </div>
  );
}
