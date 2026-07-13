"""
property_controller.py -- v2 workflow, built on Google ADK's own graph engine.

Where workflow/controller.py (v1) is a hand-written Python function that
calls each agent and branches with if/else, this version expresses the
same 8-phase / 10-gate business workflow as an actual
`google.adk.workflow.Workflow` graph: FunctionNode steps wired together
with conditional edges, with ADK's own Runner driving execution, routing,
and event streaming.

Tool-calling model (now matching v1 exactly): every business tool
(hazard/mismatch detection, vendor approval, PII redaction, the CAT
vendor call, risk scoring, pricing, delegated authority for the senior
underwriter's own context) is called by the *agent itself* via real
LLM-directed function calling -- each LlmAgent in agents/*.py is built
with `tools=[...]`, and the model decides when to call them. This file
no longer pre-computes those results as bare FunctionNode steps; each
graph node instead calls that agent's `run()` (which builds the
tool-equipped LlmAgent, drives one turn via workflow/adk_runtime.call_agent,
and -- as a belt-and-braces guard -- re-runs the deterministic tool
itself so a routing-critical field can never be silently wrong even if
the model skipped or misreported a tool call). Every FunctionNode here is
a plain synchronous function (not `async def`): ADK's graph scheduler
runs each one to completion before evaluating its route, so the
synchronous `call_agent()` used inside every agent's `run()` (itself just
a thin `asyncio.run(...)` wrapper around one Runner turn) never collides
with the Runner's own event loop -- avoiding the asyncio/Streamlit event
loop conflicts a naive `async def` node + nested `asyncio.run()` would hit.

"Python determines routing" still holds: every conditional edge below
reads a field an agent's own tool call produced (complete,
disclosure_mismatch, vendor_approved, material_risk, approve, ...), never
something this file computes itself. The one exception is Decision 9
(override exceeds delegated authority?) in Phase 6, which stays a direct
deterministic call here -- it's the predicate for *whether to reach*
Phase 7 at all, so it can't live inside the Phase 7 agent it's gating
access to (SeniorUnderwriterAgent separately calls the same tool itself,
for its own informational context, once it *is* reached).

Because every LLM node here is a plain FunctionNode calling an agent's
run(), no graph node is a bare `LlmAgent` instance anymore -- so the old
`_fresh_agent()` workaround (building a differently-named LlmAgent
instance per incoming edge, since raw LlmAgent graph nodes need unique
names) is gone. A FunctionNode has no such constraint; the same
`senior_underwriter_step` node is reached from three different branches
(Phase 2 mandatory-review escalation, Phase 5 escalation, Phase 6
authority-exceeded) and simply reads which one via
`ctx.state["pending_escalation"]`, set by a tiny prep node on each of
those three edges.

Shared state (applicant data, audit trail, each step's result) is carried
via `ctx.state` -- ADK's own per-run state store.

Every FunctionNode here also emits progress events via a
workflow.progress.ProgressTracker stashed in ctx.state -- so the same
live before/after view Streamlit gets from v1 is available from this
graph-native version too.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from google.adk import Context, Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow, node
from google.genai import types

from agents import (
    cat_exposure_agent,
    document_intelligence_agent,
    evidence_generation_agent,
    human_underwriter_agent,
    pricing_agent,
    risk_summary_agent,
    senior_underwriter_agent,
    submission_intake_agent,
)
from services.document_linker import find_linked_documents, linked_documents_as_dict
from services.html_parser import load_and_parse_html
from services.normalizer import normalize
from services.pdf_parser import parse_pdf_document
from tools.communication_tool import draft_email
from tools.decision_assembly_tool import assemble_final_decision
from tools.delegated_authority_tool import check_delegated_authority
from workflow.governance import governance_policy_check
from workflow.progress import ProgressTracker

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIDENCE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _tracker(ctx: Context) -> ProgressTracker:
    if "tracker" not in ctx.state:
        ctx.state["tracker"] = ProgressTracker()
    return ctx.state["tracker"]


def _parse_and_normalize(file_path: str):
    extension = os.path.splitext(file_path)[1].lower()
    if extension in (".html", ".htm"):
        raw = load_and_parse_html(file_path)
    elif extension == ".pdf":
        raw = parse_pdf_document(file_path)
    else:
        raise ValueError(f"Unsupported proposal format: {extension}")
    return normalize(raw)


# ---------------------------------------------------------------------------
# PHASE 1 -- Submission Intake
# ---------------------------------------------------------------------------

@node
def intake(ctx: Context, node_input: str):
    """Entry point. node_input is a JSON string: {"file_path": "..."}."""
    file_path = json.loads(node_input)["file_path"]
    tracker = _tracker(ctx)
    tracker.started("PHASE_1_SUBMISSION_INTAKE", "parse_submission")

    applicant = _parse_and_normalize(file_path)

    tracker.completed("PHASE_1_SUBMISSION_INTAKE", "parse_submission")
    ctx.state.update({
        "file_path": file_path,
        "applicant": applicant,
        "application_id": applicant.proposal_number,
        "audit_trail": ["Submission received and parsed."],
        "approval_lineage": [],
        "governance_history": [],
        "email_references": [],
        "agents_executed": 0,
        "human_reviews": 0,
        "governance_checks": 0,
        "workflow_id": str(uuid.uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"file_path": file_path}


@node
def submission_intake_step(ctx: Context, node_input):
    """Calls SubmissionIntakeAgent -- a real LlmAgent with
    tools=[check_completeness] (agents/submission_intake_agent.py). The
    model decides when to call the tool; run() re-runs it deterministically
    as a belt-and-braces guard so `complete` can never be wrong."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    phase = "PHASE_1_SUBMISSION_INTAKE"

    with tracker.step(phase, "SubmissionIntakeAgent"):
        ctx.state["agents_executed"] += 1
        completeness = submission_intake_agent.run(
            applicant.raw_fields, progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["completeness_result"] = completeness
    ctx.state["approval_lineage"].append(
        {"actor": "SubmissionIntakeAgent", "action": "COMPLETE" if completeness["complete"] else "INCOMPLETE"}
    )

    tracker.gate_decision(phase, "Decision1_SubmissionComplete", str(completeness["complete"]))
    if not completeness["complete"]:
        ctx.state["audit_trail"].append(f"Mandatory fields missing: {completeness['missing_fields']}")
        return Event(route="incomplete", output={"__ctx_marker__": True})

    ctx.state["audit_trail"].append("Submission validated as complete.")
    return Event(route="complete", output={"__ctx_marker__": True})


@node
def handle_incomplete(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    completeness = ctx.state["completeness_result"]
    missing = completeness["missing_fields"]
    tracker = _tracker(ctx)

    email = draft_email(
        trigger="incomplete_submission", proposal_number=applicant.proposal_number,
        insured_name=applicant.business_name, broker_name=applicant.broker_name,
        reason=f"Missing mandatory fields: {', '.join(missing)}",
        required_action="Provide the missing fields and resubmit.",
        context={"missing_fields": missing}, output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_1_SUBMISSION_INTAKE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])

    return _finalize(
        ctx, status="STOPPED_INCOMPLETE", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
        recommendation={"action": "REQUEST_MORE_INFORMATION", "basis": "Incomplete submission",
                         "confidence": completeness.get("confidence", 0.9),
                         "conditions": [], "reason": "Missing mandatory fields."},
        decision_evidence=[f"Missing mandatory field: {f}" for f in missing],
    )


# ---------------------------------------------------------------------------
# PHASE 2 -- Document Intelligence
# ---------------------------------------------------------------------------

@node
def document_intelligence_step(ctx: Context, node_input):
    """Links related documents, then calls DocumentIntelligenceAgent -- a
    real LlmAgent with tools=[scan_declared_hazards,
    cross_check_disclosure_mismatch] (agents/document_intelligence_agent.py)."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    phase = "PHASE_2_DOCUMENT_INTELLIGENCE"

    with tracker.step(phase, "document_linker"):
        linked = find_linked_documents(applicant.proposal_number, data_dir=DATA_DIR)
    linked_html = linked_documents_as_dict(linked)
    ctx.state["linked_documents"] = [{"doc_type": d.doc_type, "file_path": d.file_path} for d in linked]

    with tracker.step(phase, "DocumentIntelligenceAgent"):
        ctx.state["agents_executed"] += 1
        doc_intel = document_intelligence_agent.run(
            applicant.raw_fields, linked_html, progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["doc_intel"] = doc_intel
    ctx.state["approval_lineage"].append({
        "actor": "DocumentIntelligenceAgent",
        "action": "MISMATCH" if doc_intel["disclosure_mismatch"] else "CONSISTENT",
    })

    tracker.gate_decision(phase, "Decision2_DisclosureMismatch", str(doc_intel["disclosure_mismatch"]))
    if doc_intel["disclosure_mismatch"]:
        ctx.state["audit_trail"].append(f"Disclosure mismatch(es) detected: {doc_intel['issues']}")
        return Event(route="mismatch", output={"__ctx_marker__": True})

    ctx.state["audit_trail"].append("No disclosure mismatch found.")
    return Event(route="consistent", output={"__ctx_marker__": True})


@node
def governance_and_mandatory_review(ctx: Context, node_input):
    """Deterministic governance stub (per spec: log + pass through, no
    SDK), then a mandatory HumanUnderwriterAgent review of the mismatch."""
    applicant = ctx.state["applicant"]
    doc_intel = ctx.state["doc_intel"]
    tracker = _tracker(ctx)
    phase = "PHASE_2_DOCUMENT_INTELLIGENCE"

    governance_result = governance_policy_check("disclosure_mismatch", {
        "proposal_number": applicant.proposal_number, "issues": doc_intel["issues"],
    })
    ctx.state["governance_history"].append(governance_result)
    ctx.state["governance_checks"] += 1
    ctx.state["audit_trail"].append("Governance Policy Check logged -- routed to mandatory human review.")

    with tracker.step(phase, "HumanUnderwriterAgent_MandatoryReview"):
        ctx.state["agents_executed"] += 1
        ctx.state["human_reviews"] += 1
        review = human_underwriter_agent.run(
            applicant.raw_fields, doc_intel, {}, {}, {}, progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["mismatch_review"] = review
    ctx.state["approval_lineage"].append({"actor": "HumanUnderwriterAgent", "action": review["action"]})

    tracker.gate_decision(phase, "Decision2b_MandatoryReviewAction", review["action"])
    route = {"Decline": "decline", "Escalate": "escalate"}.get(review["action"], "continue")
    return Event(route=route, output={"__ctx_marker__": True})


@node
def handle_mismatch_decline(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    review = ctx.state["mismatch_review"]
    tracker = _tracker(ctx)
    email = draft_email(
        trigger="rejection", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=review["reason"], output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    return _finalize(
        ctx, status="STOPPED_MISMATCH", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
        recommendation={"action": "DECLINE", "basis": "Disclosure mismatch", "confidence": 0.9,
                         "conditions": [], "reason": review["reason"]},
        decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in ctx.state["doc_intel"]["issues"]],
    )


@node
def mismatch_continue(ctx: Context, node_input):
    """Mismatch was reviewed and Approved/Overridden -- draft the (unsent)
    clarification email and continue the pipeline into Phase 3."""
    applicant = ctx.state["applicant"]
    review = ctx.state["mismatch_review"]
    tracker = _tracker(ctx)
    _ACTION_PAST_TENSE = {"Approve": "approved", "Override": "overridden", "Escalate": "escalated"}
    email = draft_email(
        trigger="disclosure_mismatch", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name,
        reason=f"Reviewed and {_ACTION_PAST_TENSE.get(review['action'], 'reviewed')} by underwriter.",
        context={"mismatches": ctx.state["doc_intel"]["issues"]}, output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    ctx.state["audit_trail"].append(f"Human Underwriter action on mismatch: {review['action']}. Continuing pipeline.")
    return {}


# ---------------------------------------------------------------------------
# PHASE 3 -- CAT Exposure
# ---------------------------------------------------------------------------

@node
def cat_exposure_step(ctx: Context, node_input):
    """Calls CATExposureAgent -- a real LlmAgent with
    tools=[check_vendor_approval, redact_pii, call_cat_vendor]
    (agents/cat_exposure_agent.py), called in that order by the model's
    own instruction. Decisions 3 (vendor approved?) and 4 (payload
    contains PII?) are read off the agent's result rather than
    pre-branched before the call -- see that module's run() for the
    belt-and-braces guard that forces cat_score=0/LOW if the vendor
    wasn't approved, regardless of what the model reported."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    phase = "PHASE_3_CAT_EXPOSURE"

    with tracker.step(phase, "CATExposureAgent"):
        ctx.state["agents_executed"] += 1
        cat_exposure = cat_exposure_agent.run(
            applicant.cat_vendor, applicant.raw_fields,
            applicant.flood_zone, applicant.earthquake_zone, applicant.cyclone_zone, applicant.wildfire_zone,
            progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["cat_exposure"] = cat_exposure
    ctx.state["approval_lineage"].append({"actor": "CATExposureAgent", "action": cat_exposure["cat_category"]})

    tracker.gate_decision(phase, "Decision3_VendorApproved", str(cat_exposure["vendor_approved"]))
    if not cat_exposure["vendor_approved"]:
        ctx.state["audit_trail"].append(
            f"CAT vendor '{applicant.cat_vendor}' is not on the approved-vendor list -- API call blocked."
        )
        return Event(route="blocked", output={"__ctx_marker__": True})

    tracker.gate_decision(phase, "Decision4_PayloadContainsPII", str(cat_exposure["pii_redacted"]))
    ctx.state["audit_trail"].append(
        "PII redacted before CAT vendor call." if cat_exposure["pii_redacted"] else "No PII found in CAT vendor payload."
    )
    ctx.state["cat_results"] = {
        "vendor": applicant.cat_vendor, "cat_score": cat_exposure["cat_score"], "cat_category": cat_exposure["cat_category"],
        "vendor_approved": True, "pii_redacted": cat_exposure["pii_redacted"],
    }
    return Event(route="approved", output={"__ctx_marker__": True})


@node
def handle_vendor_blocked(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    email = draft_email(
        trigger="cat_vendor_blocked", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=f"CAT vendor '{applicant.cat_vendor}' is not approved.",
        output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback("PHASE_3_CAT_EXPOSURE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    return _finalize(
        ctx, status="STOPPED_MISMATCH", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
        recommendation={"action": "ESCALATE", "basis": "CAT vendor not approved", "confidence": 0.9,
                         "conditions": [], "reason": f"Vendor '{applicant.cat_vendor}' is not on the approved list."},
        decision_evidence=[f"CAT vendor '{applicant.cat_vendor}' is not approved."],
    )


# ---------------------------------------------------------------------------
# PHASE 4 -- Risk Assessment
# ---------------------------------------------------------------------------

@node
def risk_and_pricing_step(ctx: Context, node_input):
    """Calls RiskSummaryAgent (tools=[score_property_risk]) then
    PricingAgent (tools=[calculate_pricing]) -- both real LlmAgents that
    call their one deterministic tool themselves, per
    agents/risk_summary_agent.py and agents/pricing_agent.py."""
    applicant = ctx.state["applicant"]
    doc_intel = ctx.state["doc_intel"]
    cat_exposure = ctx.state["cat_exposure"]
    tracker = _tracker(ctx)
    phase = "PHASE_4_RISK_ASSESSMENT"

    with tracker.step(phase, "RiskSummaryAgent"):
        ctx.state["agents_executed"] += 1
        risk_summary = risk_summary_agent.run(
            applicant.raw_fields, len(doc_intel.get("extracted_hazards", [])), len(doc_intel.get("issues", [])),
            cat_exposure["cat_score"], applicant.previous_claims_count,
            progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["risk_summary"] = risk_summary
    ctx.state["approval_lineage"].append({"actor": "RiskSummaryAgent", "action": risk_summary["risk_category"]})
    ctx.state["audit_trail"].append(
        f"Risk assessed: score={risk_summary['risk_score']}, "
        f"category={risk_summary['risk_category']}, confidence={risk_summary['confidence']}."
    )

    with tracker.step(phase, "PricingAgent"):
        ctx.state["agents_executed"] += 1
        pricing = pricing_agent.run(
            str(applicant.total_insured_value or 0), risk_summary["risk_category"], risk_summary["material_risk"],
            applicant.deductible or "", progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["pricing"] = pricing
    ctx.state["approval_lineage"].append({"actor": "PricingAgent", "action": "PRICED"})

    material_risk = risk_summary["material_risk"]
    tracker.gate_decision(phase, "Decision5_MaterialHazard", str(material_risk))
    if material_risk:
        low_confidence = risk_summary.get("confidence", 1.0) < CONFIDENCE_THRESHOLD
        tracker.gate_decision(phase, "Decision6_LowConfidence", str(low_confidence))
        if low_confidence:
            ctx.state["audit_trail"].append(
                "Material hazard with confidence below threshold -- senior underwriter signoff will be required."
            )

    return {}


# ---------------------------------------------------------------------------
# PHASE 5 -- Human Underwriter
# ---------------------------------------------------------------------------

@node
def human_underwriter_step(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    phase = "PHASE_5_HUMAN_UNDERWRITER"

    with tracker.step(phase, "HumanUnderwriterAgent"):
        ctx.state["agents_executed"] += 1
        ctx.state["human_reviews"] += 1
        result = human_underwriter_agent.run(
            applicant.raw_fields, ctx.state["doc_intel"], ctx.state["cat_exposure"],
            ctx.state["risk_summary"], ctx.state["pricing"],
            progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["human_underwriter_result"] = result
    ctx.state["approval_lineage"].append({"actor": "HumanUnderwriterAgent", "action": result["action"]})

    tracker.gate_decision(phase, "Decision7_UnderwriterAction", result["action"])
    route = {"Approve": "approve", "Decline": "decline", "Escalate": "escalate", "Override": "override"}.get(
        result["action"], "escalate"
    )
    return Event(route=route, output={"__ctx_marker__": True})


@node
def handle_approve(ctx: Context, node_input):
    risk_summary = ctx.state["risk_summary"]
    doc_intel = ctx.state["doc_intel"]
    human_result = ctx.state["human_underwriter_result"]
    is_clean_case = (
        not risk_summary["material_risk"] and not doc_intel["disclosure_mismatch"]
        and risk_summary.get("confidence", 0) >= CONFIDENCE_THRESHOLD
    )
    decision_mode, decision_maker = ("AUTONOMOUS", "AI") if is_clean_case else ("HUMAN_REVIEW", "Human Underwriter")
    return _finalize(
        ctx, status="COMPLETED", decision_mode=decision_mode, decision_maker=decision_maker,
        recommendation={"action": "APPROVE", "basis": ctx.state["pricing"]["recommendation"],
                         "confidence": risk_summary.get("confidence"), "conditions": [], "reason": human_result["reason"]},
        decision_evidence=risk_summary.get("reasoning", []),
    )


@node
def handle_decline(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    human_result = ctx.state["human_underwriter_result"]
    tracker = _tracker(ctx)
    email = draft_email(
        trigger="rejection", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=human_result["reason"], output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_5_HUMAN_UNDERWRITER", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    return _finalize(
        ctx, status="REJECTED", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
        recommendation={"action": "DECLINE", "basis": ctx.state["pricing"]["recommendation"],
                         "confidence": ctx.state["risk_summary"].get("confidence"), "conditions": [], "reason": human_result["reason"]},
        decision_evidence=ctx.state["risk_summary"].get("reasoning", []),
    )


# ---------------------------------------------------------------------------
# PHASE 6 -- Override
# ---------------------------------------------------------------------------

@node
def override_step(ctx: Context, node_input):
    material_risk = ctx.state["risk_summary"]["material_risk"]
    tracker = _tracker(ctx)
    ctx.state["audit_trail"].append(f"Override submitted by underwriter: {ctx.state['human_underwriter_result']['reason']}")
    tracker.gate_decision("PHASE_6_OVERRIDE", "Decision8_OverrideContradictsMaterialHazard", str(material_risk))
    return Event(route="contradicts" if material_risk else "clean", output={"__ctx_marker__": True})


@node
def authority_step(ctx: Context, node_input):
    """Decision 9 -- stays a direct deterministic call (not an agent's
    tool call), since it's the routing predicate for whether Phase 7 is
    reached at all. SeniorUnderwriterAgent separately calls this same
    tool itself for its own context once reached (see
    agents/senior_underwriter_agent.py)."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    authority_check = check_delegated_authority(
        str(applicant.total_insured_value or 0), role="underwriter",
        progress_callback=tracker.tool_callback("PHASE_6_OVERRIDE", "delegated_authority_tool"),
    )
    ctx.state["authority_check"] = authority_check
    tracker.gate_decision("PHASE_6_OVERRIDE", "Decision9_ExceedsDelegatedAuthority", str(authority_check["exceeds_authority"]))
    return Event(route="exceeds" if authority_check["exceeds_authority"] else "within", output={"__ctx_marker__": True})


@node
def accept_override(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    human_result = ctx.state["human_underwriter_result"]
    tracker = _tracker(ctx)
    ctx.state["audit_trail"].append("Override accepted within delegated authority.")
    email = draft_email(
        trigger="human_review", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=f"Override recorded: {human_result['reason']}",
        required_action="Management visibility only -- no action required.", output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_6_OVERRIDE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    return _finalize(
        ctx, status="CONDITIONALLY_APPROVED", decision_mode="OVERRIDE", decision_maker="Human Underwriter",
        recommendation={"action": "OVERRIDE", "basis": ctx.state["pricing"].get("recommendation", ""),
                         "confidence": ctx.state["risk_summary"].get("confidence"),
                         "conditions": human_result.get("conditions", []), "reason": human_result["reason"]},
        decision_evidence=ctx.state["risk_summary"].get("reasoning", []),
    )


# ---------------------------------------------------------------------------
# PHASE 7 -- Senior Underwriter
# ---------------------------------------------------------------------------
# Reached from three branches (Phase 2 mandatory-review escalation, Phase 5
# escalation, Phase 6 authority-exceeded). Each branch's tiny prep node just
# records why/who into ctx.state["pending_escalation"] before routing into
# the one shared senior_underwriter_step -- no need for multiple pre-built
# agent instances (that was only necessary when a raw LlmAgent object was
# the graph node itself; a FunctionNode has no such uniqueness constraint).

@node
def prep_escalate_mismatch(ctx: Context, node_input):
    ctx.state["pending_escalation"] = {
        "reason": "Mandatory mismatch review escalated by Human Underwriter.",
        "unique_name": "SeniorUnderwriterAgent_Mismatch",
        "human_underwriter_result": ctx.state["mismatch_review"],
    }
    return {}


@node
def prep_escalate_human(ctx: Context, node_input):
    ctx.state["pending_escalation"] = {
        "reason": "Escalated by Human Underwriter after full risk assessment.",
        "unique_name": "SeniorUnderwriterAgent_Escalate",
        "human_underwriter_result": ctx.state["human_underwriter_result"],
    }
    return {}


@node
def prep_escalate_authority(ctx: Context, node_input):
    ctx.state["pending_escalation"] = {
        "reason": "Override contradicts a material hazard finding and exceeds the underwriter's delegated authority.",
        "unique_name": "SeniorUnderwriterAgent_Authority",
        "human_underwriter_result": ctx.state["human_underwriter_result"],
    }
    return {}


@node
def senior_underwriter_step(ctx: Context, node_input):
    """Calls SeniorUnderwriterAgent -- a real LlmAgent with
    tools=[check_delegated_authority] (agents/senior_underwriter_agent.py)."""
    applicant = ctx.state["applicant"]
    escalation = ctx.state["pending_escalation"]
    tracker = _tracker(ctx)
    phase = "PHASE_7_SENIOR_UNDERWRITER"

    with tracker.step(phase, escalation["unique_name"]):
        ctx.state["agents_executed"] += 1
        ctx.state["human_reviews"] += 1
        senior_result = senior_underwriter_agent.run(
            applicant.raw_fields, ctx.state.get("risk_summary", {}), ctx.state.get("pricing", {}),
            escalation["human_underwriter_result"], escalation_reason=escalation["reason"],
            unique_name=escalation["unique_name"], progress_callback=tracker.agent_callback(phase),
        )
    ctx.state["senior_result"] = senior_result
    ctx.state["approval_lineage"].append(
        {"actor": "SeniorUnderwriterAgent", "action": "APPROVE" if senior_result["approve"] else "REJECT"}
    )

    tracker.gate_decision(phase, "Decision10_SeniorApprove", str(senior_result["approve"]))
    return Event(route="approve" if senior_result["approve"] else "reject", output={"__ctx_marker__": True})


@node
def senior_approve(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    senior_result = ctx.state["senior_result"]
    tracker = _tracker(ctx)
    email = draft_email(
        trigger="conditional_approval", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=senior_result["reason"],
        context={"conditions": senior_result.get("conditions", [])}, output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_7_SENIOR_UNDERWRITER", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    risk_summary = ctx.state.get("risk_summary", {})
    return _finalize(
        ctx, status="CONDITIONALLY_APPROVED", decision_mode="SENIOR_UNDERWRITER", decision_maker="Senior Underwriter",
        recommendation={"action": "APPROVE", "basis": senior_result["reason"], "confidence": risk_summary.get("confidence"),
                         "conditions": senior_result.get("conditions", []), "reason": senior_result["reason"]},
        decision_evidence=risk_summary.get("reasoning", []),
    )


@node
def senior_reject(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    senior_result = ctx.state["senior_result"]
    tracker = _tracker(ctx)
    trigger = "information_request" if senior_result.get("requested_items") else "rejection"
    email = draft_email(
        trigger=trigger, proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=senior_result["reason"],
        context={"requested_items": senior_result.get("requested_items", [])}, output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_7_SENIOR_UNDERWRITER", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    risk_summary = ctx.state.get("risk_summary", {})
    status = "STOPPED_HUMAN_REVIEW" if senior_result.get("requested_items") else "REJECTED"
    action = "REQUEST_MORE_INFORMATION" if senior_result.get("requested_items") else "DECLINE"
    return _finalize(
        ctx, status=status, decision_mode="SENIOR_UNDERWRITER", decision_maker="Senior Underwriter",
        recommendation={"action": action, "basis": senior_result["reason"], "confidence": risk_summary.get("confidence"),
                         "conditions": [], "reason": senior_result["reason"]},
        decision_evidence=risk_summary.get("reasoning", []),
    )


# ---------------------------------------------------------------------------
# PHASE 8 -- Final Decision
# ---------------------------------------------------------------------------

def _finalize(ctx: Context, status: str, decision_mode: str, decision_maker: str,
              recommendation: Dict[str, Any], decision_evidence) -> Dict[str, Any]:
    """Deterministic assembly step -- backed by tools/decision_assembly_tool.py.
    Called directly by every terminal FunctionNode above (not itself a
    graph node), exactly like workflow/controller.py's (v1) _finalize().
    The only LLM step here is EvidenceGenerationAgent, which writes the
    one free-text paragraph in decision.json -- it has no tools, only
    output_schema, so its own run() calls it via a plain structured turn."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    phase = "PHASE_8_FINAL_DECISION"

    with tracker.step(phase, "EvidenceGenerationAgent"):
        ctx.state["agents_executed"] += 1
        doc_intel = ctx.state.get("doc_intel", {})
        ai_summary = evidence_generation_agent.run(
            applicant.raw_fields,
            {"disclosure_mismatch": bool(doc_intel.get("issues")), "issues": doc_intel.get("issues", [])},
            ctx.state.get("cat_results", {}), ctx.state.get("risk_summary", {}), ctx.state.get("pricing", {}),
            {"status": status, "decision_mode": decision_mode, "decision_maker": decision_maker, "recommendation": recommendation},
            progress_callback=tracker.agent_callback(phase),
        )

    scenario = os.path.splitext(os.path.basename(ctx.state["file_path"]))[0]

    with tracker.step(phase, "decision_assembly_tool"):
        decision = assemble_final_decision(
            application_id=ctx.state.get("application_id"),
            status=status, scenario=scenario, current_phase=phase,
            decision_mode=decision_mode, decision_maker=decision_maker,
            risk_category=ctx.state.get("risk_summary", {}).get("risk_category"),
            risk_score=ctx.state.get("risk_summary", {}).get("risk_score"),
            confidence=ctx.state.get("risk_summary", {}).get("confidence"),
            cat_exposure=ctx.state.get("cat_results", {}),
            pricing=ctx.state.get("pricing", {}),
            recommendation=recommendation,
            decision_evidence=decision_evidence,
            audit_trail=ctx.state["audit_trail"],
            approval_lineage=ctx.state["approval_lineage"],
            governance_history=ctx.state["governance_history"],
            workflow_metrics={
                "agents_executed": ctx.state["agents_executed"], "decision_gates": 10,
                "human_reviews": ctx.state.get("human_reviews", 0), "governance_checks": ctx.state.get("governance_checks", 0),
            },
            ai_summary=ai_summary,
            email_references=ctx.state.get("email_references", []),
            workflow_id=ctx.state.get("workflow_id"), started_at=ctx.state.get("started_at"),
            applicant={
                "business_name": applicant.business_name, "broker_name": applicant.broker_name,
                "primary_property_address": applicant.primary_property_address,
                "total_insured_value": applicant.total_insured_value, "occupancy_type": applicant.occupancy_type,
            },
            documents=ctx.state.get("linked_documents", []),
            execution_timeline=tracker.as_list(),
            output_dir=OUTPUT_DIR,
        )
    ctx.state["final_decision"] = decision
    return decision


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _build_graph() -> Workflow:
    return Workflow(
        name="commercial_property_underwriting_v2",
        edges=[
            ("START", intake, submission_intake_step),
            (submission_intake_step, {"complete": document_intelligence_step, "incomplete": handle_incomplete}),

            (document_intelligence_step, {"consistent": cat_exposure_step, "mismatch": governance_and_mandatory_review}),

            (governance_and_mandatory_review, {
                "decline": handle_mismatch_decline,
                "escalate": prep_escalate_mismatch,
                "continue": mismatch_continue,
            }),
            (prep_escalate_mismatch, senior_underwriter_step),
            (mismatch_continue, cat_exposure_step),

            (cat_exposure_step, {"blocked": handle_vendor_blocked, "approved": risk_and_pricing_step}),
            (risk_and_pricing_step, human_underwriter_step),

            (human_underwriter_step, {
                "approve": handle_approve,
                "decline": handle_decline,
                "escalate": prep_escalate_human,
                "override": override_step,
            }),
            (prep_escalate_human, senior_underwriter_step),

            (override_step, {"clean": accept_override, "contradicts": authority_step}),
            (authority_step, {"within": accept_override, "exceeds": prep_escalate_authority}),
            (prep_escalate_authority, senior_underwriter_step),

            (senior_underwriter_step, {"approve": senior_approve, "reject": senior_reject}),
        ],
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_workflow(file_path: str) -> dict:
    """Runs the underwriting workflow as a real ADK Workflow graph and
    returns the final decision dict (same shape as v1's run_workflow)."""
    import asyncio

    async def _run() -> dict:
        session_service = InMemorySessionService()
        user_id, session_id = "underwriting_system", str(uuid.uuid4())
        await session_service.create_session(
            app_name="commercial_property_underwriting_adk_v2", user_id=user_id, session_id=session_id
        )

        workflow = _build_graph()
        runner = Runner(agent=workflow, app_name="commercial_property_underwriting_adk_v2", session_service=session_service)

        message = types.Content(role="user", parts=[types.Part(text=json.dumps({"file_path": file_path}))])

        final_output = None
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
            if getattr(event, "output", None) is not None:
                final_output = event.output

        if final_output is None:
            raise RuntimeError("Workflow produced no final decision output.")
        return final_output

    return asyncio.run(_run())
