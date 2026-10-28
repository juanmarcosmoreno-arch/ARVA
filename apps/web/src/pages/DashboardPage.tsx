import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  ChevronRight,
  Database,
  FileUp,
  FlaskConical,
  FolderKanban,
  HardDrive,
  Plus,
  Share2,
  Upload,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { JobStatusBadge, StatTile } from "@/components/domain/bits";
import { ProjectFormDialog } from "@/components/domain/ProjectFormDialog";
import { ALL_NAV_ITEMS } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtDate, fmtDuration, fmtInt } from "@/lib/format";
import { jobLabel } from "@/lib/results";

const MODULE_KEYS = ["import", "qc", "assembly", "annotation", "genomic", "comparative", "phylogeny", "pangenome", "workflows"];

export function DashboardPage() {
  const t = useT();
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 5000 });

  const modules = MODULE_KEYS.map((k) => ALL_NAV_ITEMS.find((i) => i.key === k)!);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title={t("dashboard.welcome")}
        subtitle={t("dashboard.subtitle")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> {t("dashboard.newProject")}
          </Button>
        }
      />
      <ErrorNote error={error} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {isLoading || !data ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)
        ) : (
          <>
            <StatTile label={t("dashboard.projects")} value={fmtInt(data.project_count)} icon={FolderKanban} />
            <StatTile label={t("dashboard.samples")} value={fmtInt(data.sample_count)} icon={FlaskConical} />
            <StatTile label={t("dashboard.files")} value={fmtInt(data.raw_file_count)} sub={fmtBytes(data.total_raw_bytes)} icon={FileUp} />
            <StatTile
              label={t("dashboard.active")}
              value={fmtInt(data.jobs_running)}
              sub={`${fmtInt(data.jobs_completed)} ${t("dashboard.completed").toLowerCase()} · ${fmtInt(data.jobs_failed)} ${t("dashboard.failed").toLowerCase()}`}
              icon={Activity}
            />
          </>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title={t("dashboard.recentActivity")} description="Latest analysis jobs with their recorded status" />
          <CardBody className="pt-3">
            {data && data.recent_jobs.length === 0 ? (
              <EmptyState icon={<Activity className="h-6 w-6" />} title={t("dashboard.noActivity")} />
            ) : (
              <ul className="divide-y">
                {data?.recent_jobs.map((j) => (
                  <li key={j.id}>
                    <Link
                      to={j.sample_id ? `/samples/${j.sample_id}?tab=history&job=${j.id}` : `/projects/${j.project_id}`}
                      className="flex items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-muted/60"
                    >
                      <BarChart3 className="h-4 w-4 shrink-0 text-arva-teal" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm">
                          {jobLabel(j.job_type, t)} · {j.tool_name} {j.tool_version}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {fmtDate(j.created_at)} · {fmtDuration(j.duration_seconds)}
                        </div>
                      </div>
                      <JobStatusBadge status={j.status} />
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title={t("dashboard.recentProjects")} action={<Link to="/projects" className="text-xs text-arva-royal hover:underline dark:text-arva-cyan">All</Link>} />
            <CardBody className="pt-3">
              {data && data.recent_projects.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("projects.empty")}</p>
              ) : (
                <ul className="space-y-1">
                  {data?.recent_projects.map((p) => (
                    <li key={p.id}>
                      <Link to={`/projects/${p.id}`} className="flex items-center justify-between rounded-lg px-2 py-2 hover:bg-muted/60">
                        <span className="min-w-0 truncate text-sm">{p.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">{p.sample_count} samples</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
          <StatTile label={t("dashboard.storage")} value={data ? fmtBytes(data.storage_used_bytes) : "—"} sub="Raw data, results, reports and logs" icon={HardDrive} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold">Modules</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {modules.map((m) => (
              <Link key={m.key} to={m.to} className="group">
                <Card className="flex h-full items-start gap-3 p-4 transition-colors group-hover:border-arva-teal/50">
                  <div className="rounded-lg bg-arva-royal/10 p-2 text-arva-royal dark:bg-arva-cyan/10 dark:text-arva-cyan">
                    <m.icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{t(m.label)}</span>
                      {m.plannedPhase !== undefined ? <Badge>Phase {m.plannedPhase}</Badge> : <Badge tone="success">Available</Badge>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {m.description ?? (m.key === "import" ? "Import FASTQ/FASTA with validation and checksums." : "Read statistics, FastQC, SeqKit cross-check and fastp/Filtlong filtering.")}
                    </p>
                  </div>
                  <ArrowRight className="mt-1 h-4 w-4 text-muted-foreground transition group-hover:translate-x-0.5" />
                </Card>
              </Link>
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <Card className="relative overflow-hidden bg-arva-navy p-6 text-white">
            <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-arva-royal/40 blur-2xl" aria-hidden />
            <div className="relative">
              <p className="text-xl font-medium leading-snug">Same tools.<br />A clearer path.</p>
              <div className="my-4 h-0.5 w-10 bg-arva-teal" />
              <p className="text-sm text-slate-300">Bring together the best bioinformatics tools in a single, transparent platform.</p>
            </div>
          </Card>
          <Card className="p-5">
            <h3 className="text-sm font-semibold">{t("dashboard.flow")}</h3>
            <div className="mb-4 mt-2 h-0.5 w-8 bg-arva-teal" />
            <ol className="grid grid-cols-4 gap-1 text-center text-[11px]">
              {[
                { icon: Upload, label: "Upload data", to: "/import" },
                { icon: Database, label: "Run analyses", to: "/qc" },
                { icon: BarChart3, label: "Explore results", to: "/samples" },
                { icon: Share2, label: "Report", to: "/reports" },
              ].map((s) => (
                <li key={s.label}>
                  <Link to={s.to} className="flex flex-col items-center gap-1.5 rounded-lg p-1 hover:bg-muted">
                    <s.icon className="h-6 w-6 text-arva-royal dark:text-arva-cyan" />
                    {s.label}
                  </Link>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>

      <ProjectFormDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
