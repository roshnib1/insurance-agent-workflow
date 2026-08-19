"use client";

import { useEffect, useRef } from "react";
import { Radio } from "lucide-react";
import { STATUS_META } from "@/lib/status";
import type { NodeStatus, WorkflowEvent } from "@/types/workflow";

function eventColor(event: WorkflowEvent): string {
  if (event.event === "failed") return "var(--color-danger)";
  if (event.event === "gate_decision") return "var(--color-warning)";
  if (event.event === "completed") return "var(--color-success)";
  return "var(--color-wire)";
}

/** Maps a raw SSE event to the same status vocabulary the canvas nodes use. */
function eventStatus(event: WorkflowEvent): NodeStatus {
  if (event.event === "failed") return "failed";
  if (event.event === "completed" || event.event === "gate_decision") return "completed";
  if (event.event === "started") return "running";
  return "waiting";
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function resultLabel(event: WorkflowEvent): string {
  if (event.event === "gate_decision") return `route: ${event.route ?? "?"}`;
  if (event.event === "failed") return event.error ?? "failed";
  return event.event ?? event.status ?? "event";
}

interface EventConsoleProps {
  events: WorkflowEvent[];
  /**
   * "full" -- the original scrolling telemetry console (timestamp, agent,
   * phase, result), used where the event stream is the primary content.
   * "compact" -- a slim strip capped at ~20% viewport height showing only
   * Timestamp / Agent / Status, for the bottom bar under the workflow canvas.
   */
  variant?: "full" | "compact";
}

export default function EventConsole({ events, variant = "full" }: EventConsoleProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  if (variant === "compact") {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-4 py-1.5 text-[10.5px] font-medium text-[var(--color-ink-muted)]">
          <Radio className="h-3 w-3" strokeWidth={2} />
          Event log
          <span className="font-mono-data ml-auto text-[var(--color-ink-faint)]">{events.length}</span>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto px-3 py-1.5" style={{ maxHeight: "16vh" }}>
          {events.length === 0 ? (
            <p className="px-2 py-3 text-center text-[11.5px] text-[var(--color-ink-faint)]">
              No events yet. Run a case to see live telemetry.
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {events
                .filter((e) => e.step !== undefined)
                .map((event, i) => {
                  const status = eventStatus(event);
                  const meta = STATUS_META[status];
                  return (
                    <li
                      key={`${event.timestamp}-${i}`}
                      className="font-mono-data grid grid-cols-[64px_1fr_84px] items-center gap-x-2 rounded px-2 py-0.5 text-[11px]"
                    >
                      <span className="text-[var(--color-ink-faint)]">{formatTime(event.timestamp)}</span>
                      <span className="truncate font-medium text-[var(--color-ink)]">{event.step}</span>
                      <span
                        className="inline-flex items-center justify-self-end gap-1 rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                        style={{ color: meta.fg, background: meta.bg }}
                      >
                        {meta.label}
                      </span>
                    </li>
                  );
                })}
            </ul>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-4 py-2 text-[11px] font-medium text-[var(--color-ink-muted)]">
        <Radio className="h-3 w-3" strokeWidth={2} />
        Live event stream
        <span className="font-mono-data ml-auto text-[var(--color-ink-faint)]">{events.length} events</span>
      </div>

      <div className="scrollbar-thin flex-1 overflow-y-auto px-3 py-2">
        {events.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12.5px] text-[var(--color-ink-faint)]">
            No events yet. Run a case to see live agent telemetry.
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {events.map((event, i) => (
              <li
                key={`${event.timestamp}-${i}`}
                className="font-mono-data grid grid-cols-[64px_1fr] items-baseline gap-x-2 rounded px-2 py-1 text-[11px] hover:bg-[var(--color-surface-sunken)]"
              >
                <span className="text-[var(--color-ink-faint)]">{formatTime(event.timestamp)}</span>
                <span className="flex flex-wrap items-baseline gap-x-1.5 leading-relaxed">
                  <span className="h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full" style={{ background: eventColor(event) }} />
                  <span className="font-medium text-[var(--color-ink)]">{event.step}</span>
                  <span className="text-[var(--color-ink-faint)]">·</span>
                  <span className="text-[var(--color-ink-muted)]">{event.phase}</span>
                  <span className="text-[var(--color-ink-faint)]">·</span>
                  <span style={{ color: eventColor(event) }}>{resultLabel(event)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
