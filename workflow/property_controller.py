"""
property_controller.py -- v2 workflow, built on Google ADK's own graph engine.

Where workflow/controller.py (v1) is a hand-written Python function that
calls each agent and branches with if/else, this version expresses the
same 8-phase / 10-gate business workflow as an actual
`google.adk.workflow.Workflow` graph: LlmAgent nodes and small
deterministic FunctionNode gates, wired together with conditional edges.
ADK's own Runner drives execution, routing, and event streaming -- this
module only *defines* the graph and the gate logic, it doesn't run a
manual call/inspect/branch loop itself.

Still explicitly NOT a `SequentialAgent`: the branching this workflow
needs (complete? mismatch? vendor approved? PII? material hazard?
confidence? approve/decline/escalate/override? contradicts hazard?
exceeds authority? senior approve?) requires the conditional-edge graph
API (`Workflow(edges=[..., (gate, {route: node, ...}), ...])`), which is
what's used here -- a gate node signals its branch by returning
`Event(route=...)`.

Every business agent is reused unchanged from agents/*.py (same
instruction, same output_schema -- see agents/__init__.py for why every
agent here is tools-free and output_schema-only). This file adds the
FunctionNode steps that don't call an LLM -- parsing, hazard/mismatch
detection, vendor/PII/CAT checks, risk scoring, pricing, delegated
authority, communication drafting, and final decision assembly -- each
backed by the corresponding tool in tools/.

Shared state (applicant data, audit trail, each step's result) is carried
via `ctx.state` -- ADK's own per-run state store -- because an LlmAgent
node's output is only its own structured response, not an echo of
whatever it was given; anything that needs to survive past an LLM node
has to be written to ctx.state explicitly and read back afterwards.

Every FunctionNode and LlmAgent node here also emits progress events via
a workflow.progress.ProgressTracker stashed in ctx.state -- so the same
live before/after view Streamlit gets from v1 is available from this
graph-native version too.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from google.adk import Context, Event
from google.adk.agents import LlmAgent
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
from services.normalizer import MANDATORY_LABELS, find_missing_mandatory_fields, normalize
from services.pdf_parser import parse_pdf_document
from tools.cat_vendor_tool import call_cat_vendor
from tools.communication_tool import draft_email
from tools.decision_assembly_tool import assemble_final_decision
from tools.delegated_authority_tool import check_delegated_authority
from tools.hazard_detection_tool import detect_hazards
from tools.mismatch_detection_tool import detect_mismatches
from tools.pii_redaction_tool import redact_pii
from tools.pricing_tool import calculate_pricing
from tools.property_risk_scoring_tool import score_property_risk
from tools.vendor_approval_tool import check_vendor_approval
from workflow.governance import governance_policy_check
from workflow.progress import ProgressTracker

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIDENCE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Small helpers (same role as adk_controller.py's _parse / _save_json)
# ---------------------------------------------------------------------------

def _parse(node_input: Any) -> Dict[str, Any]:
    """LlmAgent nodes with output_schema emit either a parsed dict
    (event.output) or JSON text, depending on ADK version -- normalize
    either into a dict here."""
    if isinstance(node_input, dict):
        return node_input
    text = node_input.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


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


def _fresh_agent(module, unique_name: str) -> LlmAgent:
    """Several agents (HumanUnderwriterAgent, SeniorUnderwriterAgent) are
    reached from more than one branch. Graph nodes need unique names, so
    each branch gets its own LlmAgent instance -- same instruction and
    output_schema as the module's build_agent(), just a distinct node name."""
    template = module.build_agent()
    return LlmAgent(name=unique_name, model=template.model, instruction=template.instruction,
                     output_schema=template.output_schema)


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
    deterministic_missing = find_missing_mandatory_fields(applicant)

    tracker.completed("PHASE_1_SUBMISSION_INTAKE", "parse_submission")
    ctx.state.update({
        "file_path": file_path,
        "applicant_fields": applicant.raw_fields,
        "applicant": applicant,
        "application_id": applicant.proposal_number,
        "deterministic_missing": deterministic_missing,
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
    return {
        "applicant_fields": applicant.raw_fields,
        "mandatory_fields": list(MANDATORY_LABELS.values()),
        "deterministic_missing_fields_check": deterministic_missing,
    }


@node
def submission_gate(ctx: Context, node_input: str):
    result = _parse(node_input)
    deterministic_missing = ctx.state.get("deterministic_missing", [])
    missing = sorted(set(result.get("missing_fields", [])) | set(deterministic_missing))
    complete = len(missing) == 0

    ctx.state["agents_executed"] = ctx.state.get("agents_executed", 0) + 1
    ctx.state["completeness_result"] = {"complete": complete, "missing_fields": missing, "confidence": result.get("confidence", 0.85)}
    ctx.state["audit_trail"].append(
        "Submission validated as complete." if complete else f"Mandatory fields missing: {missing}"
    )
    ctx.state["approval_lineage"].append({"actor": "SubmissionIntakeAgent", "action": "COMPLETE" if complete else "INCOMPLETE"})

    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_1_SUBMISSION_INTAKE", "Decision1_SubmissionComplete", str(complete))

    return Event(route="complete" if complete else "incomplete", output={"__ctx_marker__": True})


@node
def handle_incomplete(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    missing = ctx.state["completeness_result"]["missing_fields"]
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
                         "confidence": ctx.state["completeness_result"].get("confidence", 0.9),
                         "conditions": [], "reason": "Missing mandatory fields."},
        decision_evidence=[f"Missing mandatory field: {f}" for f in missing],
    )


# ---------------------------------------------------------------------------
# PHASE 2 -- Document Intelligence
# ---------------------------------------------------------------------------

@node
def document_intelligence_step(ctx: Context, node_input):
    """Deterministic pre-step (linking + hazard/mismatch scan) feeding the
    DocumentIntelligenceAgent LlmAgent node that follows it in the graph."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)

    linked = find_linked_documents(applicant.proposal_number, data_dir=DATA_DIR)
    linked_html = linked_documents_as_dict(linked)
    ctx.state["linked_documents"] = [{"doc_type": d.doc_type, "file_path": d.file_path} for d in linked]

    hazard_scan = detect_hazards(applicant.raw_fields, progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "hazard_detection_tool"))
    mismatch_scan = detect_mismatches(applicant.raw_fields, linked_html, progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "mismatch_detection_tool"))

    ctx.state["hazard_scan"] = hazard_scan
    ctx.state["mismatch_scan"] = mismatch_scan

    return {
        "applicant_fields": applicant.raw_fields,
        "deterministic_hazard_scan": hazard_scan,
        "deterministic_mismatch_scan": mismatch_scan,
        "linked_documents": [d.doc_type for d in linked],
    }


@node
def document_gate(ctx: Context, node_input: str):
    result = _parse(node_input)
    deterministic_issues = ctx.state["mismatch_scan"].get("issues", [])
    issues = list(result.get("issues", []))
    known_fields = {i.get("field") for i in issues}
    for issue in deterministic_issues:
        if issue.get("field") not in known_fields:
            issues.append(issue)
    mismatch = len(issues) > 0

    ctx.state["agents_executed"] += 1
    ctx.state["doc_intel"] = {"disclosure_mismatch": mismatch, "issues": issues,
                               "extracted_hazards": result.get("extracted_hazards", []), "notes": result.get("notes", [])}
    ctx.state["audit_trail"].append(
        f"Disclosure mismatch(es) detected: {issues}" if mismatch else "No disclosure mismatch found."
    )
    ctx.state["approval_lineage"].append({"actor": "DocumentIntelligenceAgent", "action": "MISMATCH" if mismatch else "CONSISTENT"})

    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_2_DOCUMENT_INTELLIGENCE", "Decision2_DisclosureMismatch", str(mismatch))

    return Event(route="mismatch" if mismatch else "consistent", output={"__ctx_marker__": True})


@node
def governance_and_mandatory_review(ctx: Context, node_input):
    """Deterministic governance stub, then routes into a fresh
    HumanUnderwriterAgent instance for the mandatory review."""
    applicant = ctx.state["applicant"]
    governance_result = governance_policy_check("disclosure_mismatch", {
        "proposal_number": applicant.proposal_number, "issues": ctx.state["doc_intel"]["issues"],
    })
    ctx.state["governance_history"].append(governance_result)
    ctx.state["governance_checks"] = ctx.state.get("governance_checks", 0) + 1
    ctx.state["audit_trail"].append("Governance Policy Check logged -- routed to mandatory human review.")

    return {
        "applicant_fields": applicant.raw_fields,
        "document_intelligence": ctx.state["doc_intel"],
        "cat_exposure": {}, "risk_summary": {}, "pricing": {},
    }


@node
def mismatch_review_gate(ctx: Context, node_input: str):
    review = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["human_reviews"] = ctx.state.get("human_reviews", 0) + 1
    ctx.state["mismatch_review"] = review
    ctx.state["approval_lineage"].append({"actor": "HumanUnderwriterAgent", "action": review.get("action", "Escalate")})

    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_2_DOCUMENT_INTELLIGENCE", "Decision2b_MandatoryReviewAction", review.get("action", "Escalate"))

    action = review.get("action", "Escalate")
    route = {"Decline": "decline", "Escalate": "escalate"}.get(action, "continue")
    return Event(route=route, output={"__ctx_marker__": True})


@node
def handle_mismatch_decline(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    review = ctx.state["mismatch_review"]
    tracker = _tracker(ctx)
    email = draft_email(
        trigger="rejection", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=review.get("reason", ""), output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    return _finalize(
        ctx, status="STOPPED_MISMATCH", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
        recommendation={"action": "DECLINE", "basis": "Disclosure mismatch", "confidence": 0.9,
                         "conditions": [], "reason": review.get("reason", "")},
        decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in ctx.state["doc_intel"]["issues"]],
    )


@node
def mismatch_continue(ctx: Context, node_input):
    """Mismatch was reviewed and Approved/Overridden -- draft the (unsent)
    clarification email and continue the pipeline into Phase 3."""
    applicant = ctx.state["applicant"]
    review = ctx.state["mismatch_review"]
    tracker = _tracker(ctx)
    action_past_tense = {"Approve": "approved", "Override": "overridden"}.get(review.get("action"), "reviewed")
    email = draft_email(
        trigger="disclosure_mismatch", proposal_number=applicant.proposal_number, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=f"Reviewed and {action_past_tense} by underwriter.",
        context={"mismatches": ctx.state["doc_intel"]["issues"]}, output_dir=OUTPUT_DIR,
        progress_callback=tracker.tool_callback("PHASE_2_DOCUMENT_INTELLIGENCE", "communication_tool"),
    )
    if email["success"]:
        ctx.state["email_references"].append(email["reference"])
    ctx.state["audit_trail"].append(f"Human Underwriter action on mismatch: {review.get('action')}. Continuing pipeline.")
    return {"file_path": ctx.state["file_path"]}


# ---------------------------------------------------------------------------
# PHASE 3 -- CAT Exposure
# ---------------------------------------------------------------------------

@node
def cat_vendor_gate(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    vendor_approval = check_vendor_approval(applicant.cat_vendor, progress_callback=tracker.tool_callback("PHASE_3_CAT_EXPOSURE", "vendor_approval_tool"))
    ctx.state["vendor_approval"] = vendor_approval

    tracker.gate_decision("PHASE_3_CAT_EXPOSURE", "Decision3_VendorApproved", str(vendor_approval["approved"]))
    return Event(route="approved" if vendor_approval["approved"] else "blocked", output={"__ctx_marker__": True})


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


@node
def pii_and_cat_call(ctx: Context, node_input):
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)

    pii_result = redact_pii(applicant.raw_fields, progress_callback=tracker.tool_callback("PHASE_3_CAT_EXPOSURE", "pii_redaction_tool"))
    tracker.gate_decision("PHASE_3_CAT_EXPOSURE", "Decision4_PayloadContainsPII", str(pii_result["pii_found"]))
    ctx.state["audit_trail"].append(
        "PII redacted before CAT vendor call." if pii_result["pii_found"] else "No PII found in CAT vendor payload."
    )

    cat_result = call_cat_vendor(
        applicant.cat_vendor, pii_result["redacted_payload"],
        applicant.flood_zone, applicant.earthquake_zone, applicant.cyclone_zone, applicant.wildfire_zone,
        progress_callback=tracker.tool_callback("PHASE_3_CAT_EXPOSURE", "cat_vendor_tool"),
    )
    ctx.state["cat_result"] = cat_result
    ctx.state["cat_results"] = {**cat_result, "vendor_approved": True, "pii_redacted": pii_result["pii_found"]}

    return {
        "vendor_approval": ctx.state["vendor_approval"],
        "pii_redaction": pii_result,
        "cat_result": cat_result,
    }


@node
def cat_exposure_step_done(ctx: Context, node_input: str):
    result = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["cat_exposure"] = result
    ctx.state["approval_lineage"].append({"actor": "CATExposureAgent", "action": result.get("cat_category", "LOW")})

    # Deterministic risk scoring runs here, right after CAT results are
    # known, so its output can be handed straight to RiskSummaryAgent next.
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)
    risk_score_result = score_property_risk(
        applicant.raw_fields, len(ctx.state["hazard_scan"]["hazards_declared"]),
        len(ctx.state["doc_intel"]["issues"]), ctx.state["cat_result"]["cat_score"],
        applicant.previous_claims_count, progress_callback=tracker.tool_callback("PHASE_4_RISK_ASSESSMENT", "property_risk_scoring_tool"),
    )
    ctx.state["risk_score_result"] = risk_score_result

    return {
        "risk_score_result": risk_score_result,
        "hazard_scan": ctx.state["hazard_scan"],
        "mismatch_scan": ctx.state["mismatch_scan"],
        "cat_result": ctx.state["cat_result"],
    }


# ---------------------------------------------------------------------------
# PHASE 4 -- Risk Assessment
# ---------------------------------------------------------------------------

@node
def pricing_step(ctx: Context, node_input: str):
    result = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["risk_summary"] = {
        "risk_score": ctx.state["risk_score_result"]["risk_score"],
        "risk_category": ctx.state["risk_score_result"]["risk_category"],
        "material_risk": ctx.state["risk_score_result"]["material_risk"],
        "confidence": result.get("confidence", 0.85),
        "summary": result.get("summary", ""), "reasoning": result.get("reasoning", []),
    }
    ctx.state["approval_lineage"].append({"actor": "RiskSummaryAgent", "action": ctx.state["risk_summary"]["risk_category"]})
    ctx.state["audit_trail"].append(
        f"Risk assessed: score={ctx.state['risk_summary']['risk_score']}, "
        f"category={ctx.state['risk_summary']['risk_category']}, confidence={ctx.state['risk_summary']['confidence']}."
    )
    tracker = _tracker(ctx)

    applicant = ctx.state["applicant"]
    pricing_result = calculate_pricing(
        str(applicant.total_insured_value or 0), ctx.state["risk_summary"]["risk_category"], ctx.state["risk_summary"]["material_risk"],
        applicant.deductible or "", progress_callback=tracker.tool_callback("PHASE_4_RISK_ASSESSMENT", "pricing_tool"),
    )
    ctx.state["pricing_result"] = pricing_result
    return {
        "pricing_result": pricing_result,
        "risk_category": ctx.state["risk_summary"]["risk_category"],
        "material_risk": ctx.state["risk_summary"]["material_risk"],
    }


@node
def risk_gate(ctx: Context, node_input: str):
    result = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["pricing"] = {
        "recommendation": result.get("recommendation", ctx.state["pricing_result"].get("recommendation", "")),
        "indicative_premium": ctx.state["pricing_result"].get("indicative_premium"),
        "deductible": ctx.state["pricing_result"].get("deductible"),
        "rationale": result.get("rationale", []),
    }
    ctx.state["approval_lineage"].append({"actor": "PricingAgent", "action": "PRICED"})

    material_risk = ctx.state["risk_summary"]["material_risk"]
    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_4_RISK_ASSESSMENT", "Decision5_MaterialHazard", str(material_risk))
    if material_risk:
        low_confidence = ctx.state["risk_summary"].get("confidence", 1.0) < CONFIDENCE_THRESHOLD
        tracker.gate_decision("PHASE_4_RISK_ASSESSMENT", "Decision6_LowConfidence", str(low_confidence))
        if low_confidence:
            ctx.state["audit_trail"].append("Material hazard with confidence below threshold -- senior underwriter signoff will be required.")

    applicant = ctx.state["applicant"]
    return Event(route="continue", output={
        "applicant_fields": applicant.raw_fields,
        "document_intelligence": ctx.state["doc_intel"],
        "cat_exposure": ctx.state["cat_exposure"],
        "risk_summary": ctx.state["risk_summary"],
        "pricing": ctx.state["pricing"],
    })


# ---------------------------------------------------------------------------
# PHASE 5 -- Human Underwriter
# ---------------------------------------------------------------------------

@node
def human_underwriter_gate(ctx: Context, node_input: str):
    result = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["human_reviews"] = ctx.state.get("human_reviews", 0) + 1
    ctx.state["human_underwriter_result"] = result
    ctx.state["approval_lineage"].append({"actor": "HumanUnderwriterAgent", "action": result.get("action", "Escalate")})

    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_5_HUMAN_UNDERWRITER", "Decision7_UnderwriterAction", result.get("action", "Escalate"))

    action = result.get("action", "Escalate")
    route = {"Approve": "approve", "Decline": "decline", "Escalate": "escalate", "Override": "override"}.get(action, "escalate")
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
def override_gate(ctx: Context, node_input):
    material_risk = ctx.state["risk_summary"]["material_risk"]
    tracker = _tracker(ctx)
    ctx.state["audit_trail"].append(f"Override submitted by underwriter: {ctx.state['human_underwriter_result']['reason']}")
    tracker.gate_decision("PHASE_6_OVERRIDE", "Decision8_OverrideContradictsMaterialHazard", str(material_risk))
    return Event(route="contradicts" if material_risk else "clean", output={"__ctx_marker__": True})


@node
def authority_gate(ctx: Context, node_input):
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

@node
def senior_underwriter_prep(ctx: Context, node_input):
    """Feeds whichever fresh SeniorUnderwriterAgent instance follows it
    (reached from Phase 2 mismatch-escalate, Phase 5 escalate, or Phase 6
    authority-exceeded -- see _build_graph())."""
    applicant = ctx.state["applicant"]
    return {
        "applicant_fields": applicant.raw_fields,
        "risk_summary": ctx.state.get("risk_summary", {}),
        "pricing": ctx.state.get("pricing", {}),
        "human_underwriter_result": ctx.state.get("human_underwriter_result") or ctx.state.get("mismatch_review", {}),
        "authority_check": ctx.state.get("authority_check", {}),
    }


@node
def senior_gate(ctx: Context, node_input: str):
    result = _parse(node_input)
    ctx.state["agents_executed"] += 1
    ctx.state["human_reviews"] = ctx.state.get("human_reviews", 0) + 1
    ctx.state["senior_result"] = result
    ctx.state["approval_lineage"].append({"actor": "SeniorUnderwriterAgent", "action": "APPROVE" if result.get("approve") else "REJECT"})

    tracker = _tracker(ctx)
    tracker.gate_decision("PHASE_7_SENIOR_UNDERWRITER", "Decision10_SeniorApprove", str(result.get("approve", False)))

    return Event(route="approve" if result.get("approve") else "reject", output={"__ctx_marker__": True})


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
    """Deterministic step -- backed by tools/decision_assembly_tool.py.
    Called directly by every terminal FunctionNode above (not itself a
    graph node) exactly like adk_controller.py's _finalize()."""
    applicant = ctx.state["applicant"]
    tracker = _tracker(ctx)

    # The Evidence Generation Agent is invoked as a plain synchronous call
    # here rather than a graph node, since every path through this graph
    # converges on _finalize() and a graph edge can't fan every terminal
    # node into one shared downstream LlmAgent node without duplicating it
    # per branch -- calling it directly keeps Phase 8 in one place.
    from workflow.adk_runtime import call_agent
    evidence_agent = evidence_generation_agent.build_agent()
    ai_summary = call_agent(evidence_agent, {
        "applicant_fields": applicant.raw_fields,
        "document_intelligence": ctx.state.get("doc_intel", {}),
        "cat_exposure": ctx.state.get("cat_exposure", {}),
        "risk_summary": ctx.state.get("risk_summary", {}),
        "pricing": ctx.state.get("pricing", {}),
        "final_decision_context": {"status": status, "decision_mode": decision_mode,
                                    "decision_maker": decision_maker, "recommendation": recommendation},
    }, progress_callback=tracker.agent_callback("PHASE_8_FINAL_DECISION")).get("ai_summary", "")
    ctx.state["agents_executed"] += 1

    scenario = os.path.splitext(os.path.basename(ctx.state["file_path"]))[0]

    decision = assemble_final_decision(
        application_id=ctx.state.get("application_id"),
        status=status, scenario=scenario, current_phase="PHASE_8_FINAL_DECISION",
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
        progress_callback=tracker.tool_callback("PHASE_8_FINAL_DECISION", "decision_assembly_tool"),
    )
    ctx.state["final_decision"] = decision
    return decision


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _build_graph() -> Workflow:
    submission_llm = submission_intake_agent.build_agent()
    document_llm = document_intelligence_agent.build_agent()
    cat_llm = cat_exposure_agent.build_agent()
    risk_llm = risk_summary_agent.build_agent()
    pricing_llm = pricing_agent.build_agent()

    human_underwriter_llm = _fresh_agent(human_underwriter_agent, "HumanUnderwriterAgent_Phase5")
    human_underwriter_mismatch_llm = _fresh_agent(human_underwriter_agent, "HumanUnderwriterAgent_MandatoryReview")

    senior_underwriter_mismatch_llm = _fresh_agent(senior_underwriter_agent, "SeniorUnderwriterAgent_Mismatch")
    senior_underwriter_escalate_llm = _fresh_agent(senior_underwriter_agent, "SeniorUnderwriterAgent_Escalate")
    senior_underwriter_authority_llm = _fresh_agent(senior_underwriter_agent, "SeniorUnderwriterAgent_Authority")

    return Workflow(
        name="commercial_property_underwriting_v2",
        edges=[
            ("START", intake, submission_llm, submission_gate),
            (submission_gate, {"complete": document_intelligence_step, "incomplete": handle_incomplete}),

            (document_intelligence_step, document_llm, document_gate),
            (document_gate, {"consistent": cat_vendor_gate, "mismatch": governance_and_mandatory_review}),

            (governance_and_mandatory_review, human_underwriter_mismatch_llm, mismatch_review_gate),
            (mismatch_review_gate, {
                "decline": handle_mismatch_decline,
                "escalate": senior_underwriter_prep,
                "continue": mismatch_continue,
            }),
            (mismatch_continue, cat_vendor_gate),

            (cat_vendor_gate, {"blocked": handle_vendor_blocked, "approved": pii_and_cat_call}),
            (pii_and_cat_call, cat_llm, cat_exposure_step_done, risk_llm),
            (risk_llm, pricing_step, pricing_llm, risk_gate),

            (risk_gate, human_underwriter_llm, human_underwriter_gate),
            (human_underwriter_gate, {
                "approve": handle_approve,
                "decline": handle_decline,
                "escalate": senior_underwriter_prep,
                "override": override_gate,
            }),

            (override_gate, {"clean": accept_override, "contradicts": authority_gate}),
            (authority_gate, {"within": accept_override, "exceeds": senior_underwriter_prep}),

            # senior_underwriter_prep is reached from three branches above;
            # each uses its own fresh LlmAgent instance so the graph never
            # reuses one node object across multiple in-edges.
            (senior_underwriter_prep, senior_underwriter_mismatch_llm, senior_gate),
            (senior_underwriter_prep, senior_underwriter_escalate_llm, senior_gate),
            (senior_underwriter_prep, senior_underwriter_authority_llm, senior_gate),
            (senior_gate, {"approve": senior_approve, "reject": senior_reject}),
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
