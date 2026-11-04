import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Eye, Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt, fmtMax, fmtNum } from "@/lib/format";
import { codedKey, defaultPair, DEFAULT_MIXED_RATIO, DEFAULT_TRIM_LIMIT, pairSignature, suspicionRequest, trimRequest, type BuildIn, type ConsensusIn, type ConsensusPreview, type IdentificationResults, type SangerOverview, type Suspected } from "@/lib/sanger";
import { ConsensusView } from "./ConsensusView";

const NUM = (v: string) => {
  const n = Number.parseFloat(v.replace(",", "."));
  return Number.isFinite(n) ? n : null;
};

/** Build what is searched: choose the forward and reverse reads (the proposed pair by default) or one read, set the
 * trimming of each and, if wanted, the alignment and conflict settings; preview the consensus with every conflict;
 * say what you suspect (optional) and save it as an identification. */
export function ConsensusBuilder({ sampleId, overview, onCreated }: { sampleId: string; overview: SangerOverview; onCreated: (r: IdentificationResults) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [forward, setForward] = useState<string>("");
  const [reverse, setReverse] = useState<string>("");
  const [limitF, setLimitF] = useState(String(DEFAULT_TRIM_LIMIT));
  const [limitR, setLimitR] = useState(String(DEFAULT_TRIM_LIMIT));
  const [manual, setManual] = useState({ fs: "", fe: "", rs: "", re: "" });
  const [ratio, setRatio] = useState(String(DEFAULT_MIXED_RATIO));
  const [params, setParams] = useState<Record<keyof ConsensusIn, string>>({ match: "", mismatch: "", gap_open: "", gap_extend: "", min_winner_quality: "", min_quality_difference: "", min_overlap: "", min_overlap_identity: "" });
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<Suspected["kind"]>("gene");
  const [suspect, setSuspect] = useState("");
  const [notes, setNotes] = useState("");
  const [preview, setPreview] = useState<ConsensusPreview | null>(null);
  const signature = pairSignature(overview.reads);
  useEffect(() => {
    const p = defaultPair(overview);
    setForward(p.forward ?? "");
    setReverse(p.reverse ?? "");
    // When the reads change (a new upload) or a direction or pair key is corrected in the reads table, not on every
    // refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const body = (): BuildIn => ({
    forward_read_id: forward || null,
    reverse_read_id: reverse || null,
    forward_trim: trimRequest(NUM(limitF) ?? DEFAULT_TRIM_LIMIT, manual.fs, manual.fe),
    reverse_trim: trimRequest(NUM(limitR) ?? DEFAULT_TRIM_LIMIT, manual.rs, manual.re),
    consensus: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, NUM(v)])) as ConsensusIn,
    mixed_ratio: NUM(ratio) ?? DEFAULT_MIXED_RATIO,
  });
  const previewing = useMutation({ mutationFn: () => api.sangerConsensus(sampleId, body()), onSuccess: setPreview });
  const create = useMutation({
    mutationFn: () => api.createSangerIdentification(sampleId, { ...body(), label: label.trim() || null, suspected: suspicionRequest(kind, suspect), notes: notes.trim() || null }),
    onSuccess: (r) => {
      qc.setQueryData(["sanger", "identification", r.identification.id], r);
      qc.invalidateQueries({ queryKey: ["sanger", sampleId] });
      setPreview(null);
      setSuspect("");
      setLabel("");
      setNotes("");
      onCreated(r);
    },
  });
  useEffect(() => setPreview(null), [forward, reverse, limitF, limitR, manual, ratio, params]);
  const reads = overview.reads;
  const fwd = reads.find((r) => r.id === forward);
  const rev = reads.find((r) => r.id === reverse);
  const nothing = !forward && !reverse;
  const same = forward && forward === reverse;

  if (reads.length === 0) return null;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1">
            {t("sanger.build.title")} <Explain id="sanger_consensus" compact />
          </span>
        }
        description={t("sanger.build.subtitle")}
      />
      <CardBody className="space-y-4 text-sm">
        {overview.pairs.some((p) => p.status === "ambiguous") && <p className="text-xs text-amber-700 dark:text-warning">{t("sanger.build.ambiguousPairs")}</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <ReadChoice label={t("sanger.build.forward")} value={forward} onChange={setForward} overview={overview} limit={limitF} setLimit={setLimitF} start={manual.fs} end={manual.fe} setRange={(fs, fe) => setManual((m) => ({ ...m, fs, fe }))} hasQualities={fwd?.has_qualities ?? true} />
          <ReadChoice label={t("sanger.build.reverse")} value={reverse} onChange={setReverse} overview={overview} limit={limitR} setLimit={setLimitR} start={manual.rs} end={manual.re} setRange={(rs, re) => setManual((m) => ({ ...m, rs, re }))} hasQualities={rev?.has_qualities ?? true} />
        </div>
        {fwd && fwd.direction === "reverse" && <p className="text-xs text-amber-700 dark:text-warning">{t("sanger.build.directionMismatch", { name: fwd.name, direction: t("sanger.direction.reverse") })}</p>}
        {rev && rev.direction === "forward" && <p className="text-xs text-amber-700 dark:text-warning">{t("sanger.build.directionMismatch", { name: rev.name, direction: t("sanger.direction.forward") })}</p>}
        {same && <p className="text-xs text-danger">{t("api.error.sanger_same_read")}</p>}
        <details className="rounded-lg border p-3 text-xs">
          <summary className="cursor-pointer font-medium">{t("sanger.build.advanced")}</summary>
          <p className="mt-2 text-muted-foreground">{t("sanger.build.advancedHint")}</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-4">
            {(Object.keys(params) as (keyof ConsensusIn)[]).map((k) => (
              <Field key={k} label={t(`sanger.param.${k}` as const)}>
                <Input inputMode="decimal" placeholder={t(`sanger.paramDefault.${k}` as const)} value={params[k]} onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))} />
              </Field>
            ))}
            <Field label={t("sanger.mixed.ratio")} hint={t("sanger.mixed.ratioHint")}>
              <Input inputMode="decimal" value={ratio} onChange={(e) => setRatio(e.target.value)} />
            </Field>
          </div>
        </details>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => previewing.mutate()} disabled={nothing || Boolean(same) || previewing.isPending}>
            {previewing.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />} {t("sanger.build.preview")}
          </Button>
        </div>
        <ErrorNote error={previewing.error} />
        {preview && <PreviewSummary preview={preview} />}
        {preview && preview.status !== "no_overlap" && (
          <ConsensusView result={preview} reads={{ forward: fwd ?? null, reverse: rev ?? null }} trims={{ forward: body().forward_trim, reverse: body().reverse_trim }} />
        )}

        <fieldset className="space-y-3 rounded-lg border p-3">
          <legend className="flex items-center gap-1 px-1 text-xs font-semibold">
            {t("sanger.suspect.title")} <Explain id="sanger_suspected" compact />
          </legend>
          <p className="text-xs text-muted-foreground">{t("sanger.suspect.hint")}</p>
          <SuspectFields kind={kind} setKind={setKind} value={suspect} setValue={setSuspect} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("sanger.build.label")} hint={t("sanger.build.labelHint")}>
              <Input value={label} maxLength={255} onChange={(e) => setLabel(e.target.value)} />
            </Field>
            <Field label={t("sanger.build.notes")}>
              <Textarea value={notes} maxLength={5000} onChange={(e) => setNotes(e.target.value)} />
            </Field>
          </div>
        </fieldset>
        <ErrorNote error={create.error} />
        <div className="flex justify-end">
          <Button onClick={() => create.mutate()} disabled={nothing || Boolean(same) || create.isPending || preview?.status === "no_overlap"}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} {t("sanger.build.save")}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

/** What the user suspects the sequence is: a gene (any name) or a species (a single word is a genus). Optional. */
export function SuspectFields({ kind, setKind, value, setValue }: { kind: Suspected["kind"]; setKind: (k: Suspected["kind"]) => void; value: string; setValue: (v: string) => void }) {
  const t = useT();
  return (
    <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
      <Field label={t("sanger.suspect.kind")}>
        <Select value={kind} onChange={(e) => setKind(e.target.value as Suspected["kind"])}>
          <option value="gene">{t("sanger.suspect.gene")}</option>
          <option value="species">{t("sanger.suspect.species")}</option>
        </Select>
      </Field>
      <Field label={t("sanger.suspect.value")} hint={kind === "gene" ? t("sanger.suspect.geneHint") : t("sanger.suspect.speciesHint")}>
        <Input value={value} maxLength={200} onChange={(e) => setValue(e.target.value)} placeholder={kind === "gene" ? t("sanger.suspect.genePlaceholder") : t("sanger.suspect.speciesPlaceholder")} />
      </Field>
    </div>
  );
}

function ReadChoice({ label, value, onChange, overview, limit, setLimit, start, end, setRange, hasQualities }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  overview: SangerOverview;
  limit: string;
  setLimit: (v: string) => void;
  start: string;
  end: string;
  setRange: (s: string, e: string) => void;
  hasQualities: boolean;
}) {
  const t = useT();
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <Field label={label}>
        <Select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t("sanger.build.noRead")}</option>
          {overview.reads.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} · {t(`sanger.direction.${r.direction}` as const)} · {fmtInt(r.length)}
            </option>
          ))}
        </Select>
      </Field>
      {value && (
        <div className="grid grid-cols-3 gap-2">
          <Field label={t("sanger.trim.limit")}>
            <Input inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} disabled={!hasQualities} />
          </Field>
          <Field label={t("sanger.trim.manualStart")}>
            <Input inputMode="numeric" value={start} onChange={(e) => setRange(e.target.value, end)} />
          </Field>
          <Field label={t("sanger.trim.manualEnd")}>
            <Input inputMode="numeric" value={end} onChange={(e) => setRange(start, e.target.value)} />
          </Field>
          {!hasQualities && <p className="col-span-3 text-[11px] text-amber-700 dark:text-warning">{t("sanger.warning.not_trimmed_no_qualities")}</p>}
        </div>
      )}
    </div>
  );
}

function PreviewSummary({ preview }: { preview: ConsensusPreview }) {
  const t = useT();
  const o = preview.overlap;
  return (
    <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={preview.status === "no_overlap" ? "danger" : "teal"}>{t(`sanger.build.status.${preview.status}` as const)}</Badge>
        <span>{t("sanger.build.length", { n: fmtInt(preview.length) })}</span>
        {o && (
          <span>
            {t("sanger.build.overlap", { columns: fmtInt(o.columns), identity: fmtNum(o.identity, 2), mismatches: fmtInt(o.mismatches), gaps: fmtInt(o.gaps) })}
          </span>
        )}
        {preview.status === "ok" && (
          <span>
            {t("sanger.build.conflicts", { n: preview.conflicts.length, resolved: preview.counts.resolved ?? 0, unresolved: preview.counts.unresolved ?? 0 })}
          </span>
        )}
      </div>
      {preview.score != null && <p className="text-muted-foreground">{t("sanger.build.score", { score: fmtMax(preview.score, 1) })} {preview.source && t("sanger.cite", { source: preview.source })}</p>}
      <ConsensusWarnings warnings={preview.warnings} />
      {preview.reverse_complemented && <p className="text-muted-foreground">{t("sanger.consensus.reverseComplemented")}</p>}
    </div>
  );
}

/** The warnings of a consensus or of a single trimmed read, in the preview and on the saved identification. */
export function ConsensusWarnings({ warnings }: { warnings: ConsensusPreview["warnings"] }) {
  const t = useT();
  return (
    <>
      {warnings.map((w) => (
        <p key={w.code} className="flex items-start gap-1.5 text-amber-700 dark:text-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t(...codedKey("sanger.warning", w))}
        </p>
      ))}
    </>
  );
}
