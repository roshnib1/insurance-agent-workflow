"use client";

import { Radio, MousePointerClick } from "lucide-react";
import { STATUS_META } from "@/lib/status";
import { AgentDetailBody, type AgentDrawerDetail } from "./AgentDrawer";

/**
 * Replaces the old click-to-open drawer as the primary way to inspect a
 * node. This panel is always visible (right column, ~20% width) and always
 * shows *something*:
 *
 *  - Nothing run yet            -> idle placeholder
 *  - A run is in flight and the
 *    person hasn't clicked a
 *    node                       -> follows whichever node is currently active
 *  - The person clicked a node  -> pinned to that node, with a "Back to
 *                                   live" affordance to resume following
 */
export default function ActiveNodePanel({
  detail,
  isPinned,
  isRunning,
  onReturnToLive,
}: {
  detail: AgentDrawerDetail | null;
  /** true when `detail` reflects a manual click rather than the live active node */
  isPinned: boolean;
  isRunning: boolean;
  onReturnToLive: () => void;
}) {
  if (!detail) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <MousePointerClick className="h-5 w-5 text-[var(--color-ink-faint)]" strokeWidth={1.5} />
        <p className="text-[12.5px] text-[var(--color-ink-faint)]">
          {isRunning
            ? "Waiting for the first agent to start\u2026"
            : "Run a case to watch live agent execution here."}
        </p>
      </div>
    );
  }

  const meta = STATUS_META[detail.status];

  return (
    <div className="scrollbar-thin flex h-full flex-col overflow-y-auto">
      <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)]">Agent</p>
          <h3 className="text-[14px] font-semibold text-[var(--color-ink)]">{detail.agentName}</h3>
        </div>
        {isPinned ? (
          <button
            onClick={onReturnToLive}
            className="shrink-0 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10.5px] font-medium text-[var(--color-ink-muted)] transition hover:bg-[var(--color-surface-sunken)]"
          >
            Back to live
          </button>
        ) : detail.status === "running" ? (
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold"
            style={{ color: meta.fg, background: meta.bg }}
          >
            <Radio className="h-2.5 w-2.5" strokeWidth={2.5} />
            LIVE
          </span>
        ) : null}
      </div>
      <AgentDetailBody detail={detail} />
    </div>
  );
}
