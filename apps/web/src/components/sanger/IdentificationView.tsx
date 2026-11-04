import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CancelJobButton } from "@/components/domain/JobControls";
import { JobStatusBadge } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtInt } from "@/lib/format";
import { jobError, messageText } from "@/lib/messages";
import { isActiveSearch, suspicionRequest, type IdentificationResults, type SearchJob, type Suspected, type TrimIn } from "@/lib/sanger";
import type { AnalysisJob } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { ConsensusWarnings, SuspectFields } from "./ConsensusBuilder";
import { ConsensusView } from "./ConsensusView";
import { Interpretation16sCard, OnlineBlast, OtherResults, RankedTable, SuspectedCard } from "./SangerResults";
import { SearchDialog } from "./SearchDialog";

/** One identification: what was searched (reads, trimming, consensus and conflicts), what you suspect, the searches
 * of each local source with their database and version, and the results: the ranking across sources, the 16S
 * reading and the comparison with the suspicion. Report in HTML (interface language), JSON or CSV. */
export function IdentificationView({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const language = useSettings((s) => s.language);
  const q = useQuery({
    queryKey: ["sanger", "identification", id],
    queryFn: () => api.sangerIdentification(id),
    refetchInterval: (query) => (query.state.data?.searches.some(isActiveSearch) ? 2000 : false),
  });
  const [searching, setSearching] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteSangerIdentification(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sanger"] });
      onDeleted();
    },
  });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const r = q.data;
  const ident = r.identification;
  const settings = ident.settings as { forward_trim?: TrimIn | null; reverse_trim?: TrimIn | null };
  const active = r.searches.some(isActiveSearch);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={ident.label}
          description={t("sanger.ident.summary", { mode: t(`sanger.mode.${ident.mode}` as const), n: fmtInt(ident.length), date: fmtDate(ident.created_at) })}
          action={
            <div className="flex flex-wrap gap-1.5">
              <a className={buttonClass("outline", "sm")} href={api.sangerConsensusFastaUrl(id)} download>
                <Download className="h-3.5 w-3.5" aria-hidden /> {t("sanger.ident.fasta")}
              </a>
              <a className={buttonClass("outline", "sm")} href={api.sangerReportUrl(id, "html", language)} download>
                <Download className="h-3.5 w-3.5" aria-hidden /> {t("sanger.ident.reportHtml")}
              </a>
              <a className={buttonClass("outline", "sm")} href={api.sangerReportUrl(id, "json", language)} download>
                {t("sanger.ident.reportJson")}
              </a>
              <a className={buttonClass("outline", "sm")} href={api.sangerReportUrl(id, "csv", language)} download>
                {t("sanger.ident.reportCsv")}
              </a>
              <Button size="sm" variant="ghost" disabled={active || remove.isPending} aria-label={t("sanger.ident.delete")} onClick={() => window.confirm(t("sanger.ident.confirmDelete", { label: ident.label })) && remove.mutate()}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          }
        />
        <CardBody className="space-y-3 text-sm">
          <ErrorNote error={remove.error} />
          <div className="flex flex-wrap gap-2 text-xs">
            {r.reads.forward && <Badge tone="blue">{t("sanger.ident.forwardRead", { name: r.reads.forward.name })}</Badge>}
            {r.reads.reverse && <Badge tone="blue">{t("sanger.ident.reverseRead", { name: r.reads.reverse.name })}</Badge>}
            {ident.unresolved > 0 && <Badge tone="danger">{t("sanger.ident.unresolved", { n: ident.unresolved })}</Badge>}
            <code className="text-[11px] text-muted-foreground" title={ident.sha256}>
              {t("sanger.ident.sha", { sha: ident.sha256.slice(0, 12) })}
            </code>
          </div>
          {ident.notes && <p className="whitespace-pre-wrap text-xs text-muted-foreground">{ident.notes}</p>}
          <SavedConsensusNotes consensus={r.consensus} />
          <details>
            <summary className="cursor-pointer text-xs font-medium">{t("sanger.ident.consensusDetails")}</summary>
            <div className="mt-2">
              <ConsensusView result={r.consensus} reads={r.reads} trims={{ forward: settings.forward_trim, reverse: settings.reverse_trim }} />
            </div>
          </details>
          <SuspicionEditor results={r} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-1">
              {t("sanger.searches.title")} <Explain id="sanger_sources" compact />
            </span>
          }
          description={t("sanger.searches.subtitle")}
          action={
            <Button size="sm" onClick={() => setSearching(true)} disabled={active}>
              {active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" aria-hidden />} {t("sanger.searches.start")}
            </Button>
          }
        />
        <CardBody className="pt-3">
          {r.searches.length === 0 ? <p className="text-sm text-muted-foreground">{t("sanger.searches.none")}</p> : <SearchList jobs={r.searches} />}
        </CardBody>
      </Card>

      <SuspectedCard comparison={r.suspected} />
      <Interpretation16sCard interpretation={r.interpretation_16s} notSearched={ident.searched.length > 0 && r.not_searched.includes("ncbi_16s")} />
      <RankedTable results={r} />
      <OtherResults results={r} />
      <OnlineBlast sequence={ident.sequence} />
      {searching && <SearchDialog identification={ident} onClose={() => setSearching(false)} onStarted={() => setSearching(false)} />}
    </div>
  );
}

/** The consensus warnings (single read, reads that look swapped, unresolved conflicts...) and the bases to review,
 * kept with the identification: they stay visible after it is saved, not only in the preview. */
function SavedConsensusNotes({ consensus }: { consensus: IdentificationResults["consensus"] }) {
  const t = useT();
  const mixed = consensus.mixed_peaks ?? {};
  const f = mixed.forward?.length;
  const rv = mixed.reverse?.length;
  if (consensus.warnings.length === 0 && !f && !rv && !consensus.reverse_complemented) return null;
  return (
    <div className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-2 text-xs">
      <p className="font-medium">{t("sanger.ident.warnings")}</p>
      <ConsensusWarnings warnings={consensus.warnings} />
      {consensus.status === "single"
        ? (f ?? rv ?? 0) > 0 && <p className="text-muted-foreground">{t("sanger.ident.reviewSingle", { n: f ?? rv ?? 0 })}</p>
        : (f || rv) && <p className="text-muted-foreground">{t("sanger.ident.reviewPair", { f: f ?? 0, r: rv ?? 0 })}</p>}
      {consensus.reverse_complemented && <p className="text-muted-foreground">{t("sanger.consensus.reverseComplemented")}</p>}
    </div>
  );
}

function SuspicionEditor({ results }: { results: IdentificationResults }) {
  const t = useT();
  const qc = useQueryClient();
  const ident = results.identification;
  const [kind, setKind] = useState<Suspected["kind"]>(ident.suspected?.kind ?? "gene");
  const [value, setValue] = useState(ident.suspected?.value ?? "");
  useEffect(() => {
    setKind(ident.suspected?.kind ?? "gene");
    setValue(ident.suspected?.value ?? "");
  }, [ident.id, ident.suspected?.kind, ident.suspected?.value]);
  const save = useMutation({
    mutationFn: () => api.updateSangerIdentification(ident.id, { suspected: suspicionRequest(kind, value) }),
    onSuccess: (data) => {
      qc.setQueryData(["sanger", "identification", ident.id], data);
      qc.invalidateQueries({ queryKey: ["sanger", ident.sample_id] });
    },
  });
  const changed = (suspicionRequest(kind, value)?.value ?? "") !== (ident.suspected?.value ?? "") || (value.trim() !== "" && kind !== ident.suspected?.kind);
  return (
    <fieldset className="space-y-2 rounded-lg border p-3">
      <legend className="flex items-center gap-1 px-1 text-xs font-semibold">
        {t("sanger.suspect.title")} <Explain id="sanger_suspected" compact />
      </legend>
      <p className="text-xs text-muted-foreground">{t("sanger.suspect.editHint")}</p>
      <SuspectFields kind={kind} setKind={setKind} value={value} setValue={setValue} />
      <ErrorNote error={save.error} />
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => save.mutate()} disabled={!changed || save.isPending}>
          {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" aria-hidden />} {t("sanger.suspect.save")}
        </Button>
      </div>
    </fieldset>
  );
}

function SearchList({ jobs }: { jobs: SearchJob[] }) {
  const t = useT();
  return (
    <ul className="space-y-1.5 text-xs">
      {jobs
        .slice()
        .reverse()
        .map((j) => {
          const asJob = { id: j.job_id, status: j.status, cancel_requested_at: null } as unknown as AnalysisJob;
          const warnings = ((j.details?.warnings ?? []) as { code: string; params: Record<string, string | number> }[]).filter((w) => w.code === "genomes_unannotated");
          return (
            <li key={j.job_id} className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2">
              <span className="font-medium">{t(`sanger.source.${j.source}` as const)}</span>
              <JobStatusBadge status={j.status} />
              <span className="text-muted-foreground">
                {j.tool} {j.tool_version ?? ""}
                {j.database_name && ` · ${j.database_name} ${j.database_version ?? ""}`}
                {j.genomes && ` · ${t("sanger.searches.genomes", { n: j.genomes.length })}`}
              </span>
              {j.rows != null && <span>{t("sanger.searches.rows", { n: j.rows })}</span>}
              <span className="ml-auto text-muted-foreground">{fmtDate(j.finished_at ?? j.created_at)}</span>
              <CancelJobButton job={asJob} />
              {j.status === "failed" && <p className="w-full text-danger">{jobError(t, { error_message: j.error_message, error_detail: j.error_detail, resources: null } as unknown as AnalysisJob)}</p>}
              {warnings.map((w) => (
                <p key={w.code} className="w-full text-amber-700 dark:text-warning">
                  {messageText(t, "sanger.warning", { code: w.code, params: w.params, text: w.code })}
                </p>
              ))}
            </li>
          );
        })}
    </ul>
  );
}
