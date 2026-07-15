"""
workflow/controller.py -- v1 workflow, hand-rolled Python orchestration.

Sequences the 8 business agents in the exact order the flowchart
requires, evaluates all 10 decision gates itself in plain Python, and
assembles the final decision.json + email drafts. Deliberately NOT a
google.adk SequentialAgent / simple chain: this module owns the shared
WorkflowState and makes every routing decision explicitly and auditably
in Python.

Tool calling model: every business tool (hazard/mismatch detection,
vendor approval, PII redaction, the CAT vendor call, risk scoring,
pricing) is now called by the *agent itself* via real LLM-directed
function calling (`tools=[...]` on each LlmAgent in agents/*.py) rather
than pre-computed here as a FunctionNode-style step. Each agent's run()
still re-runs its deterministic tool(s) itself as a belt-and-braces check
before returning, so a routing-critical field (complete, disclosure_
mismatch, vendor_approved, material_risk, ...) is guaranteed correct even
if the model skipped or misreported a tool call.

"Python determines routing" still holds: every if/else branch below is
still plain Python, reading the *result* an agent's own tool call
produced rather than a value this controller computed itself. The one
exception is Decision 9 (override exceeds delegated authority?) in Phase
6, which stays a direct deterministic call here -- it's the predicate for
*whether to reach* Phase 7 at all, so it can't live inside the Phase 7
agent it's gating access to.

See workflow/property_controller.py (v2) for the same business workflow
expressed as a real google.adk.workflow.Workflow graph (not yet updated
to this tool-calling model -- see the note at the end of this file).

Every tool call, agent call, and gate decision fires a progress event via
the ProgressTracker passed in (or a no-op tracker if none is given), so a
caller (Streamlit, a test) can observe every before/after step live.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
from workflow.state import WorkflowState

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

CONFIDENCE_THRESHOLD = 0.75


def _parse_and_normalize(file_path: str):
    extension = os.path.splitext(file_path)[1].lower()
    if extension in (".html", ".htm"):
        raw = load_and_parse_html(file_path)
    elif extension == ".pdf":
        raw = parse_pdf_document(file_path)
    else:
        raise ValueError(f"Unsupported proposal format: {extension}")
    return normalize(raw), raw


def run_workflow(file_path: str, tracker: Optional[ProgressTracker] = None) -> Dict[str, Any]:
    tracker = tracker or ProgressTracker()
    state = WorkflowState(file_path=file_path, workflow_id=str(uuid.uuid4()))
    state.started_at = datetime.now(timezone.utc).isoformat()

    # ======================================================================
    # PHASE 1 -- Submission Intake
    # ======================================================================
    state.current_phase = "PHASE_1_SUBMISSION_INTAKE"
    with tracker.step(state.current_phase, "parse_submission"):
        applicant, raw = _parse_and_normalize(file_path)
    state.submission = applicant
    application_id = applicant.proposal_number
    state.log("Submission received and parsed.")

    with tracker.step(state.current_phase, "SubmissionIntakeAgent"):
        state.agents_executed += 1
        completeness = submission_intake_agent.run(
            applicant.raw_fields,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.record_lineage("SubmissionIntakeAgent", "COMPLETE" if completeness["complete"] else "INCOMPLETE")

    # ---- Decision 1: Is submission complete? ----
    tracker.gate_decision(state.current_phase, "Decision1_SubmissionComplete", str(completeness["complete"]))
    if not completeness["complete"]:
        state.log(f"Mandatory fields missing: {completeness['missing_fields']}")
        email = draft_email(
            trigger="incomplete_submission",
            proposal_number=application_id,
            insured_name=applicant.business_name,
            broker_name=applicant.broker_name,
            reason=f"Missing mandatory fields: {', '.join(completeness['missing_fields'])}",
            required_action="Provide the missing fields and resubmit.",
            context={"missing_fields": completeness["missing_fields"]},
            output_dir=OUTPUT_DIR,
            progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
        )
        if email["success"]:
            state.email_references.append(email["reference"])
        return _finalize(
            state, application_id, status="STOPPED_INCOMPLETE",
            decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
            recommendation={"action": "REQUEST_MORE_INFORMATION", "basis": "Incomplete submission",
                             "confidence": completeness.get("confidence", 0.9), "conditions": [], "reason": "Missing mandatory fields."},
            decision_evidence=[f"Missing mandatory field: {f}" for f in completeness["missing_fields"]],
            tracker=tracker,
        )
    state.log("Submission validated as complete.")

    # ======================================================================
    # PHASE 2 -- Document Intelligence
    # ======================================================================
    state.current_phase = "PHASE_2_DOCUMENT_INTELLIGENCE"
    with tracker.step(state.current_phase, "document_linker"):
        linked = find_linked_documents(application_id, data_dir=DATA_DIR)
    state.linked_documents = [{"doc_type": d.doc_type, "file_path": d.file_path} for d in linked]
    linked_html = linked_documents_as_dict(linked)

    with tracker.step(state.current_phase, "DocumentIntelligenceAgent"):
        state.agents_executed += 1
        doc_intel = document_intelligence_agent.run(
            applicant.raw_fields, linked_html,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.hazards = doc_intel["extracted_hazards"]
    state.disclosure_mismatches = doc_intel["issues"]
    state.record_lineage("DocumentIntelligenceAgent", "MISMATCH" if doc_intel["disclosure_mismatch"] else "CONSISTENT")

    # ---- Decision 2: Any disclosure mismatch found? ----
    tracker.gate_decision(state.current_phase, "Decision2_DisclosureMismatch", str(doc_intel["disclosure_mismatch"]))
    if doc_intel["disclosure_mismatch"]:
        state.log(f"Disclosure mismatch(es) detected: {doc_intel['issues']}")
        governance_result = governance_policy_check("disclosure_mismatch", {"proposal_number": application_id, "issues": doc_intel["issues"]})
        state.governance_history.append(governance_result)
        state.governance_checks += 1
        state.log("Governance Policy Check logged -- routed to mandatory human review.")

        with tracker.step(state.current_phase, "HumanUnderwriterAgent_MandatoryReview"):
            state.agents_executed += 1
            state.human_reviews += 1
            human_underwriter_result = human_underwriter_agent.run(
                applicant.raw_fields, doc_intel, {}, {}, {},
                progress_callback=tracker.agent_callback(state.current_phase),
            )
        state.human_actions.append(human_underwriter_result)
        state.record_lineage("HumanUnderwriterAgent", human_underwriter_result["action"])

        if human_underwriter_result["action"] == "Decline":
            email = draft_email(
                trigger="rejection", proposal_number=application_id, insured_name=applicant.business_name,
                broker_name=applicant.broker_name, reason=human_underwriter_result["reason"],
                output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
            )
            if email["success"]:
                state.email_references.append(email["reference"])
            return _finalize(
                state, application_id, status="STOPPED_MISMATCH",
                decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
                recommendation={"action": "DECLINE", "basis": "Disclosure mismatch", "confidence": 0.9,
                                 "conditions": [], "reason": human_underwriter_result["reason"]},
                decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in doc_intel["issues"]],
                tracker=tracker,
            )
        elif human_underwriter_result["action"] == "Escalate":
            return _handle_senior_escalation(
                state, application_id, applicant, doc_intel, {}, {}, human_underwriter_result,
                escalation_reason="Mandatory mismatch review escalated by Human Underwriter.",
                unique_name="SeniorUnderwriterAgent_Mismatch", tracker=tracker,
            )
        _ACTION_PAST_TENSE = {"Approve": "approved", "Override": "overridden", "Escalate": "escalated"}
        email = draft_email(
            trigger="disclosure_mismatch", proposal_number=application_id, insured_name=applicant.business_name,
            broker_name=applicant.broker_name,
            reason=f"Reviewed and {_ACTION_PAST_TENSE.get(human_underwriter_result['action'], 'reviewed')} by underwriter.",
            context={"mismatches": doc_intel["issues"]}, output_dir=OUTPUT_DIR,
            progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
        )
        if email["success"]:
            state.email_references.append(email["reference"])
        state.log(f"Human Underwriter action on mismatch: {human_underwriter_result['action']}. Continuing pipeline.")
    else:
        state.log("No disclosure mismatch found.")

    # ======================================================================
    # PHASE 3 -- CAT Exposure
    # ======================================================================
    state.current_phase = "PHASE_3_CAT_EXPOSURE"
    vendor_name = applicant.cat_vendor

    with tracker.step(state.current_phase, "CATExposureAgent"):
        state.agents_executed += 1
        cat_exposure = cat_exposure_agent.run(
            vendor_name, applicant.raw_fields,
            applicant.flood_zone, applicant.earthquake_zone, applicant.cyclone_zone, applicant.wildfire_zone,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.record_lineage("CATExposureAgent", cat_exposure["cat_category"])

    # ---- Decision 3: Is external vendor approved? ----
    # (Now decided inside CATExposureAgent's own tool-call sequence --
    # its instruction tells it to stop after check_vendor_approval if the
    # vendor isn't approved, and run()'s belt-and-braces check forces
    # cat_score=0/LOW regardless of what the model actually did. Routing
    # here reads that outcome rather than pre-branching before the call.)
    tracker.gate_decision(state.current_phase, "Decision3_VendorApproved", str(cat_exposure["vendor_approved"]))
    if not cat_exposure["vendor_approved"]:
        state.log(f"CAT vendor '{vendor_name}' is not on the approved-vendor list -- API call blocked.")
        email = draft_email(
            trigger="cat_vendor_blocked", proposal_number=application_id, insured_name=applicant.business_name,
            broker_name=applicant.broker_name, reason=f"CAT vendor '{vendor_name}' is not approved.",
            output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
        )
        if email["success"]:
            state.email_references.append(email["reference"])
        return _finalize(
            state, application_id, status="STOPPED_MISMATCH",
            decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
            recommendation={"action": "ESCALATE", "basis": "CAT vendor not approved", "confidence": 0.9,
                             "conditions": [], "reason": f"Vendor '{vendor_name}' is not on the approved list."},
            decision_evidence=[f"CAT vendor '{vendor_name}' is not approved."],
            tracker=tracker,
        )

    # ---- Decision 4: Does payload contain PII? ----
    # (Also decided inside CATExposureAgent's tool sequence -- redact_pii
    # always runs before call_cat_vendor per its instruction; the gate
    # here only affects the audit note.)
    tracker.gate_decision(state.current_phase, "Decision4_PayloadContainsPII", str(cat_exposure["pii_redacted"]))
    state.log("PII redacted before CAT vendor call." if cat_exposure["pii_redacted"] else "No PII found in CAT vendor payload.")

    state.cat_results = {
        "vendor": vendor_name, "cat_score": cat_exposure["cat_score"], "cat_category": cat_exposure["cat_category"],
        "vendor_approved": cat_exposure["vendor_approved"], "pii_redacted": cat_exposure["pii_redacted"],
    }

    # ======================================================================
    # PHASE 4 -- Risk Assessment
    # ======================================================================
    state.current_phase = "PHASE_4_RISK_ASSESSMENT"
    with tracker.step(state.current_phase, "RiskSummaryAgent"):
        state.agents_executed += 1
        risk_summary = risk_summary_agent.run(
            applicant.raw_fields, len(state.hazards), len(state.disclosure_mismatches),
            cat_exposure["cat_score"], applicant.previous_claims_count,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.risk_summary = risk_summary
    state.record_lineage("RiskSummaryAgent", risk_summary["risk_category"])

    with tracker.step(state.current_phase, "PricingAgent"):
        state.agents_executed += 1
        pricing = pricing_agent.run(
            str(applicant.total_insured_value or 0), risk_summary["risk_category"], risk_summary["material_risk"],
            applicant.deductible or "", progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.pricing = pricing
    state.record_lineage("PricingAgent", "PRICED")

    # ---- Decision 5: Material hazard exists? / Decision 6: Confidence < threshold? ----
    material_risk = risk_summary["material_risk"]
    tracker.gate_decision(state.current_phase, "Decision5_MaterialHazard", str(material_risk))
    if material_risk:
        senior_signoff_required = risk_summary.get("confidence", 1.0) < CONFIDENCE_THRESHOLD
        tracker.gate_decision(state.current_phase, "Decision6_LowConfidence", str(senior_signoff_required))
        if senior_signoff_required:
            state.log("Material hazard with confidence below threshold -- senior underwriter signoff will be required.")

    is_clean_case = (not material_risk) and (not doc_intel["disclosure_mismatch"]) and risk_summary.get("confidence", 0) >= CONFIDENCE_THRESHOLD

    # ======================================================================
    # STP (Straight-Through Processing) bypass
    # ======================================================================
    # FIX: A clean case (no material hazard, no disclosure mismatch,
    # confidence at/above threshold) used to run through PHASE 5 -- Human
    # Underwriter exactly like every other case (the mocked
    # HumanUnderwriterAgent was called, state.human_reviews was
    # incremented, and "HumanUnderwriterAgent" was appended to
    # approval_lineage) and only AFTERWARD got relabeled
    # decision_mode="AUTONOMOUS"/decision_maker="AI" for the final JSON.
    # That's self-contradictory: workflow_metrics.human_reviews and
    # approval_lineage said a human step happened, while decision_mode said
    # it didn't -- and it defeats the actual purpose of Straight-Through
    # Processing (routing every case through human review regardless of
    # risk removes the "straight-through" part; see the original spec's
    # own framing of proposal_low_risk.html as "a Straight Through
    # Processing (STP) candidate").
    #
    # A clean case now skips Phase 5 (and the agent call) entirely and is
    # approved directly, so decision_mode/decision_maker, human_reviews,
    # and approval_lineage all honestly agree that no human step occurred.
    # Phase 5 now only runs for cases that actually need judgment: any
    # material hazard, any disclosure mismatch, or confidence below
    # threshold.
    if is_clean_case:
        state.current_phase = "PHASE_5_HUMAN_UNDERWRITER"
        stp_reason = (
            "Straight-through processing: no material hazard, no disclosure mismatch, and risk "
            f"assessment confidence ({risk_summary.get('confidence')}) at or above the "
            f"{CONFIDENCE_THRESHOLD} threshold. Approved without human underwriter review."
        )
        tracker.gate_decision(state.current_phase, "Decision7_UnderwriterAction", "Approve (STP)")
        return _finalize(
            state, application_id, status="COMPLETED", decision_mode="AUTONOMOUS", decision_maker="AI",
            recommendation={"action": "APPROVE", "basis": pricing["recommendation"], "confidence": risk_summary.get("confidence"),
                             "conditions": [], "reason": stp_reason},
            decision_evidence=risk_summary.get("reasoning", []),
            tracker=tracker,
        )

    # ======================================================================
    # PHASE 5 -- Human Underwriter
    # ======================================================================
    state.current_phase = "PHASE_5_HUMAN_UNDERWRITER"
    with tracker.step(state.current_phase, "HumanUnderwriterAgent"):
        state.agents_executed += 1
        state.human_reviews += 1
        human_underwriter_result = human_underwriter_agent.run(
            applicant.raw_fields, doc_intel, cat_exposure, risk_summary, pricing,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.human_actions.append(human_underwriter_result)
    state.record_lineage("HumanUnderwriterAgent", human_underwriter_result["action"])

    # ---- Decision 7: Approve / Decline / Override / Escalate? ----
    action = human_underwriter_result["action"]
    tracker.gate_decision(state.current_phase, "Decision7_UnderwriterAction", action)

    if action == "Approve":
        return _finalize(
            state, application_id, status="COMPLETED", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
            recommendation={"action": "APPROVE", "basis": pricing["recommendation"], "confidence": risk_summary.get("confidence"),
                             "conditions": [], "reason": human_underwriter_result["reason"]},
            decision_evidence=risk_summary.get("reasoning", []),
            tracker=tracker,
        )

    if action == "Decline":
        email = draft_email(
            trigger="rejection", proposal_number=application_id, insured_name=applicant.business_name,
            broker_name=applicant.broker_name, reason=human_underwriter_result["reason"],
            output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
        )
        if email["success"]:
            state.email_references.append(email["reference"])
        return _finalize(
            state, application_id, status="REJECTED", decision_mode="HUMAN_REVIEW", decision_maker="Human Underwriter",
            recommendation={"action": "DECLINE", "basis": pricing["recommendation"], "confidence": risk_summary.get("confidence"),
                             "conditions": [], "reason": human_underwriter_result["reason"]},
            decision_evidence=risk_summary.get("reasoning", []),
            tracker=tracker,
        )

    if action == "Escalate":
        return _handle_senior_escalation(
            state, application_id, applicant, doc_intel, risk_summary, pricing, human_underwriter_result,
            escalation_reason="Escalated by Human Underwriter after full risk assessment.",
            unique_name="SeniorUnderwriterAgent_Escalate", tracker=tracker,
        )

    # action == "Override"
    return _handle_override(
        state, application_id, applicant, doc_intel, risk_summary, pricing, human_underwriter_result,
        material_risk, tracker,
    )


# ---------------------------------------------------------------------------
# PHASE 6 -- Override
# ---------------------------------------------------------------------------

def _handle_override(state, application_id, applicant, doc_intel, risk_summary, pricing,
                      human_underwriter_result, material_risk, tracker: ProgressTracker):
    state.current_phase = "PHASE_6_OVERRIDE"
    state.log(f"Override submitted by underwriter: {human_underwriter_result['reason']}")

    # ---- Decision 8: Override contradicts material hazard? ----
    contradicts = bool(material_risk)
    tracker.gate_decision(state.current_phase, "Decision8_OverrideContradictsMaterialHazard", str(contradicts))

    if not contradicts:
        return _accept_override(state, application_id, applicant, risk_summary, pricing, human_underwriter_result, tracker)

    # ---- Decision 9: Exposure exceeds delegated authority? ----
    # Stays a direct deterministic call here (not moved into an agent):
    # it's the routing predicate for *whether Phase 7 is even reached*,
    # so it can't live inside the Phase 7 agent it gates access to.
    # (SeniorUnderwriterAgent separately calls this same tool itself, for
    # its own informational context once it *is* reached -- see
    # agents/senior_underwriter_agent.py.)
    authority_check = check_delegated_authority(
        str(applicant.total_insured_value or 0), role="underwriter",
        progress_callback=tracker.tool_callback(state.current_phase, "delegated_authority_tool"),
    )
    tracker.gate_decision(state.current_phase, "Decision9_ExceedsDelegatedAuthority", str(authority_check["exceeds_authority"]))

    if authority_check["exceeds_authority"]:
        state.log("Override contradicts material hazard and exceeds delegated authority -- escalating to Senior Underwriter.")
        return _handle_senior_escalation(
            state, application_id, applicant, doc_intel, risk_summary, pricing, human_underwriter_result,
            escalation_reason="Override contradicts a material hazard finding and exceeds the underwriter's delegated authority.",
            unique_name="SeniorUnderwriterAgent_Authority", tracker=tracker,
        )

    return _accept_override(state, application_id, applicant, risk_summary, pricing, human_underwriter_result, tracker)


def _accept_override(state, application_id, applicant, risk_summary, pricing, human_underwriter_result, tracker: ProgressTracker):
    state.log("Override accepted within delegated authority.")
    email = draft_email(
        trigger="human_review", proposal_number=application_id, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=f"Override recorded: {human_underwriter_result['reason']}",
        required_action="Management visibility only -- no action required.",
        output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
    )
    if email["success"]:
        state.email_references.append(email["reference"])
    return _finalize(
        state, application_id, status="CONDITIONALLY_APPROVED", decision_mode="OVERRIDE", decision_maker="Human Underwriter",
        recommendation={"action": "OVERRIDE", "basis": pricing.get("recommendation", ""), "confidence": risk_summary.get("confidence"),
                         "conditions": human_underwriter_result.get("conditions", []), "reason": human_underwriter_result["reason"]},
        decision_evidence=risk_summary.get("reasoning", []),
        tracker=tracker,
    )


# ---------------------------------------------------------------------------
# PHASE 7 -- Senior Underwriter
# ---------------------------------------------------------------------------

def _handle_senior_escalation(state, application_id, applicant, doc_intel, risk_summary, pricing,
                               human_underwriter_result, escalation_reason, unique_name, tracker: ProgressTracker):
    state.current_phase = "PHASE_7_SENIOR_UNDERWRITER"
    with tracker.step(state.current_phase, unique_name):
        state.agents_executed += 1
        state.human_reviews += 1
        senior_result = senior_underwriter_agent.run(
            applicant.raw_fields, risk_summary or {}, pricing or {}, human_underwriter_result,
            escalation_reason=escalation_reason, unique_name=unique_name,
            progress_callback=tracker.agent_callback(state.current_phase),
        )
    state.human_actions.append(senior_result)
    state.record_lineage(unique_name, "APPROVE" if senior_result["approve"] else "REJECT")

    # ---- Decision 10: Approve? ----
    tracker.gate_decision(state.current_phase, "Decision10_SeniorApprove", str(senior_result["approve"]))

    if senior_result["approve"]:
        email = draft_email(
            trigger="conditional_approval", proposal_number=application_id, insured_name=applicant.business_name,
            broker_name=applicant.broker_name, reason=senior_result["reason"],
            context={"conditions": senior_result.get("conditions", [])},
            output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
        )
        if email["success"]:
            state.email_references.append(email["reference"])
        return _finalize(
            state, application_id, status="CONDITIONALLY_APPROVED", decision_mode="SENIOR_UNDERWRITER", decision_maker="Senior Underwriter",
            recommendation={"action": "APPROVE", "basis": senior_result["reason"], "confidence": (risk_summary or {}).get("confidence"),
                             "conditions": senior_result.get("conditions", []), "reason": senior_result["reason"]},
            decision_evidence=(risk_summary or {}).get("reasoning", []),
            tracker=tracker,
        )

    trigger = "information_request" if senior_result.get("requested_items") else "rejection"
    email = draft_email(
        trigger=trigger, proposal_number=application_id, insured_name=applicant.business_name,
        broker_name=applicant.broker_name, reason=senior_result["reason"],
        context={"requested_items": senior_result.get("requested_items", [])},
        output_dir=OUTPUT_DIR, progress_callback=tracker.tool_callback(state.current_phase, "communication_tool"),
    )
    if email["success"]:
        state.email_references.append(email["reference"])
    status = "STOPPED_HUMAN_REVIEW" if senior_result.get("requested_items") else "REJECTED"
    action = "REQUEST_MORE_INFORMATION" if senior_result.get("requested_items") else "DECLINE"
    return _finalize(
        state, application_id, status=status, decision_mode="SENIOR_UNDERWRITER", decision_maker="Senior Underwriter",
        recommendation={"action": action, "basis": senior_result["reason"], "confidence": (risk_summary or {}).get("confidence"),
                         "conditions": [], "reason": senior_result["reason"]},
        decision_evidence=(risk_summary or {}).get("reasoning", []),
        tracker=tracker,
    )


# ---------------------------------------------------------------------------
# PHASE 8 -- Final Decision
# ---------------------------------------------------------------------------

def _finalize(state: WorkflowState, application_id, status, decision_mode, decision_maker,
              recommendation, decision_evidence, tracker: ProgressTracker) -> Dict[str, Any]:
    state.current_phase = "PHASE_8_FINAL_DECISION"
    applicant = state.submission

    with tracker.step(state.current_phase, "EvidenceGenerationAgent"):
        state.agents_executed += 1
        ai_summary = evidence_generation_agent.run(
            applicant.raw_fields if applicant else {},
            {"disclosure_mismatch": bool(state.disclosure_mismatches), "issues": state.disclosure_mismatches},
            state.cat_results or {}, state.risk_summary or {}, state.pricing or {},
            {"status": status, "decision_mode": decision_mode, "decision_maker": decision_maker, "recommendation": recommendation},
            progress_callback=tracker.agent_callback(state.current_phase),
        )

    scenario = os.path.splitext(os.path.basename(state.file_path))[0]

    with tracker.step(state.current_phase, "decision_assembly_tool"):
        decision = assemble_final_decision(
            application_id=application_id,
            status=status,
            scenario=scenario,
            current_phase=state.current_phase,
            decision_mode=decision_mode,
            decision_maker=decision_maker,
            risk_category=(state.risk_summary or {}).get("risk_category"),
            risk_score=(state.risk_summary or {}).get("risk_score"),
            confidence=(state.risk_summary or {}).get("confidence"),
            cat_exposure=state.cat_results or {},
            pricing=state.pricing or {},
            recommendation=recommendation,
            decision_evidence=decision_evidence,
            audit_trail=state.audit_trail,
            approval_lineage=state.approval_lineage,
            governance_history=state.governance_history,
            workflow_metrics={
                "agents_executed": state.agents_executed,
                "decision_gates": 10,
                "human_reviews": state.human_reviews,
                "governance_checks": state.governance_checks,
            },
            ai_summary=ai_summary,
            email_references=state.email_references,
            workflow_id=state.workflow_id,
            started_at=state.started_at,
            applicant={
                "business_name": applicant.business_name if applicant else None,
                "broker_name": applicant.broker_name if applicant else None,
                "primary_property_address": applicant.primary_property_address if applicant else None,
                "total_insured_value": applicant.total_insured_value if applicant else None,
                "occupancy_type": applicant.occupancy_type if applicant else None,
            },
            documents=state.linked_documents,
            execution_timeline=tracker.as_list(),
            output_dir=OUTPUT_DIR,
            progress_callback=tracker.tool_callback(state.current_phase, "decision_assembly_tool"),
        )

    state.workflow_status = status
    state.final_decision = decision
    return decision
