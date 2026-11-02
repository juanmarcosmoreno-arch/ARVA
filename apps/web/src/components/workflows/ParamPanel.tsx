import { useMemo, useState } from "react";
import { Input, Select, Textarea } from "@/components/ui/form";
import { useT } from "@/i18n";
import { fieldProblem, getPath, paramFields, setPath, type NodeKind, type ParamField, type Problem } from "@/lib/workflows";

/** A node's parameters, as fields built from the analysis's own request model (the schema the API sends). Values are
 * checked here for type and range, and on the server with the same model as the analysis's dialog. Option names are
 * shown as the API names them (they are the tools' and ARVA's option identifiers). */
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
  const serverProblems = new Map(problems.filter((p) => p.code === "wf_param").map((p) => [String(p.params.field), String(p.params.message)]));
  if (!fields.length) return <p className="text-xs text-muted-foreground">{t("wf.param.none")}</p>;
  return (
    <div className="space-y-2.5">
      {fields.map((f) => (
        <FieldRow key={f.path} field={f} value={getPath(params, f.path)} serverProblem={serverProblems.get(f.path)} readOnly={readOnly}
          onChange={(v) => onChange(setPath(params, f.path, v))} />
      ))}
    </div>
  );
}

function FieldRow({ field: f, value, serverProblem, onChange, readOnly }: {
  field: ParamField;
  value: unknown;
  serverProblem?: string;
  onChange: (v: unknown) => void;
  readOnly: boolean;
}) {
  const t = useT();
  const [draft, setDraft] = useState<string | null>(null);
  const local = fieldProblem(f, value);
  const range = f.min !== undefined || f.max !== undefined ? t("wf.param.rangeHint", { min: f.min ?? "−∞", max: f.max ?? "∞" }) : "";
  const label = <span className="font-mono text-[11px]">{f.path}</span>;
  let control;
  if (f.kind === "boolean") {
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
