/**
 * Shared types for the underwriting workflow frontend.
 *
 * These mirror the *actual* backend shapes found in the ADK project
 * (server.py's RunRecord/_build_progress_payload, and sample
 * output/decision_*.json files) rather than a guessed schema, so the API
 * layer and store (next steps) can consume backend responses directly.
 */

export type NodeStatus = "waiting" | "running" | "completed" | "failed";

export type WorkflowNodeKind = "agent" | "gate" | "hold" | "terminal";

/** Static definition of a node on the canvas -- position, display info,
 * and the backend phase/step identifiers that should light it up. */
export interface WorkflowNodeDefinition {
  id: string;
  kind: WorkflowNodeKind;
  label: string;
  phase: string | null;
  /** Backend `step` (or gate name) values from ProgressEvent that map to this node. */
  matchSteps: string[];
  x: number;
  y: number;
  /** lucide-react icon component name, e.g. "FileInput" -- rendered by WorkflowNode. */
  icon?: string;
}

export type EdgeBranch = "main" | "stop";

export interface WorkflowEdgeDefinition {
  id: string;
  source: string;
  target: string;
  label?: string;
  branch: EdgeBranch;
  /**
   * Which side of the source/target node this edge attaches to. Required
   * whenever the graph isn't a strict left-to-right line (branches that go
   * up to a convergence node, "skip" edges that jump over a node in
   * between, or edges that run right-to-left along a reversed row) --
   * without an explicit side, ReactFlow falls back to the default
   * left-target/right-source pair, which draws backward edges as a loop
   * that doubles back over whatever sits between source and target.
   * See lib/graph.ts NODES for the row layout these correspond to.
   */
  sourceHandle?: "source-left" | "source-right" | "source-top" | "source-bottom";
  targetHandle?: "target-left" | "target-right" | "target-top" | "target-bottom";
}

/** One entry from RunRecord.events / the SSE stream (workflow/progress.py::ProgressEvent.as_dict()). */
export interface WorkflowEvent {
  type: "phase_started" | "phase_completed" | "gate_decision" | "workflow_event" | "workflow_completed" | "workflow_failed";
  /**
   * Absent on the single terminal frame RunRecord.finalize() pushes (it only
   * carries run_id/status/decision/error) -- every node-level frame from
   * TrackedProgressTracker.emit() has both.
   */
  phase?: string;
  step?: string;
  event?: "started" | "completed" | "failed" | "gate_decision";
  timestamp: number;
  route?: string;
  error?: string;
  status?: string;
  decision?: DecisionPayload | null;
  run_id?: string;
  [key: string]: unknown;
}

/** GET /progress/{run_id} (also embedded in GET /workflow-state/{run_id}) */
export interface ProgressPayload {
  current_phase: string | null;
  current_agent: string | null;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  progress_percentage: number;
  active_node: string | null;
  completed_nodes: number;
  waiting_nodes: number;
  failed_nodes: number;
  event_history: WorkflowEvent[];
}

export interface PricingInfo {
  recommendation: string;
  indicative_premium: number;
  deductible: string;
  rationale: string[];
}

export interface CatExposureInfo {
  vendor: string;
  cat_score: number;
  cat_category: string;
  vendor_approved: boolean;
  pii_redacted: boolean;
}

export interface ApprovalLineageEntry {
  actor: string;
  action: string;
}

export interface CommunicationDraft {
  email_id: string;
  status: string;
  reason: string;
  recipient_role: string;
  subject: string;
  file?: string;
}

/** GET /decision/{run_id} -- shape taken directly from output/decision_*.json */
export interface DecisionPayload {
  application_id: string;
  scenario: string;
  status: string;
  current_phase: string;
  decision_mode: string;
  decision_maker: string;
  /** null when the run stopped before risk assessment ran, e.g. an incomplete submission. */
  risk_category: string | null;
  risk_score: number | null;
  confidence: number | null;
  /** `{}` (no fields) when the run stopped before CAT exposure / pricing ran. */
  cat_exposure: Partial<CatExposureInfo>;
  pricing: Partial<PricingInfo>;
  recommendation: {
    action: string;
    basis: string;
    confidence: number;
    conditions: string[];
    reason: string;
  };
  decision_evidence: string[];
  audit_trail: string[];
  approval_lineage: ApprovalLineageEntry[];
  governance_history: string[];
  workflow_metrics: {
    agents_executed: number;
    decision_gates: number;
    human_reviews: number;
    governance_checks: number;
  };
  ai_summary: string;
  communication: {
    emails_generated: number;
    drafts: CommunicationDraft[];
  };
  workflow: {
    workflow_id: string;
    started_at: string;
    completed_at: string;
    duration_seconds: number;
    workflow_version: string;
  };
  applicant: {
    business_name: string;
    broker_name: string;
    primary_property_address: string | null;
    total_insured_value: number;
    occupancy_type: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

/** GET /audit/{run_id} */
export interface AuditPayload {
  run_id: string;
  audit_trail: string[];
}

/** GET /communications/{run_id} */
export interface CommunicationsPayload {
  run_id: string;
  communications: CommunicationDraft[];
}

/** GET /sample-cases */
export interface SampleCasesPayload {
  samples: string[];
}

/** POST /run response */
export interface RunResponse {
  run_id: string;
  status: string;
}

/** GET /metrics */
export interface MetricsPayload {
  total_runs: number;
  completed: number;
  failed: number;
  average_execution_time: number;
}
