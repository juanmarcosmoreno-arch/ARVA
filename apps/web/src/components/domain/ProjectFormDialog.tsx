import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import type { Project, ProjectInput } from "@/lib/types";

const empty: ProjectInput = { name: "", description: "", institution: "", researcher: "" };

export function ProjectFormDialog({
  open,
  onOpenChange,
  project,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  project?: Project;
}) {
  const t = useT();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState<ProjectInput>(empty);

  useEffect(() => {
    if (open) setForm(project ? { name: project.name, description: project.description ?? "", institution: project.institution ?? "", researcher: project.researcher ?? "" } : empty);
  }, [open, project]);

  const mutation = useMutation({
    mutationFn: (input: ProjectInput) => (project ? api.updateProject(project.id, input) : api.createProject(input)),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", p.id] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onOpenChange(false);
      if (!project) navigate(`/projects/${p.id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const clean = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, typeof v === "string" && v.trim() === "" && k !== "name" ? null : v]));
    mutation.mutate(clean as ProjectInput);
  };

  const set = (k: keyof ProjectInput) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={project ? "Edit project" : "New project"} description="A project groups samples, analyses and reports.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Project name *">
          <Input required autoFocus maxLength={255} value={form.name} onChange={set("name")} placeholder="e.g. S. aureus bovine mastitis 2024" />
        </Field>
        <Field label="Description">
          <Textarea value={form.description ?? ""} onChange={set("description")} placeholder="Aims, sampling design, notes…" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Researcher">
            <Input value={form.researcher ?? ""} onChange={set("researcher")} />
          </Field>
          <Field label="Institution">
            <Input value={form.institution ?? ""} onChange={set("institution")} />
          </Field>
        </div>
        <ErrorNote error={mutation.error} />
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={mutation.isPending || !form.name.trim()}>
            {project ? t("common.save") : t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
