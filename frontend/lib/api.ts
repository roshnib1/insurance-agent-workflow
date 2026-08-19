/**
 * Step 4: API layer.
 *
 * Thin wrappers around the existing FastAPI backend (server.py). No
 * endpoint shapes are invented here -- every function maps 1:1 to a route
 * that already exists, and every response type comes from types/workflow.ts.
 *
 * Base URL comes from NEXT_PUBLIC_API_BASE_URL so the same build can point
 * at localhost during development and a deployed API in production.
 */
import type {
  AuditPayload,
  CommunicationsPayload,
  DecisionPayload,
  MetricsPayload,
  ProgressPayload,
  RunResponse,
  SampleCasesPayload,
} from "@/types/workflow";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Structured API error carrying the HTTP status alongside the backend's message. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError("Could not reach the underwriting API. Is the backend running?", 0);
  }

  if (!response.ok) {
    let message = response.statusText || `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body?.message ?? body?.detail ?? message;
    } catch {
      // response wasn't JSON -- keep the default message
    }
    throw new ApiError(message, response.status);
  }

  // /run returns 202 with a JSON body; everything else is 200 JSON as well.
  return (await response.json()) as T;
}

/** GET / -- service metadata. */
export function getHealth(): Promise<{ service: string; status: string; version: string }> {
  return request("/");
}

/** GET /sample-cases */
export function getSampleCases(): Promise<SampleCasesPayload> {
  return request("/sample-cases");
}

/**
 * POST /run
 * Exactly one of `sampleCase` or `file` must be provided -- mirrors the
 * backend, which accepts either a sample_case form field or an uploaded
 * HTML/PDF file, never both.
 */
export function runWorkflow(input: { sampleCase?: string } | { file: File }): Promise<RunResponse> {
  const form = new FormData();
  if ("file" in input) {
    form.append("file", input.file);
  } else if (input.sampleCase) {
    form.append("sample_case", input.sampleCase);
  } else {
    return Promise.reject(new ApiError("Provide a sample case or upload a file.", 400));
  }
  return request("/run", { method: "POST", body: form });
}

/** GET /progress/{run_id} */
export function getProgress(runId: string): Promise<ProgressPayload> {
  return request(`/progress/${runId}`);
}

/** GET /decision/{run_id} */
export function getDecision(runId: string): Promise<DecisionPayload> {
  return request(`/decision/${runId}`);
}

/** GET /audit/{run_id} */
export function getAudit(runId: string): Promise<AuditPayload> {
  return request(`/audit/${runId}`);
}

/** GET /communications/{run_id} */
export function getCommunications(runId: string): Promise<CommunicationsPayload> {
  return request(`/communications/${runId}`);
}

/** GET /workflow-state/{run_id} -- full debug snapshot, used for reconnect/recovery. */
export function getWorkflowState(runId: string): Promise<{
  run_id: string;
  status: string;
  progress: ProgressPayload;
  events: unknown[];
  decision: DecisionPayload | null;
  error: string | null;
}> {
  return request(`/workflow-state/${runId}`);
}

/** GET /metrics */
export function getMetrics(): Promise<MetricsPayload> {
  return request("/metrics");
}
