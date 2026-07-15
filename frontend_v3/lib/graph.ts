import type { WorkflowNodeDefinition, WorkflowEdgeDefinition, WorkflowEvent } from "@/types/workflow";

/**
 * Simplified to the 8 real phases the backend tracks (PHASE_1..PHASE_8 in
 * workflow/progress.py) plus one convergence node ("Human Review / Hold")
 * for every stop/escalation branch -- rather than a node per internal gate.
 * The gates still matter (their outcome shows as a resolved-route chip on
 * whichever phase node they belong to, and their branch still animates),
 * they just don't each get their own box on the canvas anymore. This keeps
 * the graph legible at a glance instead of 15 small boxes that only read
 * as a blur once zoomed out to fit.
 *
 * `matchSteps` values are the *real* phase/step/gate identifiers emitted
 * by workflow/property_controller.py (via progress.py's ProgressTracker),
 * so live SSE events can be matched to a node without any guesswork.
 *
 * LAYOUT: two rows instead of one long line. A single row of 8 nodes is
 * ~2500px wide but only ~130px tall, so fitView (which always preserves
 * aspect ratio -- it never stretches the drawing to fill a panel) had to
 * shrink the whole graph down to fit that width, leaving huge blank bands
 * above and below since the panel itself is much closer to square. Folding
 * the second half of the flow into a row underneath -- and routing it
 * right-to-left so it reads as a continuous S-curve rather than jumping
 * back to the left edge -- brings the drawing's own aspect ratio in line
 * with the panel's, so fitView actually uses the vertical space instead of
 * padding it out. See the handle ids on each edge below for how the
 * resulting up/down and right-to-left edges attach without looping back
 * over whatever node happens to sit between source and target.
 */
export const NODES: WorkflowNodeDefinition[] = [
  // Row 1, left -> right
  {
    id: "submission_intake",
    kind: "agent",
    label: "Submission Intake",
    phase: "PHASE_1_SUBMISSION_INTAKE",
    matchSteps: ["parse_submission", "SubmissionIntakeAgent", "Decision1_SubmissionComplete"],
    x: 0,
    y: 0,
    icon: "FileInput",
  },
  {
    id: "document_intelligence",
    kind: "agent",
    label: "Document Intelligence",
    phase: "PHASE_2_DOCUMENT_INTELLIGENCE",
    matchSteps: ["document_linker", "DocumentIntelligenceAgent", "Decision2_DisclosureMismatch"],
    x: 340,
    y: 0,
    icon: "ScanSearch",
  },
  {
    id: "cat_exposure",
    kind: "agent",
    label: "CAT Exposure",
    phase: "PHASE_3_CAT_EXPOSURE",
    matchSteps: ["CATExposureAgent", "Decision3_VendorApproved", "Decision4_PayloadContainsPII"],
    x: 680,
    y: 0,
    icon: "CloudLightning",
  },
  {
    id: "risk_assessment",
    kind: "agent",
    label: "Risk Assessment & Pricing",
    phase: "PHASE_4_RISK_ASSESSMENT",
    matchSteps: ["RiskSummaryAgent", "Decision5_MaterialHazard", "Decision6_LowConfidence", "PricingAgent"],
    x: 1020,
    y: 0,
    icon: "Gauge",
  },
  // Convergence node for every mandatory-review / blocked / escalated path.
  // Sits above row 1, over the cat_exposure/document_intelligence seam so
  // its three incoming branches (from below) stay short.
  {
    id: "human_review_hold",
    kind: "hold",
    label: "Human Review / Hold",
    phase: null,
    matchSteps: ["HumanUnderwriterAgent_MandatoryReview", "Decision2b_MandatoryReviewAction"],
    x: 680,
    y: -320,
    icon: "Users",
  },
  // Row 2, right -> left (continues the flow as an S-curve under row 1,
  // instead of extending row 1 further out to the right).
  {
    id: "delegated_authority",
    kind: "gate",
    label: "Delegated Authority",
    phase: "PHASE_6_OVERRIDE",
    matchSteps: ["Decision9_ExceedsDelegatedAuthority"],
    // x pushed out from 1020 -> 1180: at 1020 it sat only ~116px from
    // human_underwriter's right edge, so the three edges converging on it
    // (within authority / escalate-override / exceeds authority) had no
    // room to separate and read as a tangle right next to the node.
    // y nudged +12: this node's box is 104px tall vs. the 128px WorkflowNode
    // boxes on either side of it, so matching y left it visually riding
    // high relative to the row -- this centers it against them instead.
    x: 1180,
    y: 432,
    icon: "Landmark",
  },
  {
    id: "human_underwriter",
    kind: "agent",
    label: "Human Underwriter",
    phase: "PHASE_5_HUMAN_UNDERWRITER",
    matchSteps: ["HumanUnderwriterAgent", "Decision7_UnderwriterAction"],
    x: 760,
    y: 420,
    icon: "UserCheck",
  },
  {
    id: "senior_underwriter",
    kind: "agent",
    label: "Senior Underwriter",
    phase: "PHASE_7_SENIOR_UNDERWRITER",
    matchSteps: ["Decision10_SeniorApprove"],
    x: 380,
    y: 420,
    icon: "UserCog",
  },
  {
    id: "decision",
    kind: "terminal",
    label: "Final Decision",
    phase: "PHASE_8_FINAL_DECISION",
    matchSteps: ["EvidenceGenerationAgent", "decision_assembly_tool", "workflow_completed", "workflow_failed"],
    x: 0,
    y: 420,
    icon: "Flag",
  },
];

export const EDGES: WorkflowEdgeDefinition[] = [
  // Row 1: plain left-to-right, default sides.
  { id: "e1", source: "submission_intake", target: "document_intelligence", branch: "main", sourceHandle: "source-right", targetHandle: "target-left" },
  { id: "e2", source: "document_intelligence", target: "cat_exposure", branch: "main", label: "No mismatch", sourceHandle: "source-right", targetHandle: "target-left" },
  // Row 1 -> hold: hold sits above, so these leave the top of the node and
  // arrive at the bottom of the hold node rather than looping via left/right.
  { id: "e3", source: "document_intelligence", target: "human_review_hold", branch: "stop", label: "Mismatch found", sourceHandle: "source-top", targetHandle: "target-bottom" },
  { id: "e4", source: "cat_exposure", target: "risk_assessment", branch: "main", label: "Approved & clear", sourceHandle: "source-right", targetHandle: "target-left" },
  { id: "e5", source: "cat_exposure", target: "human_review_hold", branch: "stop", label: "Not approved / PII", sourceHandle: "source-top", targetHandle: "target-bottom" },
  // risk_assessment drops straight down into row 2's delegated_authority.
  { id: "e6", source: "risk_assessment", target: "delegated_authority", branch: "main", label: "Priced", sourceHandle: "source-bottom", targetHandle: "target-top" },
  { id: "e7", source: "risk_assessment", target: "human_review_hold", branch: "stop", label: "Low confidence", sourceHandle: "source-top", targetHandle: "target-bottom" },
  // Row 2 runs right-to-left, so "forward" edges leave the LEFT side and
  // arrive on the RIGHT -- the mirror image of row 1 -- otherwise the
  // default left/right pairing draws every one of these as a loop.
  { id: "e8", source: "delegated_authority", target: "human_underwriter", branch: "main", label: "Within authority", sourceHandle: "source-left", targetHandle: "target-right" },
  // "Exceeds authority" skips over human_underwriter, which sits directly
  // between delegated_authority and senior_underwriter in row 2 -- routed
  // via the bottom of both nodes so it arcs under the row instead of
  // passing through/behind human_underwriter.
  { id: "e9", source: "delegated_authority", target: "senior_underwriter", branch: "stop", label: "Exceeds authority", sourceHandle: "source-bottom", targetHandle: "target-bottom" },
  { id: "e10", source: "human_underwriter", target: "senior_underwriter", branch: "main", label: "Escalate / override", sourceHandle: "source-left", targetHandle: "target-right" },
  // hold -> senior_underwriter: leaves hold's left side, drops through the
  // open band between row 1 and row 2, and arrives at senior_underwriter's
  // top -- clear of both rows' node bodies.
  { id: "e11", source: "human_review_hold", target: "senior_underwriter", branch: "stop", sourceHandle: "source-left", targetHandle: "target-top" },
  { id: "e12", source: "senior_underwriter", target: "decision", branch: "main", sourceHandle: "source-left", targetHandle: "target-right" },
];

/** Tools executed per node, consolidated from every phase/gate it now represents. */
export const TOOLS_BY_NODE: Record<string, string[]> = {
  submission_intake: ["parse_submission_tool"],
  document_intelligence: ["html_parser", "document_linker", "normalizer"],
  cat_exposure: ["vendor_approval_tool", "cat_vendor_tool", "pii_redaction_tool"],
  risk_assessment: ["property_risk_scoring_tool", "hazard_detection_tool", "pricing_tool"],
  decision: ["decision_assembly_tool"],
};

/** Callback chain shown under each node, e.g. parse_submission_tool() -> submission_intake_completed(). */
export const CALLBACKS_BY_NODE: Record<string, string[]> = {
  submission_intake: ["parse_submission_tool()", "submission_intake_completed()"],
  document_intelligence: ["document_linker()", "document_intelligence_completed()"],
  cat_exposure: ["cat_vendor_tool()", "cat_exposure_completed()"],
  risk_assessment: ["property_risk_scoring_tool()", "pricing_tool()", "risk_assessment_completed()"],
  decision: ["decision_assembly_tool()", "evidence_generation_completed()"],
};

/** Resolve a live SSE/event-history entry to the node id it should affect. */
export function matchEventToNode(event: Pick<WorkflowEvent, "step" | "phase">): string | undefined {
  const node = event.step ? NODES.find((n) => n.matchSteps.includes(event.step!)) : undefined;
  if (node) return node.id;
  // Fall back to phase match if the step name is a one-off (e.g. senior underwriter escalation names).
  return NODES.find((n) => n.phase === event.phase)?.id;
}

export function getNodeDefinition(id: string): WorkflowNodeDefinition | undefined {
  return NODES.find((n) => n.id === id);
}