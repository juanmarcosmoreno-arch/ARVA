import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, Copy, Download, Loader2, Play, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { resolveDark, useSettings } from "@/store/settings";
import {
  connectionProblem,
  edgeId,
  newNodeId,
  nodeTools,
  type Catalogue,
  type Definition,
  type NodeKind,
  type Problem,
  type WfEdge,
  type WorkflowRead,
} from "@/lib/workflows";
import { NODE_TYPES, fromFlow, toFlow, toFlowEdge, type FlowNode } from "./WorkflowCanvas";
import { ParamPanel } from "./ParamPanel";
import { RunDialog } from "./RunDialog";

const CATEGORIES = ["source", "reads", "assembly", "annotation", "characterisation", "comparative", "phylogeny"];

export function problemText(t: ReturnType<typeof useT>, p: Problem): string {
  return messageText(t, "api.error", { code: p.code, params: p.params, text: p.code });
}

/** The Workflow Builder: drag analyses from the palette, connect typed ports (incompatible connections are refused
 * with the reason), set each node's parameters, and save the graph as a new version. */
export function WorkflowEditor({ workflow, catalogue, version }: { workflow: WorkflowRead; catalogue: Catalogue; version?: number }) {
  return (
    <ReactFlowProvider>
      <Editor workflow={workflow} catalogue={catalogue} version={version} />
    </ReactFlowProvider>
  );
}

function Editor({ workflow, catalogue, version }: { workflow: WorkflowRead; catalogue: Catalogue; version?: number }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const theme = useSettings((s) => s.theme);
  const kinds = useMemo(() => new Map(catalogue.kinds.map((k) => [k.kind, k])), [catalogue]);
  const shown = (version ? workflow.selected : workflow.latest) ?? workflow.latest;
  const readOnly = Boolean(version && workflow.latest && version !== workflow.latest.version);
  const initial = useMemo(() => toFlow(shown!.definition, kinds, workflow.problems, (n, k) => nodeTools(k, n.params)), [shown, kinds, workflow.problems]);
  const [nodes, setNodes] = useState<FlowNode[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [selected, setSelected] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<TranslationKey | null>(null);
  const [note, setNote] = useState("");
  const [name, setName] = useState(workflow.name);
  const [running, setRunning] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const flow = useReactFlow();
  useEffect(() => {
    setNodes(initial.nodes);
    setEdges(initial.edges);
  }, [initial]);

  const definition = useMemo(() => fromFlow(nodes, edges), [nodes, edges]);
  const key = JSON.stringify({ n: definition.nodes.map((n) => [n.id, n.kind, n.params]), e: definition.edges });
  const check = useQuery({ queryKey: ["wfValidate", key], queryFn: () => api.validateWorkflow(definition), retry: false, staleTime: 60_000 });
  const problems = useMemo(() => [...(check.data?.problems ?? []), ...(check.data?.unavailable ?? [])], [check.data]);
  useEffect(() => {
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, problems: problems.filter((p) => p.node === n.id), tools: nodeTools(n.data.kind, n.data.params) } })));
  }, [problems]);

  const wfEdges = (es: Edge[]): WfEdge[] => es.map((e) => ({ source: e.source, source_port: e.sourceHandle ?? "", target: e.target, target_port: e.targetHandle ?? "" }));
  const asEdge = (c: Connection | Edge): WfEdge => ({ source: c.source, source_port: c.sourceHandle ?? "", target: c.target, target_port: c.targetHandle ?? "" });
  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      const why = connectionProblem(kinds, nodes.map((n) => ({ id: n.id, kind: n.data.kind.kind })), wfEdges(edges), asEdge(c));
      if (why !== refusal) setRefusal(why);
      return why === null;
    },
    [kinds, nodes, edges, refusal],
  );
  const onConnect = useCallback(
    (c: Connection) => {
      if (readOnly) return;
      const e = asEdge(c);
      setEdges((es) => [...es, toFlowEdge(kinds, fromFlow(nodes, es))(e)]);
      setRefusal(null);
    },
    [kinds, nodes, readOnly],
  );
  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    setNodes((ns) => applyNodeChanges(readOnly ? changes.filter((c) => c.type !== "remove") : changes, ns));
  }, [readOnly]);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    if (!readOnly) setEdges((es) => applyEdgeChanges(changes, es));
  }, [readOnly]);
  const onNodesDelete = useCallback((deleted: FlowNode[]) => {
    const gone = new Set(deleted.map((n) => n.id));
    setEdges((es) => es.filter((e) => !gone.has(e.source) && !gone.has(e.target)));
    if (selected && gone.has(selected)) setSelected(null);
  }, [selected]);

  const addNode = (kind: NodeKind, position: { x: number; y: number }) => {
    if (readOnly) return;
    setNodes((ns) => {
      const id = newNodeId(kind.kind, ns);
      setSelected(id);
      return [...ns, { id, type: "arva", position, data: { kind, params: kind.defaults, problems: [], tools: nodeTools(kind, kind.defaults) } }];
    });
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const kind = kinds.get(e.dataTransfer.getData("application/arva-node"));
    if (kind) addNode(kind, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  const save = useMutation({
    mutationFn: () => api.saveWorkflowVersion(workflow.id, { definition, note: note || null, name }),
    onSuccess: (wf) => {
      queryClient.setQueryData(["workflow", workflow.id, undefined], wf);
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      setNote("");
      if (version) navigate(`/workflows/${workflow.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteWorkflow(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      navigate("/workflows");
    },
  });
  const node = nodes.find((n) => n.id === selected);
  const dirty = JSON.stringify(definition) !== JSON.stringify(fromFlow(initial.nodes, initial.edges)) || name !== workflow.name;
  const blocking = problems.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("wf.name")} className="w-72">
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={readOnly} />
        </Field>
        <Field label={t("wf.version")} className="w-56">
          <Select value={String(version ?? workflow.latest?.version ?? "")}
            onChange={(e) => navigate(Number(e.target.value) === workflow.latest?.version ? `/workflows/${workflow.id}` : `/workflows/${workflow.id}?version=${e.target.value}`)}>
            {[...workflow.versions].reverse().map((v) => (
              <option key={v.version} value={v.version}>{t("wf.versionLine", { v: v.version, date: fmtDate(v.created_at) })}</option>
            ))}
          </Select>
        </Field>
        {!readOnly && (
          <Field label={t("wf.note")} className="min-w-[200px] flex-1">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("wf.notePlaceholder")} />
          </Field>
        )}
        <div className="flex flex-wrap gap-2">
          {!readOnly && (
            <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} {t("wf.saveVersion")}
            </Button>
          )}
          {readOnly && (
            <Button onClick={() => save.mutate()} disabled={save.isPending} variant="outline">
              <Save className="h-4 w-4" /> {t("wf.restoreVersion")}
            </Button>
          )}
          <Button variant="outline" onClick={() => setDuplicating(true)}><Copy className="h-4 w-4" /> {t("wf.duplicate")}</Button>
          <a href={api.workflowExportUrl(workflow.id, version)} download>
            <Button variant="outline"><Download className="h-4 w-4" /> {t("wf.exportJson")}</Button>
          </a>
          <Button onClick={() => setRunning(true)} disabled={dirty || blocking} title={dirty ? t("wf.saveFirst") : blocking ? t("wf.fixFirst") : undefined}>
            <Play className="h-4 w-4" /> {t("wf.runAction")}
          </Button>
          <Button variant="ghost" onClick={() => window.confirm(t("wf.deleteConfirm")) && remove.mutate()} aria-label={t("wf.delete")}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <ErrorNote error={save.error ?? remove.error} />
      {readOnly && <p className="rounded-lg border border-amber-400 bg-warning/10 px-3 py-2 text-xs">{t("wf.oldVersion", { v: version ?? 0 })}</p>}
      <div className="grid gap-4 lg:grid-cols-[200px_1fr]">
        <Card className="h-fit">
          <CardHeader title={t("wf.palette")} description={t("wf.paletteHint")} />
          <CardBody className="max-h-[640px] space-y-3 overflow-y-auto pt-3">
            {CATEGORIES.map((c) => (
              <div key={c}>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t(`wf.category.${c}` as TranslationKey)}</p>
                <div className="space-y-1">
                  {catalogue.kinds.filter((k) => k.category === c).map((k) => {
                    const groups = Object.values(k.tools).filter((ts) => ts.length > 0);
                    const unavailable = groups.length > 0 && groups.every((ts) => ts.some((x) => !x.available));
                    return (
                      <div key={k.kind} draggable={!readOnly} onDragStart={(e) => e.dataTransfer.setData("application/arva-node", k.kind)}
                        onDoubleClick={() => addNode(k, { x: 80, y: 80 })}
                        className="cursor-grab rounded-md border px-2 py-1 text-xs hover:bg-muted/50" title={t(`wf.kindHint.${k.kind}` as TranslationKey)}>
                        <span className="font-medium">{t(`wf.kind.${k.kind}` as TranslationKey)}</span>
                        {unavailable && <Badge tone="danger" className="ml-1">{t("wf.unavailableShort")}</Badge>}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
        <div className="space-y-2">
          <div ref={wrapper} className="relative h-[680px] rounded-xl border bg-surface" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
            <ReactFlow<FlowNode>
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodesDelete={onNodesDelete}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onConnectEnd={() => undefined}
              onNodeClick={(_, n) => setSelected(n.id)}
              onPaneClick={() => setSelected(null)}
              nodesConnectable={!readOnly}
              deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
              colorMode={resolveDark(theme) ? "dark" : "light"}
              fitView
              fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={16} />
              <Controls />
              <MiniMap pannable zoomable style={{ width: 150, height: 90 }} position="bottom-left" className="!left-12" />
            </ReactFlow>
            {node && (
              <Card className="absolute right-3 top-3 z-10 max-h-[654px] w-[330px] overflow-y-auto shadow-lg">
                <CardHeader title={t(`wf.kind.${node.data.kind.kind}` as TranslationKey)} description={t(`wf.kindHint.${node.data.kind.kind}` as TranslationKey)}
                  action={<Button size="sm" variant="ghost" onClick={() => setSelected(null)} aria-label={t("common.close")}><X className="h-4 w-4" /></Button>} />
                <CardBody className="space-y-3 pt-3">
                  <Field label={t("wf.nodeLabel")}>
                    <Input className="h-8 text-xs" value={node.data.label ?? ""} disabled={readOnly}
                      onChange={(e) => setNodes((ns) => ns.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, label: e.target.value || null } } : n)))} />
                  </Field>
                  <ParamPanel kind={node.data.kind} params={node.data.params} problems={node.data.problems} readOnly={readOnly}
                    onChange={(params) => setNodes((ns) => ns.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, params, tools: nodeTools(n.data.kind, params) } } : n)))} />
                </CardBody>
              </Card>
            )}
          </div>
          {!node && <p className="text-xs text-muted-foreground">{t("wf.selectNode")}</p>}
          {refusal && (
            <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-warning" role="status">
              <AlertTriangle className="h-3.5 w-3.5" /> {t("wf.connect.refused", { reason: t(refusal) })}
            </p>
          )}
          <ProblemList problems={problems} pending={check.isFetching} onSelect={setSelected} />
        </div>
      </div>
      <DuplicateDialog open={duplicating} onOpenChange={setDuplicating} workflow={workflow} version={version} />
      {running && <RunDialog open={running} onOpenChange={setRunning} workflow={workflow} />}
    </div>
  );
}

function ProblemList({ problems, pending, onSelect }: { problems: Problem[]; pending: boolean; onSelect: (id: string) => void }) {
  const t = useT();
  if (!problems.length) return <p className="text-xs text-success">{pending ? t("wf.checking") : t("wf.noProblems")}</p>;
  return (
    <ul className="space-y-0.5 rounded-lg border border-amber-400/60 bg-warning/5 p-2 text-xs">
      {problems.map((p, i) => (
        <li key={i} className="flex gap-2">
          {p.node && <button type="button" className="font-mono text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => onSelect(p.node!)}>{p.node}</button>}
          <span>{problemText(t, p)}</span>
        </li>
      ))}
    </ul>
  );
}

function DuplicateDialog({ open, onOpenChange, workflow, version }: { open: boolean; onOpenChange: (o: boolean) => void; workflow: WorkflowRead; version?: number }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  useEffect(() => {
    if (open) setName(t("wf.copyName", { name: workflow.name }));
  }, [open, workflow.name, t]);
  const dup = useMutation({
    mutationFn: () => api.duplicateWorkflow(workflow.id, { name, version: version ?? null }),
    onSuccess: (wf) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      onOpenChange(false);
      navigate(`/workflows/${wf.id}`);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("wf.duplicate")} description={t("wf.duplicateHint")}>
      <div className="space-y-3">
        <Field label={t("wf.name")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <ErrorNote error={dup.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => dup.mutate()} disabled={!name.trim() || dup.isPending}><Copy className="h-4 w-4" /> {t("wf.duplicate")}</Button>
        </div>
      </div>
    </Dialog>
  );
}

export function useKinds(catalogue: Catalogue | undefined) {
  return useMemo(() => new Map((catalogue?.kinds ?? []).map((k) => [k.kind, k])), [catalogue]);
}

export function definitionEdges(d: Definition) {
  return d.edges.map(edgeId);
}
