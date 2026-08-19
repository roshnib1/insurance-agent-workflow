"use client";

import { useEffect, useMemo, useRef } from "react";
import ReactFlow, {
  ReactFlowProvider,
  Background,
  Controls,
  useReactFlow,
  type Node,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";

import WorkflowNode, { type WorkflowNodeData } from "./WorkflowNode";
import DecisionNode, { type GateNodeData } from "./DecisionNode";
import WorkflowEdge, { type WorkflowEdgeData } from "./WorkflowEdge";
import { NODES, EDGES, TOOLS_BY_NODE } from "@/lib/graph";
import type { NodeStatus } from "@/types/workflow";

const nodeTypes = { agent: WorkflowNode, gate: DecisionNode, hold: WorkflowNode, terminal: WorkflowNode };
const edgeTypes = { workflow: WorkflowEdge };

/**
 * ReactFlow keeps whatever zoom/pan it last had when its container resizes --
 * it does NOT re-run fitView on its own. That's what made the diagram look
 * stranded in a sea of blank space whenever the panel was taller/wider than
 * the diagram needed (e.g. the default layout, or after toggling fullscreen):
 * the viewport grew but the drawing stayed at its old scale instead of
 * growing to fill the new space. Watching the wrapper element and re-running
 * fitView on every size change keeps the diagram sized to the space it
 * actually has, instead of the space it happened to have on first render.
 */
function FitViewOnResize({ containerRef }: { containerRef: React.RefObject<HTMLDivElement | null> }) {
  const { fitView } = useReactFlow();

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      // Let the CSS layout/transition settle before measuring.
      requestAnimationFrame(() => fitView({ padding: 0.18, duration: 200 }));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [containerRef, fitView]);

  return null;
}

export interface WorkflowCanvasProps {
  /** Current status for every node id; nodes not present default to "waiting". */
  nodeStatuses?: Record<string, NodeStatus>;
  /** Node currently emitting an event -- gets the pulsing ring + active edges. */
  activeNodeId?: string | null;
  /** Node currently open in the detail drawer -- gets the selection outline. */
  selectedNodeId?: string | null;
  /** Resolved branch text for gates that have already fired, e.g. "No mismatch". */
  resolvedRoutes?: Record<string, string>;
  /** Execution time (ms) per node, shown as a chip once known. */
  executionMs?: Record<string, number>;
  onSelectNode?: (nodeId: string) => void;
}

export default function WorkflowCanvas({
  nodeStatuses = {},
  activeNodeId = null,
  selectedNodeId = null,
  resolvedRoutes = {},
  executionMs = {},
  onSelectNode,
}: WorkflowCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const nodes: Node<WorkflowNodeData | GateNodeData>[] = useMemo(
    () =>
      NODES.map((def) => {
        const status = nodeStatuses[def.id] ?? "waiting";
        const totalTools = TOOLS_BY_NODE[def.id]?.length ?? 0;
        const base = {
          id: def.id,
          position: { x: def.x, y: def.y },
          selected: selectedNodeId === def.id,
          type: def.kind === "gate" ? "gate" : "agent",
        };
        if (def.kind === "gate") {
          return {
            ...base,
            data: { label: def.label, status, resolvedRoute: resolvedRoutes[def.id] } satisfies GateNodeData,
          };
        }
        return {
          ...base,
          data: {
            label: def.label,
            status,
            terminal: def.kind === "terminal",
            toolsTotal: totalTools,
            toolsCompleted: status === "completed" ? totalTools : 0,
            executionMs: executionMs[def.id],
          } satisfies WorkflowNodeData,
        };
      }),
    [nodeStatuses, selectedNodeId, resolvedRoutes, executionMs]
  );

  const edges: Edge<WorkflowEdgeData>[] = useMemo(
    () =>
      EDGES.map((def) => {
        const targetStatus = nodeStatuses[def.target] ?? "waiting";
        const resolved = targetStatus === "completed" || targetStatus === "running" || targetStatus === "failed";
        const active = activeNodeId === def.target;
        return {
          id: def.id,
          source: def.source,
          target: def.target,
          sourceHandle: def.sourceHandle,
          targetHandle: def.targetHandle,
          type: "workflow",
          label: def.label,
          data: { branch: def.branch, active, resolved } satisfies WorkflowEdgeData,
        };
      }),
    [nodeStatuses, activeNodeId]
  );

  return (
    <div ref={containerRef} className="h-full w-full">
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, node) => onSelectNode?.(node.id)}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.3}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--color-canvas-dot)" gap={22} size={1} />
          <Controls
            showInteractive={false}
            className="!rounded-lg !border !border-[var(--color-canvas-border)] !bg-[var(--color-canvas-raised)] [&_button]:!border-[var(--color-canvas-border)] [&_button]:!bg-transparent [&_button]:!fill-[var(--color-canvas-ink-muted)] [&_button:hover]:!bg-[var(--color-canvas-border)]"
          />
          <FitViewOnResize containerRef={containerRef} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}