"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { motion } from "framer-motion";
import { STATUS_META } from "@/lib/status";
import type { NodeStatus } from "@/types/workflow";

export interface GateNodeData {
  label: string;
  status: NodeStatus;
  /** The route the gate actually took once resolved, e.g. "True", "No mismatch", "Approve". */
  resolvedRoute?: string;
}

/**
 * Routes come from the backend's real gate_decision event.route values,
 * which aren't a uniform yes/no vocabulary across all 10 gates (e.g.
 * Decision7's route is one of Approve/Decline/Escalate/Override, not
 * True/False) -- this is a best-effort classifier so every gate still
 * gets *some* green/orange signal once resolved, per the brief's "YES
 * green / NO orange" branch coloring, without overclaiming precision on
 * routes that aren't strictly binary.
 */
const POSITIVE_ROUTES = new Set([
  "true", "yes", "approve", "approved", "complete", "continue", "within", "clean",
]);

function branchColor(resolvedRoute: string | undefined): { fg: string; bg: string; border: string } | null {
  if (!resolvedRoute) return null;
  const isPositive = POSITIVE_ROUTES.has(resolvedRoute.trim().toLowerCase());
  return isPositive
    ? { fg: "var(--color-success)", bg: "var(--color-success-soft)", border: "var(--color-success)" }
    : { fg: "var(--color-alert)", bg: "var(--color-alert-soft)", border: "var(--color-alert)" };
}

function GateNodeComponent({ data, selected }: NodeProps<GateNodeData>) {
  const statusMeta = STATUS_META[data.status];
  const isRunning = data.status === "running";
  const isResolved = data.status === "completed" || data.status === "failed";
  const resolved = isResolved ? branchColor(data.resolvedRoute) : null;
  const meta = resolved ?? statusMeta;

  return (
    // Horizontal layout: connectors are Left (in) / Right (out), matching
    // every other node's orientation -- previously Top/Bottom, which
    // rendered gate edges at the wrong angle once the graph went horizontal.
    <div className="relative flex h-[104px] w-[104px] items-center justify-center">
      {/* Same per-side handle set as WorkflowNode -- see that file's comment. */}
      <Handle id="target-left" type="target" position={Position.Left} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="target-top" type="target" position={Position.Top} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="source-left" type="source" position={Position.Left} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />

      <motion.div
        initial={false}
        animate={
          isRunning
            ? { rotate: 45, boxShadow: [`0 0 0 0px ${meta.border}`, `0 0 0 8px ${meta.border}00`] }
            : { rotate: 45 }
        }
        transition={{ duration: 1.3, repeat: isRunning ? Infinity : 0, ease: "easeInOut" }}
        className="absolute h-[70px] w-[70px] rounded-xl border-2"
        style={{
          background: "#ffffff",
          borderColor: meta.border,
          boxShadow: selected
            ? "0 0 0 2px var(--color-wire)"
            : isRunning
            ? "var(--glow-blue, 0 0 0 1px rgba(76,141,255,0.5), 0 0 20px 6px rgba(76,141,255,0.28))"
            : isResolved
            ? `0 0 0 1px ${meta.border}55, 0 6px 18px ${meta.border}22`
            : "var(--shadow-node, 0 1px 3px rgba(15,21,36,0.08))",
        }}
      />

      <div className="relative z-10 flex flex-col items-center gap-1 px-3 text-center">
        <span className="text-[12px] font-semibold leading-tight text-[var(--color-canvas-ink)]">
          {data.label}
        </span>
        <span
          className="rounded-[var(--radius-chip)] px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
          style={{ color: meta.fg, background: meta.bg }}
        >
          {data.resolvedRoute ?? statusMeta.label}
        </span>
      </div>

      <Handle id="source-right" type="source" position={Position.Right} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
    </div>
  );
}

export default memo(GateNodeComponent);
