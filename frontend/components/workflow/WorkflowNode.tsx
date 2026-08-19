"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2,
  XCircle,
  FileInput,
  ScanSearch,
  CloudLightning,
  Gauge,
  Landmark,
  UserCheck,
  UserCog,
  Flag,
  Users,
  type LucideIcon,
} from "lucide-react";
import { getNodeVisual } from "@/lib/status";
import type { NodeStatus } from "@/types/workflow";

export interface WorkflowNodeData {
  label: string;
  status: NodeStatus;
  icon?: string;
  toolsCompleted?: number;
  toolsTotal?: number;
  executionMs?: number;
  confidence?: number;
  terminal?: boolean;
}

const ICONS: Record<string, LucideIcon> = {
  FileInput,
  ScanSearch,
  CloudLightning,
  Gauge,
  Landmark,
  UserCheck,
  UserCog,
  Flag,
  Users,
};

/** Short, executive-facing subtitle -- the "why is this running" line, per node id. */
const SUBTITLES: Record<string, string> = {
  submission_intake: "Validating proposal completeness",
  document_intelligence: "Cross-checking disclosures & reports",
  cat_exposure: "Assessing catastrophe exposure",
  risk_assessment: "Scoring hazard, claims history & premium",
  delegated_authority: "Checking underwriter authority limits",
  human_underwriter: "Underwriter review & judgment",
  senior_underwriter: "Senior-level authority review",
  decision: "Final decision & evidence assembly",
  human_review_hold: "Held pending manual review",
};

function NodeIcon({ name, size = 24, color }: { name?: string; size?: number; color: string }) {
  const Icon = (name && ICONS[name]) || FileInput;
  return <Icon size={size} color={color} strokeWidth={1.9} />;
}

function WorkflowNodeComponent({ id, data, selected }: NodeProps<WorkflowNodeData>) {
  const visual = getNodeVisual(id, data.status);
  const isRunning = data.status === "running";
  const isCompleted = data.status === "completed";
  const isFailed = data.status === "failed";
  const isWaiting = data.status === "waiting";

  // ~2.5x the original ~210x70 chip: 210 wide stays similar, height grows
  // significantly to fit icon + title + subtitle + status/metrics row.
  return (
    <div className="relative" style={{ width: 224 }}>
      {/*
        Four target + four source handles, one per side, each with an
        explicit id ("target-left", "source-right", etc). graph.ts's EDGES
        pick the pair that matches the two nodes' actual relative position
        (e.g. a node below reaching up into this one uses source-top /
        target-bottom) so the smoothstep path travels the short way between
        them instead of defaulting to left-in/right-out and looping back
        over whatever sits in between.
      */}
      <Handle id="target-left" type="target" position={Position.Left} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="target-top" type="target" position={Position.Top} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="target-right" type="target" position={Position.Right} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="target-bottom" type="target" position={Position.Bottom} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="source-left" type="source" position={Position.Left} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="source-top" type="source" position={Position.Top} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />

      <motion.div
        initial={false}
        animate={isCompleted ? { scale: [1, 1.045, 1] } : { scale: 1 }}
        transition={{ duration: 0.55, ease: "easeOut" }}
        className={[
          "relative flex flex-col gap-2.5 rounded-2xl border-2 px-4 py-3.5 text-left transition-shadow",
          isRunning ? "node-running" : "",
          isCompleted ? "node-completed-flash" : "",
          "hover:shadow-lg",
        ].join(" ")}
        style={{
          width: 224,
          minHeight: 128,
          background: "#ffffff",
          borderColor: isWaiting ? "var(--color-canvas-border)" : visual.border,
          boxShadow: isRunning
            ? undefined // handled by .node-running glow keyframe in globals.css
            : isFailed
            ? "0 0 0 1px var(--color-danger), 0 0 18px 4px rgba(255,84,112,0.28)"
            : isCompleted
            ? `0 0 0 1px ${visual.border}66, 0 8px 22px ${visual.border}22`
            : selected
            ? "0 0 0 2px var(--color-wire)"
            : "0 1px 3px rgba(15,21,36,0.08), 0 6px 18px rgba(15,21,36,0.06)",
        }}
      >
        {/* Icon + completion/failure marker */}
        <div className="flex items-center justify-between">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl"
            style={{ background: isWaiting ? "var(--color-waiting-soft, #eef0f4)" : visual.bg }}
          >
            <NodeIcon name={data.icon} color={isWaiting ? "var(--color-ink-faint)" : visual.fg} />
          </div>
          <AnimatePresence mode="wait">
            {isCompleted ? (
              <motion.div
                key="done"
                initial={{ scale: 0.4, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="node-checkmark-pop"
              >
                <CheckCircle2 size={22} color={visual.fg} strokeWidth={2.25} />
              </motion.div>
            ) : isFailed ? (
              <XCircle size={22} color="var(--color-danger)" strokeWidth={2.25} />
            ) : null}
          </AnimatePresence>
        </div>

        {/* Title + subtitle */}
        <div>
          <p className="text-[15px] font-semibold leading-snug text-[var(--color-canvas-ink)]">{data.label}</p>
          <p className="mt-0.5 text-[11.5px] leading-snug text-[var(--color-canvas-ink-muted)]">
            {SUBTITLES[id] ?? "\u00A0"}
          </p>
        </div>

        {/* Status badge + metrics */}
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
          <span
            className="rounded-[var(--radius-chip)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: visual.fg, background: isWaiting ? "var(--color-waiting-soft, #eef0f4)" : visual.bg }}
          >
            {visual.label}
          </span>
          {typeof data.executionMs === "number" && (
            <span className="font-mono-data text-[10.5px] text-[var(--color-canvas-ink-muted)]">
              {(data.executionMs / 1000).toFixed(1)}s
            </span>
          )}
          {typeof data.confidence === "number" && (
            <span className="font-mono-data text-[10.5px] text-[var(--color-canvas-ink-muted)]">
              {(data.confidence * 100).toFixed(0)}% conf.
            </span>
          )}
          {typeof data.toolsTotal === "number" && data.toolsTotal > 0 && (
            <span className="font-mono-data text-[10.5px] text-[var(--color-canvas-ink-muted)]">
              {data.toolsCompleted ?? 0}/{data.toolsTotal} tools
            </span>
          )}
        </div>
      </motion.div>

      <Handle id="source-right" type="source" position={Position.Right} className="!h-2 !w-2 !border-0" style={{ background: "var(--color-canvas-border)" }} />
    </div>
  );
}

export default memo(WorkflowNodeComponent);
