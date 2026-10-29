import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { TECHNOLOGIES, technologyLabel } from "@/lib/format";
import type { Sample, SampleInput, SequencingTechnology } from "@/lib/types";

const FIELDS: { key: keyof SampleInput & `${string}`; placeholder?: TranslationKey; type?: string }[] = [
  { key: "organism", placeholder: "sampleForm.organismExample" },
  { key: "expected_species" },
  { key: "sample_type", placeholder: "sampleForm.sampleTypeExample" },
  { key: "host", placeholder: "sampleForm.hostExample" },
  { key: "geographic_origin" },
  { key: "collection_date", type: "date" },
  { key: "sequencing_run" },
  { key: "researcher" },
  { key: "institution" },
];

const fieldLabel = (key: string) => `metadata.field.${key}` as TranslationKey;

function toForm(s?: Sample): SampleInput {
  return {
    sample_code: s?.sample_code ?? "",
    sequencing_technology: s?.sequencing_technology ?? "unknown",
    ...Object.fromEntries(FIELDS.map((f) => [f.key, (s?.[f.key as keyof Sample] as string | null) ?? ""])),
    description: s?.description ?? "",
    notes: s?.notes ?? "",
  };
}

function clean(form: SampleInput): SampleInput {
  return Object.fromEntries(
    Object.entries(form).map(([k, v]) => [k, typeof v === "string" && v.trim() === "" && k !== "sample_code" ? null : v]),
  ) as SampleInput;
}

export function SampleFields({ form, setForm }: { form: SampleInput; setForm: (f: SampleInput) => void }) {
  const t = useT();
  const set = (k: keyof SampleInput) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("form.required", { label: t("metadata.field.sample_code") })}>
          <Input required maxLength={255} value={form.sample_code} onChange={set("sample_code")} placeholder={t("sampleForm.idExample")} />
        </Field>
        <Field label={t("metadata.field.sequencing_technology")}>
          <Select value={form.sequencing_technology} onChange={(e) => setForm({ ...form, sequencing_technology: e.target.value as SequencingTechnology })}>
            {TECHNOLOGIES.map((v) => (
              <option key={v} value={v}>
                {technologyLabel(v)}
              </option>
            ))}
          </Select>
        </Field>
        {FIELDS.map((f) => (
          <Field key={f.key} label={t(fieldLabel(f.key))}>
            <Input type={f.type ?? "text"} value={(form[f.key] as string) ?? ""} onChange={set(f.key)} placeholder={f.placeholder && t(f.placeholder)} />
          </Field>
        ))}
      </div>
      <Field label={t("metadata.field.description")}>
        <Textarea value={form.description ?? ""} onChange={set("description")} />
      </Field>
      <Field label={t("metadata.field.notes")}>
        <Textarea value={form.notes ?? ""} onChange={set("notes")} />
      </Field>
    </div>
  );
}

export function SampleFormDialog({
  open,
  onOpenChange,
  projectId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  projectId: string;
}) {
  const t = useT();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState<SampleInput>(toForm());
  useEffect(() => {
    if (open) setForm(toForm());
  }, [open]);

  const mutation = useMutation({
    mutationFn: (input: SampleInput) => api.createSample(projectId, input),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["samples"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onOpenChange(false);
      navigate(`/samples/${s.id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate(clean(form));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("samples.new")} description={t("sampleForm.description")} className="max-w-2xl">
      <form onSubmit={submit} className="space-y-4">
        <SampleFields form={form} setForm={setForm} />
        <ErrorNote error={mutation.error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={mutation.isPending || !form.sample_code.trim()}>
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function SampleMetadataEditor({ sample }: { sample: Sample }) {
  const t = useT();
  const qc = useQueryClient();
  const [form, setForm] = useState<SampleInput>(toForm(sample));
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(toForm(sample)), [sample]);
  const mutation = useMutation({
    mutationFn: (input: SampleInput) => api.updateSample(sample.id, input),
    onSuccess: (s) => {
      qc.setQueryData(["sample", s.id], s);
      qc.invalidateQueries({ queryKey: ["samples"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(clean(form));
      }}
      className="space-y-4"
    >
      <SampleFields form={form} setForm={setForm} />
      <ErrorNote error={mutation.error} />
      <div className="flex items-center justify-end gap-3">
        {saved && <span className="text-xs text-success">{t("common.saved")}</span>}
        <Button type="submit" disabled={mutation.isPending || !form.sample_code.trim()}>
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}
