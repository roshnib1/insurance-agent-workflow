"use client";

import { Loader2, Play } from "lucide-react";
import UploadPanel from "./UploadPanel";

export type WorkflowRunStatus =
  | "IDLE"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED";

const RUN_STATUS_META: Record<
  WorkflowRunStatus,
  { label: string; fg: string; bg: string; dot: string }
> = {
  IDLE: {
    label: "Idle",
    fg: "var(--color-ink-muted)",
    bg: "var(--color-surface-sunken)",
    dot: "var(--color-ink-faint)",
  },
  RUNNING: {
    label: "Running",
    fg: "var(--color-wire)",
    bg: "var(--color-wire-soft)",
    dot: "var(--color-wire)",
  },
  COMPLETED: {
    label: "Completed",
    fg: "var(--color-success)",
    bg: "var(--color-success-soft)",
    dot: "var(--color-success)",
  },
  FAILED: {
    label: "Failed",
    fg: "var(--color-danger)",
    bg: "var(--color-danger-soft)",
    dot: "var(--color-danger)",
  },
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
    <div className="flex h-full flex-col px-4 py-4">
      {/* SAMPLE PROPOSAL */}
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
          Sample Proposal
        </p>

        <select
          value={selectedSample ?? ""}
          onChange={(e) => onSelectSample(e.target.value)}
          disabled={isRunning}
          className="mt-3 h-11 w-full rounded-xl border px-4 text-sm font-medium outline-none"
          style={{
            background: "var(--color-surface)",
            borderColor: "var(--color-border)",
            color: "var(--color-ink)",
          }}
        >
          <option value="">Select a sample proposal</option>

          {samples.map((sample) => (
            <option key={sample} value={sample}>
              {sample.replace(/\.(html|htm|pdf)$/i, "")}
            </option>
          ))}
        </select>

        {samples.length === 0 && (
          <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
            No sample proposals available.
          </p>
        )}
      </div>

      {/* OR DIVIDER */}
      <div className="my-5 flex items-center">
        <div className="flex-1 border-t border-[var(--color-border)]"></div>
        <span className="mx-3 text-xs font-semibold text-[var(--color-ink-faint)]">
          OR
        </span>
        <div className="flex-1 border-t border-[var(--color-border)]"></div>
      </div>

      {/* UPLOAD */}
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
          Upload a Proposal
        </p>

        <div className="mt-3">
          <UploadPanel
            onUpload={onUpload}
            disabled={isRunning}
          />
        </div>
      </div>

      {/* PUSH BUTTON TO BOTTOM */}
      <div className="flex-1" />

      {/* RUN BUTTON */}
      <div className="border-t border-[var(--color-border)] pt-4">
        <button
          onClick={onRun}
          disabled={!canRun || isRunning}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-wire)] px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRunning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}

          {isRunning ? "Running workflow" : "Run workflow"}
        </button>

        <div className="mt-3 flex items-center justify-between">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
            style={{
              color: meta.fg,
              background: meta.bg,
            }}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                background: meta.dot,
              }}
            />
            {meta.label}
          </span>

          <span className="font-mono text-xs text-[var(--color-ink-muted)]">
            {formatElapsed(elapsedMs)}
          </span>
        </div>
      </div>
    </div>
  );
}