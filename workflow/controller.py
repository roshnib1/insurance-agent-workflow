"""
Workflow Controller

Sequences the five Google ADK business agents in the exact order the
business workflow requires, evaluates each decision gate itself, calls the
Governance SDK hook (before_agent/after_agent) around every agent
invocation, and assembles the final decision + audit trail.

Deliberately NOT a google.adk SequentialAgent / simple chain: this module
owns the shared UnderwritingState, reads each agent's structured output,
and makes the routing decisions in plain Python so the branching logic
(complete? consistent? material risk? confidence above threshold?) is
fully explicit and auditable, exactly as specified.
"""

import os
from typing import Optional

from agents import submission_agent, document_agent, risk_agent, recommendation_agent, human_review_agent
from hooks.sdk_hooks import PolicyHook, NoOpPolicyHook
from schemas.models import FinalDecision, to_dict
from services.html_parser import load_and_parse_html
from services.pdf_parser import parse_pdf_proposal
from services.normalizer import normalize
from services.communication_service import (
    draft_missing_information_email,
    draft_disclosure_mismatch_email,
    draft_human_review_information_request,
)
from workflow.state import UnderwritingState

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
UNDERWRITING_CONFIDENCE_THRESHOLD = 0.75


def _parse_and_normalize(file_path: str):
    extension = os.path.splitext(file_path)[1].lower()
    if extension in (".html", ".htm"):
        raw = load_and_parse_html(file_path)
    elif extension == ".pdf":
        raw = parse_pdf_proposal(file_path)
    else:
        raise ValueError(f"Unsupported proposal format: {extension}")
    return normalize(raw)


def _save_json_artifact(filename: str, data: dict) -> str:
    import json
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def run_workflow(file_path: str, policy_hook: Optional[PolicyHook] = None) -> dict:
    hook = policy_hook or NoOpPolicyHook()
    state = UnderwritingState(file_path=file_path)

    # ---------------- Parse + normalize (deterministic service, not an agent) ----------------
    state.proposal_data = _parse_and_normalize(file_path)
    applicant = state.proposal_data
    application_id = applicant.proposal_number

    # ---------------- 1. Submission Intake Agent ----------------
    hook.before_agent("submission_intake", {"file_path": file_path})
    state.completeness_result = submission_agent.run(applicant)
    hook.after_agent("submission_intake", state.completeness_result)
    state.log("Submission received, parsed, and evaluated by Submission Intake Agent.")

    if not state.completeness_result["complete"]:
        missing = state.completeness_result["missing_fields"]
        state.log(f"Mandatory fields missing: {missing}")

        communication = draft_missing_information_email(
            proposal_number=applicant.proposal_number,
            broker_name=applicant.broker_name,
            applicant_name=applicant.applicant_name,
            missing_fields=missing,
        )
        state.communication = to_dict(communication)
        safe_id = (application_id or "UNKNOWN").replace("/", "_")
        state.communication_artifact_path = _save_json_artifact(
            f"email_draft_{safe_id}.json", state.communication
        )
        state.log(f"Draft communication prepared and saved to {state.communication_artifact_path} (not sent).")

        return _finalize(
            state, application_id,
            status="STOPPED_INCOMPLETE",
            recommendation="REQUEST_MORE_INFORMATION",
            decision_evidence=[f"Missing mandatory field: {f}" for f in missing],
        )

    state.log("Submission validated as complete by Submission Intake Agent.")

    # ---------------- 2. Document Intelligence Agent ----------------
    hook.before_agent("document_intelligence", {"proposal_number": application_id})
    state.document_result = document_agent.run(applicant)
    hook.after_agent("document_intelligence", state.document_result)

    if not state.document_result["consistent"]:
        issues = state.document_result["issues"]
        state.log(f"Disclosure mismatch(es) detected: {issues}")

        hook.before_agent("human_review", {"trigger": "disclosure_mismatch"})
        state.human_review_result = human_review_agent.run(
            applicant, trigger="disclosure_mismatch", document_result=state.document_result
        )
        hook.after_agent("human_review", state.human_review_result)
        state.log(
            f"Routed to Human Review. Action: {state.human_review_result['action']}. "
            f"Reason: {state.human_review_result['reason']}"
        )

        if state.human_review_result["action"] == "REQUEST_MORE_INFORMATION":
            communication = draft_disclosure_mismatch_email(
                proposal_number=applicant.proposal_number,
                broker_name=applicant.broker_name,
                applicant_name=applicant.applicant_name,
                mismatches=issues,
            )
            state.communication = to_dict(communication)
            safe_id = (application_id or "UNKNOWN").replace("/", "_")
            state.communication_artifact_path = _save_json_artifact(
                f"email_draft_{safe_id}.json", state.communication
            )
            state.log(f"Draft communication prepared and saved to {state.communication_artifact_path} (not sent).")

        return _finalize(
            state, application_id,
            status="STOPPED_MISMATCH",
            recommendation=state.human_review_result["action"],
            decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in issues],
        )

    state.log("Document Intelligence Agent found no disclosure mismatches.")

    # ---------------- 3. Risk Assessment Agent ----------------
    hook.before_agent("risk_assessment", {"proposal_number": application_id})
    state.risk_result = risk_agent.run(applicant)
    hook.after_agent("risk_assessment", state.risk_result)
    state.log(
        f"Risk assessed: score={state.risk_result['risk_score']}, "
        f"category={state.risk_result['risk_category']}, confidence={state.risk_result['confidence']}."
    )

    if state.risk_result["material_risk"]:
        state.log("Material risk identified -- routing to Human Review.")
        hook.before_agent("human_review", {"trigger": "material_risk"})
        state.human_review_result = human_review_agent.run(
            applicant, trigger="material_risk", risk_result=state.risk_result
        )
        hook.after_agent("human_review", state.human_review_result)
        state.log(
            f"Human Review action: {state.human_review_result['action']}. "
            f"Reason: {state.human_review_result['reason']}"
        )

        if state.human_review_result["action"] == "REQUEST_MORE_INFORMATION":
            requested = state.human_review_result.get("requested_items") or [
                "Updated medical examination report",
                "Detailed claim history / loss run statement",
            ]
            communication = draft_human_review_information_request(
                proposal_number=applicant.proposal_number,
                broker_name=applicant.broker_name,
                applicant_name=applicant.applicant_name,
                requested_items=requested,
                review_reason=state.human_review_result["reason"],
            )
            state.communication = to_dict(communication)
            safe_id = (application_id or "UNKNOWN").replace("/", "_")
            state.communication_artifact_path = _save_json_artifact(
                f"email_draft_{safe_id}.json", state.communication
            )
            state.log(f"Draft communication prepared and saved to {state.communication_artifact_path} (not sent).")

        return _finalize(
            state, application_id,
            status="STOPPED_HUMAN_REVIEW",
            risk_result=state.risk_result,
            recommendation=state.human_review_result["action"],
            decision_evidence=state.risk_result.get("reasoning", []),
        )

    # ---------------- 4. Underwriting Recommendation Agent ----------------
    hook.before_agent("underwriting_recommendation", {"proposal_number": application_id})
    state.recommendation = recommendation_agent.run(applicant, state.risk_result)
    hook.after_agent("underwriting_recommendation", state.recommendation)
    state.log(
        f"Underwriting recommendation generated: {state.recommendation['recommendation']} "
        f"(confidence {state.recommendation['confidence']})."
    )

    if state.recommendation["confidence"] >= UNDERWRITING_CONFIDENCE_THRESHOLD:
        state.log("Confidence above threshold -- straight-through processing.")
        return _finalize(
            state, application_id,
            status="COMPLETED",
            risk_result=state.risk_result,
            recommendation=state.recommendation["recommendation"],
            premium=state.recommendation["premium"],
            confidence=state.recommendation["confidence"],
            decision_evidence=state.recommendation.get("rationale", []),
        )

    # ---------------- 5. Human Review Agent (low confidence) ----------------
    state.log("Confidence below threshold -- routing to Human Review.")
    hook.before_agent("human_review", {"trigger": "low_confidence"})
    state.human_review_result = human_review_agent.run(
        applicant, trigger="low_confidence", risk_result=state.risk_result, recommendation=state.recommendation
    )
    hook.after_agent("human_review", state.human_review_result)
    state.log(
        f"Human Review action: {state.human_review_result['action']}. "
        f"Reason: {state.human_review_result['reason']}"
    )

    if state.human_review_result["action"] == "REQUEST_MORE_INFORMATION":
        requested = state.human_review_result.get("requested_items") or [
            "Supplementary information to support automated risk scoring"
        ]
        communication = draft_human_review_information_request(
            proposal_number=applicant.proposal_number,
            broker_name=applicant.broker_name,
            applicant_name=applicant.applicant_name,
            requested_items=requested,
            review_reason=state.human_review_result["reason"],
        )
        state.communication = to_dict(communication)
        safe_id = (application_id or "UNKNOWN").replace("/", "_")
        state.communication_artifact_path = _save_json_artifact(
            f"email_draft_{safe_id}.json", state.communication
        )
        state.log(f"Draft communication prepared and saved to {state.communication_artifact_path} (not sent).")

    return _finalize(
        state, application_id,
        status="STOPPED_HUMAN_REVIEW",
        risk_result=state.risk_result,
        recommendation=state.human_review_result["action"],
        premium=state.recommendation.get("premium"),
        confidence=state.recommendation.get("confidence"),
        decision_evidence=state.recommendation.get("rationale", []),
    )


def _finalize(
    state: UnderwritingState,
    application_id,
    status: str,
    risk_result: Optional[dict] = None,
    recommendation: Optional[str] = None,
    premium: Optional[str] = None,
    confidence: Optional[float] = None,
    decision_evidence=None,
) -> dict:
    decision = FinalDecision(
        application_id=application_id,
        status=status,
        risk_category=(risk_result or {}).get("risk_category"),
        risk_score=(risk_result or {}).get("risk_score"),
        recommendation=recommendation,
        premium=premium,
        confidence=confidence,
        decision_evidence=decision_evidence or [],
        audit_trail=state.audit_trail,
        communication=state.communication,
    )
    decision_dict = to_dict(decision)
    state.final_decision = decision_dict
    _save_json_artifact("decision.json", decision_dict)
    return decision_dict
