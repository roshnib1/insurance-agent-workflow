"use client";

import { FileText, Loader2, Play } from "lucide-react";
import UploadPanel from "./UploadPanel";

export type WorkflowRunStatus = "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";

const RUN_STATUS_META: Record<WorkflowRunStatus, { label: string; fg: string; bg: string; dot: string }> = {
  IDLE: { label: "Idle", fg: "var(--color-ink-muted)", bg: "var(--color-surface-sunken)", dot: "var(--color-ink-faint)" },
  RUNNING: { label: "Running", fg: "var(--color-wire)", bg: "var(--color-wire-soft)", dot: "var(--color-wire)" },
  COMPLETED: { label: "Completed", fg: "var(--color-success)", bg: "var(--color-success-soft)", dot: "var(--color-success)" },
  FAILED: { label: "Failed", fg: "var(--color-danger)", bg: "var(--color-danger-soft)", dot: "var(--color-danger)" },
};

function formatElapsed(ms: number): string {
  const totalSeconds = ms / 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = (totalSeconds % 60).toFixed(1);
  return `${String(minutes).padStart(2, "0")}:${seconds.padStart(4, "0")}`;
}

export interface RunPanelProps {
  samples: string[];
  selectedSample: string | null;
  onSelectSample: (sample: string) => void;
  onUpload: (file: File) => void;
  onRun: () => void;
  status: WorkflowRunStatus;
  elapsedMs: number;
  canRun: boolean;
}

export default function RunPanel({
  samples,
  selectedSample,
  onSelectSample,
  onUpload,
  onRun,
  status,
  elapsedMs,
  canRun,
}: RunPanelProps) {
  const meta = RUN_STATUS_META[status];
  const isRunning = status === "RUNNING";

  return (
    // Sample list is the only part that scrolls (min-h-0 + overflow-y-auto on
    // its own wrapper below). Upload and the Run button are shrink-0 and sit
    // outside that scroll area, so they're always visible regardless of how
    // many sample cases there are -- no scrolling required to find them.
    <div className="flex h-full flex-col gap-4 px-4 py-4">
      {/* Sample case selector (scrolls independently) */}
      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
          Sample proposal
        </p>
        <div className="mt-2 flex flex-col gap-1.5">
          {samples.length === 0 && (
            <p className="text-[12.5px] text-[var(--color-ink-faint)]">No sample cases found.</p>
          )}
          {samples.map((sample) => {
            const active = selectedSample === sample;
            return (
              <button
                key={sample}
                onClick={() => onSelectSample(sample)}
                disabled={isRunning}
                className="flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-[12.5px] transition disabled:cursor-not-allowed disabled:opacity-60"
                style={{
                  borderColor: active ? "var(--color-wire)" : "var(--color-border)",
                  background: active ? "var(--color-wire-soft)" : "var(--color-surface)",
                  color: active ? "var(--color-wire)" : "var(--color-ink)",
                }}
              >
                <FileText className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                <span className="truncate">{sample}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Upload -- always visible, pinned below the scrollable sample list */}
      <div className="shrink-0">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
          Or upload a proposal
        </p>
        <div className="mt-2">
          <UploadPanel onUpload={onUpload} disabled={isRunning} />
        </div>
      </div>

      {/* Run control -- always visible, pinned to the bottom */}
      <div className="shrink-0 flex flex-col gap-3 border-t border-[var(--color-border)] pt-4">
        <button
          onClick={onRun}
          disabled={!canRun || isRunning}
          className="flex items-center justify-center gap-2 rounded-lg bg-[var(--color-wire)] px-4 py-2.5 text-[13px] font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRunning ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Play className="h-4 w-4" strokeWidth={2} />}
          {isRunning ? "Running workflow" : "Run workflow"}
        </button>

        <div className="flex items-center justify-between">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
            style={{ color: meta.fg, background: meta.bg }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.dot }} />
            {meta.label}
          </span>
          <span className="font-mono-data text-[12px] text-[var(--color-ink-muted)]">{formatElapsed(elapsedMs)}</span>
        </div>
      </div>
    </div>
  );
}
