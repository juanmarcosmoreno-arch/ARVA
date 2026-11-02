import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Loader2, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonCandidate, ComparisonSet } from "@/lib/comparative";
import { fmtBases, fmtDate } from "@/lib/format";

const CHECK = "mt-0.5 h-3.5 w-3.5 accent-arva-teal";

/** Create or edit a comparison set: its project, name, the assemblies (from any project) in their order, and the
 * label each genome carries in plots and tables. */
export function SetDialog({ open, onOpenChange, existing }: { open: boolean; onOpenChange: (o: boolean) => void; existing?: ComparisonSet }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const candidates = useQuery({ queryKey: ["comparisonCandidates"], queryFn: api.comparisonCandidates, enabled: open });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.projects(), enabled: open });
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [order, setOrder] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (!open) return;
    setProjectId(existing?.project_id ?? "");
    setName(existing?.name ?? "");
    setDescription(existing?.description ?? "");
    setOrder(existing?.members.map((m) => m.assembly_id) ?? []);
    setLabels(Object.fromEntries((existing?.members ?? []).map((m) => [m.assembly_id, m.label])));
    setFilter("");
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const byId = useMemo(() => new Map((candidates.data ?? []).map((c) => [c.assembly_id, c])), [candidates.data]);
  const home = projectId || (order.length ? byId.get(order[0])?.project_id ?? "" : "");
  const shown = (candidates.data ?? []).filter((c) => {
    const q = filter.trim().toLowerCase();
    return !q || [c.sample_code, c.project_name, c.assembler].some((v) => (v ?? "").toLowerCase().includes(q));
  });
  const toggle = (id: string) => setOrder((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]));
  const move = (i: number, d: -1 | 1) =>
    setOrder((o) => {
      const n = [...o];
      [n[i], n[i + d]] = [n[i + d], n[i]];
      return n;
    });
  const save = useMutation({
    mutationFn: () => {
      const body = { project_id: home, name, description: description.trim() || null, assembly_ids: order,
        labels: Object.fromEntries(order.filter((id) => labels[id]?.trim()).map((id) => [id, labels[id].trim()])) };
      return existing ? api.updateComparison(existing.id, body) : api.createComparison(body);
    },
    onSuccess: (s) => {
      queryClient.invalidateQueries({ queryKey: ["comparisons"] });
      queryClient.setQueryData(["comparison", s.id], s);
      onOpenChange(false);
      navigate(`/comparative/${s.id}`);
    },
  });
  const valid = name.trim() && home && order.length >= 2;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={existing ? t("comparative.editSet") : t("comparative.newSet")}
      description={t("comparative.setDialogText")} className="max-w-4xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("comparative.setName")}>
            <Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t("comparative.homeProject")} hint={t("comparative.homeProjectHint")}>
            <Select value={home} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">{t("comparative.chooseProject")}</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={t("comparative.setDescription")}>
          <Textarea rows={2} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("comparative.available", { n: candidates.data?.length ?? 0 })}</h4>
            <Input placeholder={t("comparative.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} />
            <ErrorNote error={candidates.error} />
            <div className="max-h-72 overflow-y-auto rounded-lg border">
              {shown.map((c) => (
                <label key={c.assembly_id} className="flex cursor-pointer items-start gap-2 border-b px-2 py-1.5 text-xs last:border-0 hover:bg-muted/50">
                  <input type="checkbox" className={CHECK} checked={order.includes(c.assembly_id)} onChange={() => toggle(c.assembly_id)} />
                  <CandidateLine c={c} />
                </label>
              ))}
              {candidates.data && shown.length === 0 && <p className="p-3 text-xs text-muted-foreground">{t("comparative.noCandidates")}</p>}
            </div>
          </section>
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("comparative.selected", { n: order.length })}</h4>
            <p className="text-xs text-muted-foreground">{t("comparative.orderHint")}</p>
            <ol className="max-h-80 space-y-1 overflow-y-auto">
              {order.map((id, i) => {
                const c = byId.get(id);
                return (
                  <li key={id} className="flex items-center gap-1.5 rounded-lg border px-2 py-1">
                    <span className="w-5 text-right text-xs tabular-nums text-muted-foreground">{i + 1}</span>
                    <Input className="h-7 flex-1 text-xs" aria-label={t("comparative.label")} maxLength={100}
                      placeholder={c ? `${c.sample_code ?? ""} (${c.assembler})` : id.slice(0, 8)}
                      value={labels[id] ?? ""} onChange={(e) => setLabels((l) => ({ ...l, [id]: e.target.value }))} />
                    <button className="rounded p-1 hover:bg-muted disabled:opacity-30" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("comparative.moveUp")}>
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button className="rounded p-1 hover:bg-muted disabled:opacity-30" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label={t("comparative.moveDown")}>
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                    <button className="rounded p-1 hover:bg-muted" onClick={() => toggle(id)} aria-label={t("comparative.remove")}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        </div>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!valid || save.isPending}>
            {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {t("comparative.saveSet")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function CandidateLine({ c }: { c: ComparisonCandidate }) {
  const t = useT();
  return (
    <span className="min-w-0">
      <span className="font-medium">{c.sample_code}</span> <span className="text-muted-foreground">· {c.project_name}</span>{" "}
      {c.kind === "polished" && <Badge tone="teal">{t("comparative.polished")}</Badge>}
      <span className="block text-muted-foreground">
        {c.assembler} {c.assembler_version} · {c.total_length ? fmtBases(c.total_length) : "—"} · {t("comparative.contigCount", { n: c.contigs ?? 0 })} · {fmtDate(c.created_at)}
      </span>
    </span>
  );
}
