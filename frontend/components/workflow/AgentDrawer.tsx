"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, X } from "lucide-react";
import { STATUS_META } from "@/lib/status";
import { CALLBACKS_BY_NODE, TOOLS_BY_NODE } from "@/lib/graph";
import type { NodeStatus } from "@/types/workflow";

export interface AgentDrawerDetail {
  nodeId: string;
  agentName: string;
  status: NodeStatus;
  phase?: string;
  executionMs?: number;
  currentStep?: string;
  summary?: string;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: string;
  confidence?: number;
  businessPolicy?: string;
  nextAgent?: string;
  toolsCompleted?: string[];
}

function KeyValueBlock({ title, value }: { title: string; value?: Record<string, unknown> }) {
  if (!value || Object.keys(value).length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">{title}</p>
      <pre className="font-mono-data scrollbar-thin mt-1.5 max-h-40 overflow-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] p-3 text-[11.5px] leading-relaxed text-[var(--color-ink)]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/**
 * The actual node-detail content -- Agent Name/Phase/Status/Execution Time/
 * Confidence/Business Policy/Decision/Inputs/Outputs/Tools/Callbacks.
 *
 * Deliberately has no drawer/modal chrome of its own so it can be reused two
 * ways: as the persistent "Live Agent Details" panel (ActiveNodePanel.tsx,
 * the primary usage now) and inside the slide-over `AgentDrawer` below for
 * places that still want a modal (kept for backward compatibility, not used
 * on the main dashboard anymore).
 */
export function AgentDetailBody({ detail }: { detail: AgentDrawerDetail }) {
  const meta = STATUS_META[detail.status];
  const tools = TOOLS_BY_NODE[detail.nodeId] ?? [];
  const callbacks = CALLBACKS_BY_NODE[detail.nodeId] ?? [];

  return (
    <div className="flex flex-col gap-5 px-5 py-4">
      {/* Status / phase / timing / step */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
          style={{ color: meta.fg, background: meta.bg }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.dot }} />
          {meta.label}
        </span>
        {detail.phase && (
          <span className="font-mono-data rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] text-[var(--color-ink-muted)]">
            {detail.phase}
          </span>
        )}
        {typeof detail.executionMs === "number" && (
          <span className="font-mono-data rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] text-[var(--color-ink-muted)]">
            {(detail.executionMs / 1000).toFixed(2)}s
          </span>
        )}
        {detail.currentStep && (
          <span className="font-mono-data rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] text-[var(--color-ink-muted)]">
            {detail.currentStep}
          </span>
        )}
      </div>

      {/* Summary */}
      {detail.summary && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Summary</p>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink)]">{detail.summary}</p>
        </div>
      )}

      {/* Decision + Confidence */}
      {(detail.decision || typeof detail.confidence === "number") && (
        <div className="grid grid-cols-2 gap-3">
          {detail.decision && (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] px-3 py-2.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Decision</p>
              <p className="mt-0.5 text-[13px] font-medium text-[var(--color-ink)]">{detail.decision}</p>
            </div>
          )}
          {typeof detail.confidence === "number" && (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] px-3 py-2.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Confidence</p>
              <p className="font-mono-data mt-0.5 text-[13px] font-medium text-[var(--color-ink)]">
                {(detail.confidence * 100).toFixed(0)}%
              </p>
            </div>
          )}
        </div>
      )}

      {/* Business policy */}
      {detail.businessPolicy && (
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] px-3 py-2.5">
          <p className="text-[10.5px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Business policy</p>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-[var(--color-ink)]">{detail.businessPolicy}</p>
        </div>
      )}

      {/* Inputs / Outputs */}
      <KeyValueBlock title="Inputs" value={detail.inputs} />
      <KeyValueBlock title="Outputs" value={detail.outputs} />

      {/* Tools executed */}
      {tools.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Tools executed</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {tools.map((tool) => {
              const done = detail.toolsCompleted?.includes(tool) ?? detail.status === "completed";
              const active = detail.status === "running" && !done;
              return (
                <li key={tool} className="font-mono-data flex items-center gap-2 text-[12.5px]">
                  <span
                    className="flex h-4 w-4 items-center justify-center rounded-full text-[10px]"
                    style={{
                      color: done ? "var(--color-success)" : active ? "var(--color-wire)" : "var(--color-ink-faint)",
                      background: done
                        ? "var(--color-success-soft)"
                        : active
                        ? "var(--color-wire-soft)"
                        : "var(--color-surface-sunken)",
                    }}
                  >
                    {done ? "✓" : "·"}
                  </span>
                  <span className={done ? "text-[var(--color-ink)]" : "text-[var(--color-ink-faint)]"}>{tool}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Callback chain */}
      {callbacks.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Callback chain</p>
          <div className="font-mono-data mt-1.5 flex flex-col gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] p-3 text-[12px] text-[var(--color-ink-muted)]">
            <span className="text-[var(--color-ink)]">{detail.agentName}</span>
            {callbacks.map((cb) => (
              <span key={cb} className="pl-4">
                &#8595; {cb}
              </span>
            ))}
            {detail.nextAgent && <span className="pl-4">&#8595; {detail.nextAgent}</span>}
          </div>
        </div>
      )}

      {/* Next agent */}
      {detail.nextAgent && (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-[var(--color-border-strong)] px-3 py-2.5 text-[12.5px] text-[var(--color-ink-muted)]">
          <span>Next agent</span>
          <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} />
          <span className="font-medium text-[var(--color-ink)]">{detail.nextAgent}</span>
        </div>
      )}
    </div>
  );
}

/**
 * Slide-over modal variant. No longer used on the main dashboard (the
 * persistent ActiveNodePanel replaced it), kept available in case a modal
 * presentation is wanted elsewhere -- e.g. a smaller viewport.
 */
export default function AgentDrawer({
  detail,
  onClose,
}: {
  detail: AgentDrawerDetail | null;
  onClose: () => void;
}) {
  const open = detail !== null;

  return (
    <AnimatePresence>
      {open && detail && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/10"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="scrollbar-thin fixed right-0 top-0 z-50 flex h-full w-[400px] flex-col overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-surface)]"
            style={{ boxShadow: "var(--shadow-drawer)" }}
            initial={{ x: 400 }}
            animate={{ x: 0 }}
            exit={{ x: 400 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border)] px-5 py-4">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)]">Agent</p>
                <h3 className="text-[15px] font-semibold text-[var(--color-ink)]">{detail.agentName}</h3>
              </div>
              <button
                onClick={onClose}
                className="rounded-md p-1.5 text-[var(--color-ink-muted)] transition hover:bg-[var(--color-surface-sunken)]"
                aria-label="Close agent details"
              >
                <X className="h-4 w-4" strokeWidth={2} />
              </button>
            </div>
            <AgentDetailBody detail={detail} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
