"use client";

import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from "reactflow";

export interface WorkflowEdgeData {
  branch: "main" | "stop";
  /** true only for the instant an event is traveling this edge */
  active?: boolean;
  /** true once the target node has completed/started, i.e. this path was taken */
  resolved?: boolean;
}

export default function WorkflowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  label,
}: EdgeProps<WorkflowEdgeData>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 10,
  });

  const branch = data?.branch ?? "main";
  const color =
    branch === "stop"
      ? "var(--color-alert)"
      : data?.resolved
      ? "var(--color-success)"
      : "var(--color-canvas-border)";

  return (
    <>
      <BaseEdge
        path={path}
        style={{
          stroke: color,
          strokeWidth: data?.active ? 2.5 : 1.5,
          opacity: data?.resolved || data?.active ? 1 : 0.55,
          ...(data?.active
            ? {
                strokeDasharray: "6 6",
                animation: "edge-flow 0.7s linear infinite",
                filter: `drop-shadow(0 0 4px ${color})`,
              }
            : {}),
        }}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="font-mono-data pointer-events-none absolute rounded px-1.5 py-0.5 text-[9.5px] font-medium"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              background: "var(--color-canvas-raised)",
              color: branch === "stop" ? "var(--color-alert)" : "var(--color-canvas-ink-muted)",
              border: "1px solid var(--color-canvas-border)",
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
