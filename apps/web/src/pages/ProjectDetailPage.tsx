import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Pencil, Plus, Trash2, UploadCloud } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { BulkImportDialog } from "@/components/domain/BulkImportDialog";
import { ProjectFormDialog } from "@/components/domain/ProjectFormDialog";
import { SampleFormDialog } from "@/components/domain/SampleForm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { SamplesTable } from "./SamplesPage";

export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const t = useT();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [bulk, setBulk] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const samples = useQuery({ queryKey: ["samples", projectId], queryFn: () => api.samples(projectId) });

  const del = useMutation({
    mutationFn: () => api.deleteProject(projectId),
    onSuccess: () => {
      qc.invalidateQueries();
      navigate("/projects");
    },
  });

  if (project.isLoading) return <Skeleton className="h-40" />;
  if (project.error || !project.data) return <ErrorNote error={project.error ?? "Project not found"} />;
  const p = project.data;

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow={
          <Link to="/projects" className="hover:underline">
            {t("nav.projects")}
          </Link>
        }
        title={
          <span className="flex items-center gap-2">
            {p.name} {p.is_demo && <Badge tone="warning">DEMO</Badge>}
          </span>
        }
        subtitle={[p.researcher, p.institution, `Created ${fmtDate(p.created_at)}`].filter(Boolean).join(" · ")}
        actions={
          <>
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" /> Edit
            </Button>
            <Button variant="ghost" onClick={() => setConfirmDelete(true)} aria-label="Delete project">
              <Trash2 className="h-4 w-4" />
            </Button>
            <Button variant="outline" onClick={() => setBulk(true)}>
              <UploadCloud className="h-4 w-4" /> {t("bulk.button")}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> {t("samples.new")}
            </Button>
          </>
        }
      />
      {p.description && <p className="-mt-2 mb-6 max-w-3xl text-sm text-muted-foreground">{p.description}</p>}

      <Card>
        {samples.isLoading ? (
          <Skeleton className="m-5 h-24" />
        ) : samples.data?.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={<FlaskConical className="h-7 w-7" />} title={t("samples.empty")}>
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> {t("samples.new")}
              </Button>
            </EmptyState>
          </div>
        ) : (
          <SamplesTable samples={samples.data ?? []} showProject={false} />
        )}
      </Card>

      <ProjectFormDialog open={editing} onOpenChange={setEditing} project={p} />
      <SampleFormDialog open={creating} onOpenChange={setCreating} projectId={p.id} />
      <BulkImportDialog open={bulk} onOpenChange={setBulk} projectId={p.id} samples={samples.data ?? []} />
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete project?">
        <p className="text-sm text-muted-foreground">
          This removes the project, its {p.sample_count} sample(s) and their analysis records from ARVA. Raw files already stored on disk are
          not deleted (original data are never removed automatically).
        </p>
        <ErrorNote error={del.error} />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" disabled={del.isPending} onClick={() => del.mutate()}>
            Delete project
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
