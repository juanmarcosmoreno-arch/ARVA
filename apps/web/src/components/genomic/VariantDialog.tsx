import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtInt } from "@/lib/format";
import { hasReads } from "@/lib/results";
import { formProblems, initialVariantForm, isLong, TECHNOLOGIES, type Technology, type VariantForm, variantBody, type VariantSettings } from "@/lib/variants";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Variant calling of the sample's reads against a reference: the technology (which sets the aligner and bcftools'
 * profile), the reference (an ARVA assembly or a genome of a reference collection), the reads, the filters with
 * their source, and a preview of the tools, the reference's checksum and every note before an explicit confirmation. */
export function VariantDialog({ open, onOpenChange, sampleId }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string }) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: ["variantOptions", sampleId], queryFn: () => api.variantOptions(sampleId), enabled: open });
  const files = useQuery({ queryKey: ["files", sampleId], queryFn: () => api.files(sampleId), enabled: open });
  const [form, setForm] = useState<VariantForm>(() => initialVariantForm(undefined, null));
  const [search, setSearch] = useState("");
  useEffect(() => {
    if (open && options.data) setForm(initialVariantForm(options.data, options.data.suggested_technology));
    // Only when the dialog opens (or its options arrive): the user's choices are never replaced while it is open.
  }, [open, options.data]);
  const set = <K extends keyof VariantForm>(key: K, value: VariantForm[K]) => setForm((f) => ({ ...f, [key]: value, confirmed: key === "confirmed" ? (value as boolean) : false }));
  const setNum = (key: keyof VariantSettings, raw: string) => {
    const n = Number(raw);
    setForm((f) => ({ ...f, settings: { ...f.settings, [key]: raw === "" ? null : Number.isFinite(n) ? n : f.settings[key] }, confirmed: false }));
  };
  const genomes = useQuery({
    queryKey: ["collectionGenomes", form.databaseId, search],
    queryFn: () => api.collectionGenomes(form.databaseId, search),
    enabled: open && form.referenceKind === "collection" && Boolean(form.databaseId),
  });
  const missing = formProblems(form);
  const body = variantBody(form);
  const plan = useQuery({
    queryKey: ["variantPlan", sampleId, JSON.stringify({ ...body, confirmed: false })],
    queryFn: () => api.variantPreview(sampleId, { ...body, confirmed: false }),
    enabled: open && missing.length === 0,
    retry: false,
  });
  const p = plan.data;
  const run = useMutation({
    mutationFn: () => api.runVariants(sampleId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["variants", sampleId] });
      onOpenChange(false);
    },
  });
  const reads = (files.data ?? []).filter((f) => hasReads(f.file_format) && f.is_valid);
  const readSelect = (role: "r1" | "r2" | "unpaired" | "long") => (
    <Field key={role} label={t(`variants.role.${role}` as TranslationKey)}>
      <Select value={form[role]} onChange={(e) => set(role, e.target.value)}
        disabled={role === "unpaired" ? Boolean(form.r1 || form.r2) : role !== "long" && Boolean(form.unpaired)}>
        <option value="">{t("variants.noFile")}</option>
        {reads.map((f) => (
          <option key={f.id} value={f.id}>{f.original_filename}</option>
        ))}
      </Select>
    </Field>
  );
  const o = options.data;
  const profile = o?.defaults.profiles[form.technology];

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("variants.title")} description={t("variants.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <ErrorNote error={options.error ?? files.error} />
        <section className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-semibold">{t("variants.technology")}</h4>
            <Explain id="variant_calling" compact />
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {TECHNOLOGIES.map((tech: Technology) => (
              <label key={tech} className="flex items-start gap-2 rounded-lg border p-2 text-xs">
                <input type="radio" className={CHECK} checked={form.technology === tech} onChange={() => set("technology", tech)} />
                <span>
                  <span className="font-medium">{t(`variants.tech.${tech}` as TranslationKey)}</span>
                  <span className="block text-muted-foreground">{t(`variants.techHint.${tech}` as TranslationKey)}</span>
                </span>
              </label>
            ))}
          </div>
          {o?.suggested_technology && o.suggested_technology !== form.technology && (
            <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning"><Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("variants.techDiffers", { tech: t(`variants.tech.${o.suggested_technology}` as TranslationKey) })}</p>
          )}
        </section>

        <section className="space-y-2">
          <h4 className="text-sm font-semibold">{t("variants.reference")}</h4>
          <div className="flex gap-4 text-xs">
            {(["assembly", "collection"] as const).map((k) => (
              <label key={k} className="flex items-center gap-2">
                <input type="radio" className={CHECK} checked={form.referenceKind === k} onChange={() => set("referenceKind", k)} disabled={k === "collection" && !o?.collections.length} />
                {t(`variants.refKind.${k}` as TranslationKey)}
              </label>
            ))}
          </div>
          {form.referenceKind === "assembly" ? (
            <Select value={form.assemblyId} onChange={(e) => set("assemblyId", e.target.value)} aria-label={t("variants.reference")}>
              {(o?.assemblies ?? []).map((a) => (
                <option key={a.assembly_id} value={a.assembly_id}>
                  {a.label} · {fmtInt(a.contigs ?? 0)} contigs · {fmtBases(a.total_length ?? 0)}{a.annotation ? ` · ${t("variants.annotated", { tool: a.annotation.tool })}` : ""}{a.own_sample ? ` · ${t("variants.ownSample")}` : ""}
                </option>
              ))}
            </Select>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              <Select value={form.databaseId} onChange={(e) => set("databaseId", e.target.value)} aria-label={t("variants.collection")}>
                {(o?.collections ?? []).map((c) => (
                  <option key={c.database_id} value={c.database_id} disabled={!c.available}>{c.name} {c.version ?? ""} · {t("variants.genomes", { n: c.genomes })}</option>
                ))}
              </Select>
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("variants.genomeSearch")} aria-label={t("variants.genomeSearch")} />
              <Select className="sm:col-span-2" value={form.genomeKey} onChange={(e) => set("genomeKey", e.target.value)} aria-label={t("variants.genome")}>
                <option value="">{t("variants.chooseGenome")}</option>
                {(genomes.data ?? []).map((g) => (
                  <option key={g.key} value={g.key}>{[g.organism, g.strain, g.accession].filter(Boolean).join(" · ") || g.key}</option>
                ))}
              </Select>
            </div>
          )}
          <p className="text-xs text-muted-foreground">{t("variants.referenceHint")}</p>
        </section>

        <section className="space-y-2">
          <h4 className="text-sm font-semibold">{t("variants.reads")}</h4>
          <div className="grid gap-3 sm:grid-cols-3">
            {isLong(form.technology) ? readSelect("long") : (["r1", "r2", "unpaired"] as const).map(readSelect)}
          </div>
        </section>

        <section className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-semibold">{t("variants.filters")}</h4>
            <Explain id="variant_filters" compact />
          </div>
          <p className="text-xs text-muted-foreground">{t("variants.filtersSource")}</p>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label={t("variants.minQual")}><Input type="number" step="any" value={form.settings.min_qual} onChange={(e) => setNum("min_qual", e.target.value)} /></Field>
            <Field label={t("variants.minDepth")}><Input type="number" min={0} value={form.settings.min_depth} onChange={(e) => setNum("min_depth", e.target.value)} /></Field>
            <Field label={t("variants.minAltFraction")}><Input type="number" step="0.01" min={0} max={1} value={form.settings.min_alt_fraction} onChange={(e) => setNum("min_alt_fraction", e.target.value)} /></Field>
            <Field label={t("variants.minMapq")}><Input type="number" min={0} max={60} value={form.settings.min_mapq} onChange={(e) => setNum("min_mapq", e.target.value)} /></Field>
            <Field label={t("variants.minBaseq")} hint={profile ? t("variants.profileValue", { value: profile.min_baseq }) : undefined}>
              <Input type="number" min={0} max={60} placeholder={profile ? String(profile.min_baseq) : ""} value={form.settings.min_baseq ?? ""} onChange={(e) => setNum("min_baseq", e.target.value)} />
            </Field>
            <Field label={t("variants.maxDepth")} hint={t("variants.maxDepthHint")}><Input type="number" min={10} value={form.settings.max_depth} onChange={(e) => setNum("max_depth", e.target.value)} /></Field>
            <Field label={t("annotation.threads")} hint={p ? t("variants.threadsHint", { max: p.resources.max_threads }) : undefined}>
              <Input type="number" min={1} placeholder="4" value={form.threads} onChange={(e) => set("threads", e.target.value)} />
            </Field>
          </div>
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className={CHECK} checked={form.effects} onChange={(e) => set("effects", e.target.checked)} />
            <span>{t("variants.effects")}</span>
          </label>
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className={CHECK} checked={form.keepAlignment} onChange={(e) => set("keepAlignment", e.target.checked)} />
            <span>{t("variants.keepAlignment")}</span>
          </label>
        </section>

        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && (
          <section className="space-y-1 rounded-lg border bg-muted/30 p-3 text-xs">
            <p>{t("variants.planTools", { aligner: `${p.tools[p.aligner.tool]?.name ?? p.aligner.tool} ${p.tools[p.aligner.tool]?.version ?? "?"}${p.aligner.preset ? ` -x ${p.aligner.preset}` : ""}`, samtools: p.tools.samtools?.version ?? "?", bcftools: p.tools.bcftools?.version ?? "?" })}</p>
            <p>{t("variants.planReference", { label: p.reference.label, length: fmtBases(p.reference.total_length), sequences: fmtInt(p.reference.contigs?.length ?? 0), sha: p.reference.sha256.slice(0, 16) })}</p>
            <p>{p.effects ? t("variants.planEffects", { tool: p.reference.annotation?.tool ?? "?" }) : t("variants.planNoEffects")}</p>
            <p>{t("variants.planSample", { name: p.read_group_sample })}</p>
            {p.notes.map((n) => (
              <p key={n.code} className="flex gap-1.5 text-amber-700 dark:text-warning"><Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t(`variants.note.${n.code}` as TranslationKey, n.params)}</p>
            ))}
          </section>
        )}

        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("variants.caveat")}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("variants.confirm")}</span>
        </label>
        {(missing.length > 0 || (p?.problems.length ?? 0) > 0) && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {missing.map((k) => <li key={k}>{t(k)}</li>)}
            {p?.problems.map((x) => (
              <li key={x.code} className="text-amber-700 dark:text-warning">{t(`variants.planProblem.${x.code}` as TranslationKey, { tool: "?", status: "?", flags: "", ...x.params })}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => run.mutate()} disabled={!p || !form.confirmed || p.problems.length > 0 || missing.length > 0 || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("variants.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
