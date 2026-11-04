import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, Dna, FileText, GitBranch, GitCompareArrows, Loader2, Map as MapIcon, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlignmentView } from "@/components/comparative/AlignmentView";
import { AniView } from "@/components/comparative/AniView";
import { GeneView } from "@/components/comparative/GeneView";
import { PangenomeDialog } from "@/components/comparative/PangenomeDialog";
import { PangenomeView } from "@/components/comparative/PangenomeView";
import { PhylogenyDialog } from "@/components/comparative/PhylogenyDialog";
import { GeneDialog, RegionDialog } from "@/components/comparative/RegionDialogs";
import { RegionView } from "@/components/comparative/RegionView";
import { AlignmentDialog, AniDialog } from "@/components/comparative/RunDialogs";
import { SetDialog } from "@/components/comparative/SetDialog";
import { TreeView } from "@/components/comparative/TreeView";
import { JobStatusBadge } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { assemblerText } from "@/lib/assembly";
import type { ComparisonResultRead, ComparisonSet, Warning } from "@/lib/comparative";
import type { RegionAnchorIn } from "@/lib/regions";
import { fmtBases, fmtDate } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { jobLabel } from "@/lib/results";
import type { JobStatus } from "@/lib/types";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";

/** Comparative genomics: saved comparison sets of assemblies from any project, their ANI matrices and whole-genome
 * alignments. */
export function ComparativePage() {
  const t = useT();
  const { setId } = useParams();
  const [creating, setCreating] = useState(false);
  const sets = useQuery({ queryKey: ["comparisons"], queryFn: () => api.comparisons() });
  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title={t("nav.comparative")}
        subtitle={t("comparative.subtitle")}
        actions={
          <>
            <Explain id="ani_matrix" />
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> {t("comparative.newSet")}
            </Button>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader title={t("comparative.sets")} description={t("comparative.setsHint")} />
          <CardBody className="space-y-1 pt-3">
            {sets.isLoading && <Skeleton className="h-24" />}
            <ErrorNote error={sets.error} />
            {sets.data?.length === 0 && <p className="text-xs text-muted-foreground">{t("comparative.noSets")}</p>}
            {sets.data?.map((s) => (
              <Link key={s.id} to={`/comparative/${s.id}`}
                className={`block rounded-lg border px-3 py-2 text-xs hover:bg-muted/50 ${s.id === setId ? "border-arva-teal bg-arva-teal/5" : ""}`}>
                <span className="block text-sm font-medium">{s.name}</span>
                <span className="text-muted-foreground">{t("comparative.setLine", { n: s.genomes, project: s.project_name ?? "" })}</span>
              </Link>
            ))}
          </CardBody>
        </Card>
        {setId ? (
          <SetDetail key={setId} setId={setId} />
        ) : (
          <EmptyState icon={<GitCompareArrows className="h-7 w-7" />} title={t("comparative.chooseSet")}>
            {t("comparative.chooseSetHint")}
          </EmptyState>
        )}
      </div>
      <SetDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function WarningList({ warnings }: { warnings: Warning[] }) {
  const t = useT();
  if (!warnings.length) return null;
  return (
    <ul className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
      {warnings.map((w, i) => (
        <li key={i} className="flex gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          {messageText(t, "comparative.warning", { code: w.code, params: w.params, text: w.code })}
        </li>
      ))}
    </ul>
  );
}

function SetDetail({ setId }: { setId: string }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"edit" | "ani" | "align" | "region" | "gene" | "pangenome" | "phylogeny" | null>(null);
  const [treeFamily, setTreeFamily] = useState<{ resultId: string; family: string } | null>(null);
  const [regionStart, setRegionStart] = useState<{ anchor: RegionAnchorIn; genomes: string[] } | null>(null);
  const view = useQuery({
    queryKey: ["comparison", setId],
    queryFn: () => api.comparison(setId),
    refetchInterval: (q) => ((q.state.data?.jobs ?? []).some((j) => j.status === "pending" || j.status === "running") ? 3000 : false),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const s = view.data;
  const resultId = selected ?? s?.results[0]?.id ?? null;
  const result = useQuery({ queryKey: ["comparisonResult", resultId], queryFn: () => api.comparisonResult(resultId!), enabled: Boolean(resultId) });
  const remove = useMutation({
    mutationFn: () => api.deleteComparison(setId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comparisons"] });
      navigate("/comparative");
    },
  });
  if (view.isLoading) return <Skeleton className="h-64" />;
  if (!s) return <ErrorNote error={view.error} />;
  return (
    <div className="min-w-0 space-y-6">
      <Card>
        <CardHeader title={s.name} description={s.description ?? t("comparative.setLine", { n: s.members.length, project: s.project_name ?? "" })} />
        <div className="flex flex-wrap gap-2 px-5 pt-3">
          <Button size="sm" onClick={() => setDialog("ani")}><Play className="h-3.5 w-3.5" /> {t("comparative.runAni")}</Button>
          <Button size="sm" onClick={() => setDialog("align")}><Play className="h-3.5 w-3.5" /> {t("comparative.runAlignment")}</Button>
          <Button size="sm" onClick={() => { setRegionStart(null); setDialog("region"); }}><MapIcon className="h-3.5 w-3.5" /> {t("region.open")}</Button>
          <Button size="sm" onClick={() => setDialog("gene")}><Dna className="h-3.5 w-3.5" /> {t("gene.open")}</Button>
          <Button size="sm" onClick={() => setDialog("pangenome")}><Boxes className="h-3.5 w-3.5" /> {t("pangenome.open")}</Button>
          <Button size="sm" onClick={() => { setTreeFamily(null); setDialog("phylogeny"); }}><GitBranch className="h-3.5 w-3.5" /> {t("phylo.open")}</Button>
          <Button size="sm" variant="outline" onClick={() => setDialog("edit")}><Pencil className="h-3.5 w-3.5" /> {t("comparative.editSet")}</Button>
          <a href={api.comparisonReportUrl(s.id, "html")} target="_blank" rel="noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium hover:bg-muted">
            <FileText className="h-3.5 w-3.5" /> {t("comparative.report")}
          </a>
          <Button size="sm" variant="ghost" onClick={() => window.confirm(t("comparative.deleteConfirm")) && remove.mutate()} aria-label={t("comparative.deleteConfirm")}>
            {remove.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
        <CardBody className="pt-3">
          <MembersTable set={s} />
          <Jobs set={s} />
        </CardBody>
      </Card>
      {s.results.length > 0 ? (
        <Card>
          <CardHeader title={t("comparative.results")} />
          <CardBody className="space-y-4 pt-3">
            <div className="flex flex-wrap gap-2">
              {s.results.map((r) => (
                <button key={r.id} onClick={() => setSelected(r.id)}
                  className={`rounded-lg border px-3 py-1.5 text-left text-xs ${r.id === resultId ? "border-arva-teal bg-arva-teal/5" : "hover:bg-muted/50"}`}>
                  <span className="block font-medium">{t(`comparative.analysis.${r.analysis}` as TranslationKey)} · {r.tool} {r.tool_version}</span>
                  <span className="text-muted-foreground">{fmtDate(r.created_at)} · {t("comparative.genomeCount", { n: r.genomes.length })}</span>
                </button>
              ))}
            </div>
            <ErrorNote error={result.error} />
            {result.isLoading && <Skeleton className="h-64" />}
            {result.data && (
              <div className="space-y-4">
                <WarningList warnings={result.data.warnings} />
                <ResultBody result={result.data} set={s} onNeighbourhood={(anchor, genomes) => { setRegionStart({ anchor, genomes }); setDialog("region"); }}
                  onGeneTree={(family) => { setTreeFamily({ resultId: result.data!.id, family }); setDialog("phylogeny"); }} />
              </div>
            )}
          </CardBody>
        </Card>
      ) : (
        <EmptyState icon={<GitCompareArrows className="h-7 w-7" />} title={t("comparative.noResults")}>{t("comparative.noResultsHint")}</EmptyState>
      )}
      <SetDialog open={dialog === "edit"} onOpenChange={(o) => setDialog(o ? "edit" : null)} existing={s} />
      <AniDialog open={dialog === "ani"} onOpenChange={(o) => setDialog(o ? "ani" : null)} set={s} />
      <AlignmentDialog open={dialog === "align"} onOpenChange={(o) => setDialog(o ? "align" : null)} set={s} />
      <RegionDialog open={dialog === "region"} onOpenChange={(o) => setDialog(o ? "region" : null)} set={s} initial={regionStart} />
      <GeneDialog open={dialog === "gene"} onOpenChange={(o) => setDialog(o ? "gene" : null)} set={s} />
      <PangenomeDialog open={dialog === "pangenome"} onOpenChange={(o) => setDialog(o ? "pangenome" : null)} set={s} />
      <PhylogenyDialog open={dialog === "phylogeny"} onOpenChange={(o) => setDialog(o ? "phylogeny" : null)} set={s} initialFamily={treeFamily} />
    </div>
  );
}

function ResultBody({ result, set, onNeighbourhood, onGeneTree }: {
  result: ComparisonResultRead; set: ComparisonSet; onNeighbourhood: (anchor: RegionAnchorIn, genomes: string[]) => void;
  onGeneTree: (family: string) => void;
}) {
  const t = useT();
  if (result.analysis === "ani") return <AniView result={result} />;
  if (result.analysis === "alignment") return <AlignmentView result={result} members={set.members} />;
  if (result.data_missing) return <p className="text-xs text-danger">{t("region.dataMissing")}</p>;
  if (result.analysis === "region") return <RegionView key={result.id} result={result} />;
  if (result.analysis === "pangenome") return <PangenomeView key={result.id} result={result} onNeighbourhood={onNeighbourhood} onGeneTree={onGeneTree} />;
  if (result.analysis === "phylogeny") return <TreeView key={result.id} result={result} set={set} />;
  return (
    <GeneView result={result} onNeighbourhood={(m, genomes) => onNeighbourhood(
      { assembly_id: m.assembly_id, contig: m.contig, start: m.start, end: m.end, strand: m.strand }, genomes)} />
  );
}

function MembersTable({ set }: { set: ComparisonSet }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            {["label", "sample", "project", "assembly", "length", "explorer"].map((k) => (
              <th key={k} className="px-2 py-1.5 font-medium">{t(`comparative.member.${k}` as TranslationKey)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {set.members.map((m) => (
            <tr key={m.assembly_id}>
              <td className="px-2 py-1.5 font-medium">{m.label}</td>
              <td className="px-2 py-1.5"><Link to={`/samples/${m.sample_id}`} className={LINK}>{m.sample_code}</Link></td>
              <td className="px-2 py-1.5">{m.project_name}</td>
              <td className="px-2 py-1.5">
                {assemblerText(t, m.assembler, m.assembler_version)} {m.kind === "polished" && <Badge tone="teal">{t("comparative.polished")}</Badge>}
                {!m.contigs_present && <Badge tone="danger">{t("comparative.contigsMissing")}</Badge>}
              </td>
              <td className="px-2 py-1.5 tabular-nums">{m.total_length ? fmtBases(m.total_length) : "—"}</td>
              <td className="px-2 py-1.5">
                {m.annotation_id ? <Link to={`/explorer/${m.annotation_id}`} className={LINK}>{t("comparative.openExplorer")}</Link>
                  : <span className="text-muted-foreground" title={t("comparative.noAnnotation")}>{t("comparative.notAnnotated")}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Jobs({ set }: { set: ComparisonSet }) {
  const t = useT();
  if (!set.jobs.length) return null;
  return (
    <ul className="mt-3 space-y-1 text-xs">
      {set.jobs.map((j) => (
        <li key={j.id} className="flex flex-wrap items-center gap-2">
          <JobStatusBadge status={j.status as JobStatus} />
          <span>{jobLabel(j.job_type, t)} · {j.tool_name} · {fmtDate(j.created_at)}</span>
          {j.error_message && (
            <span className="text-danger">
              {messageText(t, "job.error", { code: j.error_detail?.code ?? null, params: j.error_detail?.params ?? {}, text: j.error_message })}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
