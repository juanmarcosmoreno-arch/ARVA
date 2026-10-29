import { useQuery } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ProjectFormDialog } from "@/components/domain/ProjectFormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export function ProjectsPage() {
  const t = useT();
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  return (
    <div className="animate-fade-in">
      <PageHeader
        title={t("projects.title")}
        subtitle={t("projects.subtitle")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> {t("dashboard.newProject")}
          </Button>
        }
      />
      <ErrorNote error={error} />
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : data?.length === 0 ? (
        <EmptyState icon={<FolderKanban className="h-7 w-7" />} title={t("projects.empty")}>
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> {t("dashboard.newProject")}
          </Button>
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="group">
              <Card className="flex h-full flex-col p-5 transition-colors group-hover:border-arva-teal/50">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-medium leading-snug">{p.name}</h3>
                  {p.is_demo && <Badge tone="warning">{t("common.demo")}</Badge>}
                </div>
                <p className="mt-1 line-clamp-2 flex-1 text-sm text-muted-foreground">{p.description || t("projects.noDescription")}</p>
                <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    {t("dashboard.sampleCount", { count: p.sample_count })}
                    {p.institution && ` · ${p.institution}`}
                  </span>
                  <span>{fmtDate(p.updated_at)}</span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
      <ProjectFormDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
