import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Biohazard, Microscope, Orbit, Plus, ScanSearch, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { FailedCard, RunningCard } from "@/components/assembly/RunMonitor";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { toolMessage } from "@/lib/messages";
import { AMR_JOB } from "@/lib/amr";
import { MLST_JOB } from "@/lib/mlst";
import { MOBILE_JOB, VIRULENCE_JOB } from "@/lib/mobile";
import { SPECIES_JOB } from "@/lib/species";
import type { AnalysisJobDetail } from "@/lib/types";
import { AmrCard } from "./AmrResult";
import { MlstCard } from "./MlstResult";
import { MobileContigCard, MobileRunCard } from "./MobileResult";
import { VirulenceCard } from "./Virulence";
import { SpeciesCard } from "./SpeciesResult";

const active = (jobs: AnalysisJobDetail[]) => jobs.filter((j) => j.status === "pending" || j.status === "running");
const stopped = (jobs: AnalysisJobDetail[]) => jobs.filter((j) => j.status === "failed" || j.status === "cancelled").slice(0, 3);

/** The sample's genomic analyses on its assemblies: species identification, MLST, AMR/virulence genes (AMRFinderPlus),
 * virulence factors from both sources side by side, and plasmids and mobile elements (the rest of Phase 5 is listed
 * as planned). */
export function GenomicTab({ sampleId, jobs, onMlst, onSpecies, onAmr, onMobile, onVirulence }: {
  sampleId: string;
  jobs: AnalysisJobDetail[];
  onMlst: () => void;
  onSpecies: () => void;
  onAmr: () => void;
  onMobile: () => void;
  onVirulence: () => void;
}) {
  const t = useT();
  const mlst = useTool("mlst");
  const amrTool = useTool("amrfinderplus");
  const amrRuns = jobs.filter((j) => j.job_type === AMR_JOB);
  const amr = useQuery({ queryKey: ["amr", sampleId], queryFn: () => api.amrRuns(sampleId) });
  const amrList = amr.data ?? [];
  const mobileRuns = jobs.filter((j) => j.job_type === MOBILE_JOB);
  const virulenceRuns = jobs.filter((j) => j.job_type === VIRULENCE_JOB);
  const mobile = useQuery({ queryKey: ["mobile", sampleId], queryFn: () => api.mobileSample(sampleId) });
  const virulence = useQuery({ queryKey: ["virulence", sampleId], queryFn: () => api.virulenceSample(sampleId) });
  const mlstRuns = jobs.filter((j) => j.job_type === MLST_JOB);
  const speciesRuns = jobs.filter((j) => j.job_type === SPECIES_JOB);
  const results = useQuery({ queryKey: ["mlst", sampleId], queryFn: () => api.mlstResults(sampleId) });
  const species = useQuery({ queryKey: ["species", sampleId], queryFn: () => api.speciesResults(sampleId) });
  const assemblies = useQuery({ queryKey: ["assemblies", sampleId], queryFn: () => api.assemblies(sampleId) });
  const byJob = new Map(jobs.map((j) => [j.id, j]));
  const list = results.data ?? [];
  const speciesList = species.data ?? [];
  const hasAssembly = (assemblies.data ?? []).length > 0;

  return (
    <div className="space-y-8">
      <section className="space-y-4" aria-labelledby="species-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-2xl space-y-1">
            <h3 id="species-section" className="text-sm font-semibold">
              {t("species.sectionTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("species.intro")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Explain id="ani" />
            <Button onClick={onSpecies} disabled={!hasAssembly}>
              <Plus className="h-4 w-4" /> {t("species.start")}
            </Button>
          </div>
        </div>
        {active(speciesRuns).map((j) => (
          <RunningCard key={j.id} job={j} names={new Map()} />
        ))}
        {speciesList.map((s) => (
          <SpeciesCard key={s.id} result={s} job={byJob.get(s.job_id)} />
        ))}
        <ErrorNote error={species.error} />
        {stopped(speciesRuns).map((j) => (
          <FailedCard key={j.id} job={j} />
        ))}
        {!active(speciesRuns).length && !speciesList.length && !stopped(speciesRuns).length && (
          <EmptyState icon={<ScanSearch className="h-7 w-7" />} title={t("species.empty")}>
            {hasAssembly ? t("species.emptyHint") : t("mlst.noAssembly")}
          </EmptyState>
        )}
      </section>

      <section className="space-y-4" aria-labelledby="mlst-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-2xl space-y-1">
            <h3 id="mlst-section" className="text-sm font-semibold">
              {t("mlst.sectionTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("mlst.intro")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Explain id="mlst" />
            <Button onClick={onMlst} disabled={!hasAssembly}>
              <Plus className="h-4 w-4" /> {t("mlst.start")}
            </Button>
          </div>
        </div>
        {mlst && mlst.status !== "available" && (
          <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
            <p>
              {t("mlst.toolMissing", { reason: mlst.status === "not_installed" && mlst.reason === "not_found" ? t("annotation.notInstalled") : toolMessage(t, mlst) || mlst.status })}{" "}
              <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
                {t("nav.tools")}
              </Link>
            </p>
          </div>
        )}
        {active(mlstRuns).map((j) => (
          <RunningCard key={j.id} job={j} names={new Map()} />
        ))}
        {list.map((m) => (
          <MlstCard key={m.id} result={m} job={byJob.get(m.job_id)} />
        ))}
        <ErrorNote error={results.error} />
        {stopped(mlstRuns).map((j) => (
          <FailedCard key={j.id} job={j} />
        ))}
        {!active(mlstRuns).length && !list.length && !stopped(mlstRuns).length && (
          <EmptyState icon={<Microscope className="h-7 w-7" />} title={t("mlst.empty")}>
            {hasAssembly ? t("mlst.emptyHint") : t("mlst.noAssembly")}
          </EmptyState>
        )}
      </section>
      <section className="space-y-4" aria-labelledby="amr-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-2xl space-y-1">
            <h3 id="amr-section" className="text-sm font-semibold">
              {t("amr.sectionTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("amr.intro")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Explain id="amr" />
            <Button onClick={onAmr} disabled={!hasAssembly}>
              <Plus className="h-4 w-4" /> {t("amr.start")}
            </Button>
          </div>
        </div>
        {amrTool && amrTool.status !== "available" && (
          <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
            <p>
              {t("amr.toolMissing", { reason: amrTool.status === "not_installed" && amrTool.reason === "not_found" ? t("annotation.notInstalled") : toolMessage(t, amrTool) || amrTool.status })}{" "}
              <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
                {t("nav.tools")}
              </Link>
            </p>
          </div>
        )}
        {active(amrRuns).map((j) => (
          <RunningCard key={j.id} job={j} names={new Map()} />
        ))}
        {amrList.map((r) => (
          <AmrCard key={r.job_id} run={r} job={byJob.get(r.job_id)} />
        ))}
        <ErrorNote error={amr.error} />
        {stopped(amrRuns).map((j) => (
          <FailedCard key={j.id} job={j} />
        ))}
        {!active(amrRuns).length && !amrList.length && !stopped(amrRuns).length && (
          <EmptyState icon={<ShieldAlert className="h-7 w-7" />} title={t("amr.empty")}>
            {hasAssembly ? t("amr.emptyHint") : t("mlst.noAssembly")}
          </EmptyState>
        )}
      </section>
      <section className="space-y-4" aria-labelledby="virulence-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-2xl space-y-1">
            <h3 id="virulence-section" className="text-sm font-semibold">
              {t("virulence.sectionTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("virulence.intro")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Explain id="vfdb" />
            <Button onClick={onVirulence} disabled={!hasAssembly}>
              <Plus className="h-4 w-4" /> {t("virulence.start")}
            </Button>
          </div>
        </div>
        {active(virulenceRuns).map((j) => (
          <RunningCard key={j.id} job={j} names={new Map()} />
        ))}
        {(virulence.data?.assemblies ?? []).map((v) => (
          <VirulenceCard key={v.assembly_id} view={v} runs={virulence.data?.runs ?? []} />
        ))}
        <ErrorNote error={virulence.error} />
        {stopped(virulenceRuns).map((j) => (
          <FailedCard key={j.id} job={j} />
        ))}
        {!active(virulenceRuns).length && !(virulence.data?.assemblies ?? []).length && !stopped(virulenceRuns).length && (
          <EmptyState icon={<Biohazard className="h-7 w-7" />} title={t("virulence.empty")}>
            {hasAssembly ? t("virulence.emptyHint") : t("mlst.noAssembly")}
          </EmptyState>
        )}
      </section>
      <section className="space-y-4" aria-labelledby="mobile-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-2xl space-y-1">
            <h3 id="mobile-section" className="text-sm font-semibold">
              {t("mobile.sectionTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("mobile.intro")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Explain id="plasmid" />
            <Button onClick={onMobile} disabled={!hasAssembly}>
              <Plus className="h-4 w-4" /> {t("mobile.start")}
            </Button>
          </div>
        </div>
        {active(mobileRuns).map((j) => (
          <RunningCard key={j.id} job={j} names={new Map()} />
        ))}
        {(mobile.data?.assemblies ?? []).map((a) => (
          <MobileContigCard key={a.assembly_id} table={a} />
        ))}
        {(mobile.data?.runs ?? []).map((r) => (
          <MobileRunCard key={r.job_id} run={r} job={byJob.get(r.job_id)} />
        ))}
        <ErrorNote error={mobile.error} />
        {stopped(mobileRuns).map((j) => (
          <FailedCard key={j.id} job={j} />
        ))}
        {!active(mobileRuns).length && !(mobile.data?.runs ?? []).length && !stopped(mobileRuns).length && (
          <EmptyState icon={<Orbit className="h-7 w-7" />} title={t("mobile.empty")}>
            {hasAssembly ? t("mobile.emptyHint") : t("mlst.noAssembly")}
          </EmptyState>
        )}
      </section>
      <p className="text-xs text-muted-foreground">{t("genomic.plannedNote")}</p>
    </div>
  );
}
