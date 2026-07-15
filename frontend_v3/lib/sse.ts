/**
 * Step 5: SSE integration.
 *
 * The backend (`server.py::events`) writes frames like:
 *
 *   event: gate_decision
 *   data: {"type":"gate_decision","phase":"...","step":"...","event":"gate_decision", ...}
 *
 * i.e. it sets a *named* SSE event per frame, so a plain `EventSource.onmessage`
 * only catches frames with no explicit `event:` line. We register a listener
 * for every named type the backend emits (`_map_event_type` in server.py) plus
 * a `message` fallback, and forward all of them through one `onEvent` callback
 * -- the caller doesn't need to know about SSE event names at all.
 */
import type { WorkflowEvent } from "@/types/workflow";
import { API_BASE } from "./api";

const NAMED_EVENT_TYPES = [
  "phase_started",
  "phase_completed",
  "gate_decision",
  "workflow_event",
  "workflow_completed",
  "workflow_failed",
] as const;

export interface ConnectToEventsHandlers {
  /** Fired for every event frame, in arrival order, already JSON-parsed. */
  onEvent: (event: WorkflowEvent) => void;
  onOpen?: () => void;
  /** The browser's EventSource auto-retries; this fires on each transient error. */
  onError?: (error: Event) => void;
}

/**
 * Open a live connection to GET /events/{run_id}.
 * Returns a disconnect function -- call it on unmount / run change / workflow
 * completion to close the underlying connection.
 */
export function connectToEvents(runId: string, handlers: ConnectToEventsHandlers): () => void {
  const source = new EventSource(`${API_BASE}/events/${runId}`);

  const handleFrame = (raw: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(raw.data) as WorkflowEvent;
      handlers.onEvent(parsed);
    } catch {
      // Malformed frame -- drop it rather than crash the stream.
    }
  };

  for (const type of NAMED_EVENT_TYPES) {
    source.addEventListener(type, handleFrame as EventListener);
  }
  source.addEventListener("message", handleFrame as EventListener);

  if (handlers.onOpen) source.onopen = handlers.onOpen;
  if (handlers.onError) source.onerror = handlers.onError;

  return () => {
    for (const type of NAMED_EVENT_TYPES) {
      source.removeEventListener(type, handleFrame as EventListener);
    }
    source.removeEventListener("message", handleFrame as EventListener);
    source.close();
  };
}
