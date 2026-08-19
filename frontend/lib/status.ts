import type { NodeStatus } from "@/types/workflow";

export const STATUS_META: Record<
  NodeStatus,
  { label: string; dot: string; fg: string; bg: string; border: string }
> = {
  waiting: {
    label: "Waiting",
    dot: "var(--color-ink-faint)",
    fg: "var(--color-ink-muted)",
    bg: "var(--color-surface-sunken)",
    border: "var(--color-border)",
  },
  running: {
    label: "Running",
    dot: "var(--color-wire)",
    fg: "var(--color-wire)",
    bg: "var(--color-wire-soft)",
    border: "var(--color-wire)",
  },
  completed: {
    label: "Completed",
    dot: "var(--color-success)",
    fg: "var(--color-success)",
    bg: "var(--color-success-soft)",
    border: "var(--color-success)",
  },
  failed: {
    label: "Failed",
    dot: "var(--color-danger)",
    fg: "var(--color-danger)",
    bg: "var(--color-danger-soft)",
    border: "var(--color-danger)",
  },
};

/**
 * Node-role color overrides, layered on top of STATUS_META.
 *
 * NodeStatus itself stays exactly as the backend's event vocabulary
 * defines it (started/completed/failed/gate_decision -> running/completed/
 * failed/waiting) -- this is a presentation-only concern: certain node ids
 * should read as a *different* color family for the same status, per the
 * brief's "Human Review: Orange Glow" / "Decision: Purple Glow" (waiting
 * and failed are unaffected -- gray and red already match the brief).
 */
const HUMAN_REVIEW_NODE_IDS = new Set(["human_underwriter", "human_review_hold", "senior_underwriter"]);
const DECISION_TERMINAL_NODE_ID = "decision";

export function getNodeVisual(
  nodeId: string,
  status: NodeStatus
): { label: string; fg: string; bg: string; border: string } {
  const base = STATUS_META[status];

  // Waiting/failed keep the standard gray/red treatment regardless of role.
  if (status === "waiting" || status === "failed") return base;

  if (HUMAN_REVIEW_NODE_IDS.has(nodeId)) {
    return { label: base.label, fg: "var(--color-alert)", bg: "var(--color-alert-soft)", border: "var(--color-alert)" };
  }
  if (nodeId === DECISION_TERMINAL_NODE_ID) {
    return { label: base.label, fg: "var(--color-decision)", bg: "var(--color-decision-soft)", border: "var(--color-decision)" };
  }
  return base;
}
