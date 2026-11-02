import { Handle, Position, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Ban, Recycle } from "lucide-react";
import { type TranslationKey, useT } from "@/i18n";
import {
  PORT_COLORS,
  STATUS_COLOR,
  type Counts,
  type Definition,
  type NodeKind,
  type Problem,
  type ToolState,
  type WfEdge,
  type WfNode,
  ITEM_STATUSES,
  edgeId,
} from "@/lib/workflows";

export interface NodeData extends Record<string, unknown> {
  kind: NodeKind;
  params: Record<string, unknown>;
  label?: string | null;
  problems: Problem[];
  tools: ToolState[];
  progress?: (Counts & { total: number }) | null;
  reused?: number;
}

export type FlowNode = Node<NodeData, "arva">;

const ROW = 22;
const HEAD = 46;

/** One workflow node: its analysis, its tools, typed input ports on the left and output ports on the right
 * (coloured by data type), its problems and, on a run, how many of its items are in each status. */
export function ArvaNode({ id, data, selected }: NodeProps<FlowNode>) {
  const t = useT();
  const { kind } = data;
  const rows = Math.max(kind.inputs.length, kind.outputs.length, 1);
  const unavailable = data.tools.filter((x) => !x.available);
  return (
    <div className={`w-[210px] rounded-xl border bg-surface text-xs shadow-sm ${selected ? "ring-2 ring-arva-teal" : ""} ${data.problems.length ? "border-amber-500" : ""}`}
      style={{ minHeight: HEAD + rows * ROW + 26 }}>
      <div className="flex items-start justify-between gap-1 rounded-t-xl border-b bg-muted/40 px-2.5 py-1.5">
        <div className="min-w-0">
          <p className="truncate font-semibold">{data.label || t(`wf.kind.${kind.kind}` as TranslationKey)}</p>
          <p className="truncate font-mono text-[10px] text-muted-foreground">
            {id} · {t(`wf.scope.${kind.scope}` as TranslationKey)}
          </p>
        </div>
        {data.problems.length > 0 && <span title={t("wf.node.problems", { n: data.problems.length })}><AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600" /></span>}
        {unavailable.length > 0 && <span title={t("wf.node.unavailable")}><Ban className="h-3.5 w-3.5 shrink-0 text-danger" /></span>}
      </div>
      <div className="relative" style={{ height: rows * ROW + 4 }}>
        {kind.inputs.map((p, i) => (
          <div key={p.name} className="absolute left-2 flex items-center gap-1" style={{ top: 4 + i * ROW }}>
            <span className="text-[10px]" style={{ color: PORT_COLORS[p.accepts[0]] }}>
              {p.accepts.map((a) => t(`wf.port.${a}` as TranslationKey)).join(" / ")}
              {p.collection ? ` ${t("wf.port.many")}` : ""}
              {p.required ? "" : ` (${t("wf.port.optional")})`}
            </span>
          </div>
        ))}
        {kind.outputs.map((p, i) => (
          <div key={p.name} className="absolute right-2 text-right text-[10px]" style={{ top: 4 + i * ROW, color: PORT_COLORS[p.type] }}>
            {t(`wf.port.${p.type}` as TranslationKey)}
          </div>
        ))}
      </div>
      {kind.inputs.map((p, i) => (
        <Handle key={p.name} id={p.name} type="target" position={Position.Left}
          style={{ top: HEAD + 11 + i * ROW, background: PORT_COLORS[p.accepts[0]], width: 10, height: 10 }} />
      ))}
      {kind.outputs.map((p, i) => (
        <Handle key={p.name} id={p.name} type="source" position={Position.Right}
          style={{ top: HEAD + 11 + i * ROW, background: PORT_COLORS[p.type], width: 10, height: 10 }} />
      ))}
      <div className="border-t px-2.5 py-1 text-[10px] text-muted-foreground">
        {data.tools.length
          ? data.tools.map((x) => `${x.name} ${x.version ?? ""}`.trim()).join(" · ")
          : t(kind.source ? "wf.node.source" : kind.internal ? "wf.node.internal" : "wf.node.arvaOnly")}
      </div>
      {data.progress && <ProgressStrip counts={data.progress} reused={data.reused ?? 0} />}
    </div>
  );
}

function ProgressStrip({ counts, reused }: { counts: Counts & { total: number }; reused: number }) {
  const t = useT();
  return (
    <div className="space-y-0.5 border-t px-2.5 py-1.5">
      <div className="flex h-2 overflow-hidden rounded-full bg-muted">
        {ITEM_STATUSES.filter((s) => counts[s] > 0).map((s) => (
          <div key={s} style={{ width: `${(100 * counts[s]) / counts.total}%`, background: STATUS_COLOR[s] }} title={`${t(`wf.status.${s}` as TranslationKey)}: ${counts[s]}`} />
        ))}
      </div>
      <p className="flex items-center gap-1 text-[10px] text-muted-foreground">
        {t("wf.node.progress", { done: counts.completed, total: counts.total })}
        {counts.failed > 0 && <span className="text-danger">· {t("wf.node.failed", { n: counts.failed })}</span>}
        {reused > 0 && <span className="inline-flex items-center gap-0.5"><Recycle className="h-3 w-3" />{reused}</span>}
      </p>
    </div>
  );
}

export const NODE_TYPES = { arva: ArvaNode };

export function toFlow(
  definition: Definition,
  kinds: Map<string, NodeKind>,
  problems: Problem[],
  toolsOf: (n: WfNode, k: NodeKind) => ToolState[],
): { nodes: FlowNode[]; edges: Edge[] } {
  const nodes = definition.nodes
    .filter((n) => kinds.has(n.kind))
    .map<FlowNode>((n) => {
      const kind = kinds.get(n.kind)!;
      return {
        id: n.id,
        type: "arva",
        position: n.position ?? { x: 0, y: 0 },
        data: { kind, params: n.params, label: n.label, problems: problems.filter((p) => p.node === n.id), tools: toolsOf(n, kind) },
      };
    });
  return { nodes, edges: definition.edges.map(toFlowEdge(kinds, definition)) };
}

export function toFlowEdge(kinds: Map<string, NodeKind>, definition: Pick<Definition, "nodes">) {
  return (e: WfEdge): Edge => {
    const src = definition.nodes.find((n) => n.id === e.source);
    const type = src && kinds.get(src.kind)?.outputs.find((p) => p.name === e.source_port)?.type;
    return {
      id: edgeId(e),
      source: e.source,
      sourceHandle: e.source_port,
      target: e.target,
      targetHandle: e.target_port,
      style: { stroke: type ? PORT_COLORS[type] : undefined, strokeWidth: 2 },
    };
  };
}

export function fromFlow(nodes: FlowNode[], edges: Edge[]): Definition {
  return {
    format: "arva-workflow",
    format_version: 1,
    nodes: nodes.map((n) => ({ id: n.id, kind: n.data.kind.kind, label: n.data.label ?? null, params: n.data.params, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })),
    edges: edges.map((e) => ({ source: e.source, source_port: e.sourceHandle ?? "", target: e.target, target_port: e.targetHandle ?? "" })),
  };
}
