import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtBytes, fmtInt } from "@/lib/format";
import type { NcbiFilters, NcbiPlan, NcbiTaxon } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";
const DEFAULT_FILTERS: NcbiFilters = { source: "refseq", type_material: true, reference_only: false, exclude_atypical: true, exact_taxon: false };

/** Builds a reference genome collection from NCBI Datasets: the taxon and filters first, then what NCBI lists
 * (genomes, species, type material, size) — nothing is downloaded until that exact list is confirmed. */
export function NcbiCollectionDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [taxon, setTaxon] = useState("");
  const [filters, setFilters] = useState<NcbiFilters>(DEFAULT_FILTERS);
  const [confirmed, setConfirmed] = useState(false);
  const setFilter = <K extends keyof NcbiFilters>(k: K, v: NcbiFilters[K]) => {
    setFilters((f) => ({ ...f, [k]: v }));
    plan.reset();
    setConfirmed(false);
  };
  const plan = useMutation({ mutationFn: (id: number | null) => api.ncbiPlan({ taxon, tax_id: id, filters }) });
  const start = useMutation({
    mutationFn: (p: NcbiPlan) => api.ncbiStart({ taxon, tax_id: p.taxon!.tax_id, filters, confirm_genomes: p.genomes, confirm_fingerprint: p.fingerprint! }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["databases"] });
      onClose();
    },
  });
  const p = plan.data;
  const check = (id: number | null) => {
    setConfirmed(false);
    plan.mutate(id);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("ncbi.title")} description={t("ncbi.description")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field label={t("ncbi.taxon")} hint={t("ncbi.taxonHint")}>
            <Input
              value={taxon}
              maxLength={100}
              onChange={(e) => {
                setTaxon(e.target.value);
                plan.reset();
                setConfirmed(false);
              }}
              placeholder={t("ncbi.taxonPlaceholder")}
            />
          </Field>
          <Button onClick={() => check(null)} disabled={!taxon.trim() || plan.isPending}>
            {plan.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} {t("ncbi.check")}
          </Button>
        </div>
        <fieldset className="grid gap-2 sm:grid-cols-2">
          <Field label={t("ncbi.source")}>
            <Select value={filters.source} onChange={(e) => setFilter("source", e.target.value as NcbiFilters["source"])}>
              <option value="refseq">{t("ncbi.source.refseq")}</option>
              <option value="genbank">{t("ncbi.source.genbank")}</option>
              <option value="all">{t("ncbi.source.all")}</option>
            </Select>
          </Field>
          <div className="space-y-1.5 text-xs">
            {(["type_material", "reference_only", "exclude_atypical", "exact_taxon"] as const).map((k) => (
              <label key={k} className="flex items-start gap-2">
                <input type="checkbox" className={CHECK} checked={filters[k]} onChange={(e) => setFilter(k, e.target.checked)} />
                <span>{t(`ncbi.filter.${k}` as TranslationKey)}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <p className="text-xs text-muted-foreground">{t("ncbi.privacy")}</p>
        <ErrorNote error={plan.error} />
        {p?.status === "choose_taxon" && <Candidates candidates={p.candidates} onChoose={(c) => check(c.tax_id)} />}
        {p?.status === "too_many" && <p className="text-amber-700 dark:text-warning">{t("ncbi.tooMany", { count: p.total_count ?? 0, limit: p.limit ?? 0 })}</p>}
        {p?.status === "no_genomes" && <p className="text-muted-foreground">{t("ncbi.noGenomes", { taxon: p.taxon?.name ?? taxon })}</p>}
        {p?.status === "ready" && <PlanFacts plan={p} />}
        {p?.status === "ready" && (
          <>
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              <span>{t("ncbi.confirm", { n: p.genomes, size: fmtBytes(p.zip_estimate_bytes ?? 0) })}</span>
            </label>
            {!p.enough && <p className="text-amber-700 dark:text-warning">{t("ncbi.noSpace", { needed: fmtBytes(p.required_bytes ?? 0), available: fmtBytes(p.available_bytes ?? 0) })}</p>}
            {p.target_exists && <p className="text-amber-700 dark:text-warning">{t("ncbi.targetExists", { path: p.host_target_path ?? "" })}</p>}
          </>
        )}
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            onClick={() => p && start.mutate(p)}
            disabled={!p || p.status !== "ready" || !confirmed || !p.enough || Boolean(p.target_exists) || start.isPending}
          >
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} {t("ncbi.download")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function Candidates({ candidates, onChoose }: { candidates: NcbiTaxon[]; onChoose: (c: NcbiTaxon) => void }) {
  const t = useT();
  return (
    <div className="space-y-2 rounded-lg border p-3 text-xs">
      <p className="font-medium">{t("ncbi.choose")}</p>
      {candidates.map((c) => (
        <button key={c.tax_id} type="button" onClick={() => onChoose(c)} className="block w-full rounded border px-2 py-1 text-left hover:bg-muted">
          {c.name} · {c.rank ?? "?"} · {t("ncbi.taxId", { id: c.tax_id })}
        </button>
      ))}
    </div>
  );
}

function PlanFacts({ plan: p }: { plan: NcbiPlan }) {
  const t = useT();
  return (
    <div className="space-y-2 rounded-lg border p-3 text-xs">
      <p className="flex flex-wrap items-center gap-2 font-medium">
        {p.taxon?.name} <Badge>{p.taxon?.rank ?? "?"}</Badge> <span className="text-muted-foreground">{t("ncbi.taxId", { id: p.taxon?.tax_id ?? 0 })}</span>
        <Explain id="reference_collection" compact />
      </p>
      <p>{t("ncbi.counts", { genomes: p.genomes, species: p.species ?? 0, type: p.type_material ?? 0, reference: p.reference_genomes ?? 0 })}</p>
      <p>
        {t("ncbi.sizes", {
          zip: p.download?.estimated_mb ?? "?",
          fasta: fmtBytes(p.fasta_estimate_bytes ?? 0),
          free: fmtBytes(p.available_bytes ?? 0),
        })}
      </p>
      <p className="text-muted-foreground">{t("ncbi.destination", { path: p.host_target_path ?? "" })}</p>
      {p.by_species.length > 1 && (
        <p className="text-muted-foreground">
          {t("ncbi.bySpecies")} {p.by_species.slice(0, 10).map((s) => `${s.species} (${fmtInt(s.genomes)})`).join(", ")}
          {p.by_species.length > 10 ? " …" : ""}
        </p>
      )}
      {(p.type_material ?? 0) < p.genomes && (
        <p className="flex gap-1.5 text-amber-700 dark:text-warning">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("ncbi.notAllType", { n: p.genomes - (p.type_material ?? 0) })}
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-muted-foreground">{t("ncbi.preview", { n: p.preview.length })}</summary>
        <ul className="mt-1 space-y-0.5">
          {p.preview.map((g) => (
            <li key={g.accession}>
              <code>{g.accession}</code> {g.organism}
              {g.strain ? ` · ${g.strain}` : ""}
              {g.type_label ? ` · ${t("species.typeMaterial")}` : ""}
              {g.length ? ` · ${fmtBases(g.length)}` : ""}
            </li>
          ))}
        </ul>
      </details>
      {p.query_url && <p className="break-all text-muted-foreground">{t("ncbi.query", { url: p.query_url })}</p>}
    </div>
  );
}
