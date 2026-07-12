"""
adk_controller.py — v2 workflow, built on Google ADK's own graph engine.

Where workflow/controller.py (v1) is a hand-written Python function that
calls each agent and branches with if/else, this version expresses the
same 5-agent business workflow as an actual `google.adk.workflow.Workflow`
graph: LlmAgent nodes (with tools) and small deterministic FunctionNode
gates/handlers, wired together with conditional edges. ADK's own Runner
drives execution, routing, and event streaming.

Agent tools (completeness, consistency, premium, etc.) are invoked by
LlmAgents so AssuranceADKPlugin can emit TOOL_CALL_* events. Risk dimension
tools run in a FunctionNode before a judgment-only RiskAssessmentAgent
(avoids mid-tool hangs on high-risk). Other FunctionNodes (intake, gates,
handlers) emit TOOL_CALL_* manually via workflow.assurance helpers.

Shared state (applicant data, audit trail, each agent's result) is carried
via `ctx.state` -- ADK's own per-run state store.
"""

import json
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, Optional

from google.adk.agents import LlmAgent
from google.adk import Context, Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow, node
from google.genai import types

from agents import (
    submission_agent,
    document_agent,
    risk_agent,
    recommendation_agent,
    human_review_agent,
)
from tools.claims_tool import assess_claims_risk
from tools.communication_tool import draft_communication
from tools.completeness_tool import check_submission_completeness
from tools.consistency_tool import validate_consistency
from tools.coverage_condition_tool import determine_coverage_conditions
from tools.decision_evidence_tool import assemble_final_decision
from tools.document_parser_tool import parse_proposal_document
from tools.extraction_tool import extract_supporting_document_data
from tools.financial_risk_tool import assess_financial_risk
from tools.human_review_queue_tool import enqueue_for_human_review
from tools.lifestyle_risk_tool import assess_lifestyle_risk
from tools.medical_risk_tool import assess_medical_risk
from tools.premium_tool import recommend_premium
from tools.scoring_tool import compute_overall_risk_score
from workflow.assurance import (
    begin_run,
    close_run,
    emit_decision_finalized,
    emit_gate_evaluated,
    emit_human_approval,
    emit_tool_call_completed,
    emit_tool_call_failed,
    emit_tool_call_started,
)
from workflow.model_config import get_model

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
CONFIDENCE_THRESHOLD = 0.75
WORKFLOW_TIMEOUT_S = 180


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _traced_tool(
    node_name: str,
    tool_name: str,
    tool_args: dict[str, Any],
    fn: Callable[[], Any],
) -> Any:
    """Emit TOOL_CALL_* around a FunctionNode tool invocation."""
    emit_tool_call_started(tool_name, tool_args, agent_name=node_name)
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:
        emit_tool_call_failed(
            tool_name, exc, agent_name=node_name, tool_args=tool_args
        )
        raise
    emit_tool_call_completed(
        tool_name,
        agent_name=node_name,
        execution_time_ms=int(round((time.perf_counter() - started) * 1000)),
        tool_args=tool_args,
        result=result,
    )
    return result


def _parse(node_input: Any) -> Dict[str, Any]:
    """LlmAgent nodes emit raw JSON text (no output_schema, since
    output_schema and tools can't be used together in ADK). Gates receive
    that text and need it as a dict.

    Models often finish after tool calls with an empty final message, or wrap
    JSON in prose/fences -- so this parser is intentionally forgiving.
    """
    if isinstance(node_input, dict):
        return node_input
    if node_input is None:
        raise ValueError("Agent produced no output")

    text = node_input if isinstance(node_input, str) else str(node_input)
    text = text.strip()
    if not text:
        raise ValueError("Agent produced empty output")

    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening ``` / ```json and closing ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _try_parse(node_input: Any) -> Optional[Dict[str, Any]]:
    try:
        return _parse(node_input)
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


def _fallback_submission(applicant: dict, *, node_name: str = "submission_gate") -> Dict[str, Any]:
    result = _traced_tool(
        node_name,
        "check_submission_completeness",
        {"applicant_data": applicant},
        lambda: check_submission_completeness(applicant),
    )
    return {
        "complete": result.get("complete", False),
        "missing_fields": result.get("missing_fields", []),
        "confidence": 0.9,
        "notes": [
            "Recovered via CompletenessCheckTool after empty/invalid LLM output."
        ],
    }


def _run_document_tools(
    applicant: dict, *, node_name: str = "document_tools"
) -> Dict[str, Any]:
    """Run extract + consistency tools with Assurance TOOL_CALL_* emits."""
    attached = applicant.get("attached_documents") or {}
    extraction = _traced_tool(
        node_name,
        "extract_supporting_document_data",
        {"attached_documents": attached},
        lambda: extract_supporting_document_data(attached),
    )
    extracted = extraction.get("extracted_data") or {}
    consistency_args = {
        "declared_smoking_status": applicant.get("smoking_status"),
        "declared_previous_claims_filed": applicant.get("previous_claims_filed"),
        "declared_annual_income": applicant.get("annual_income"),
        "extracted_data": extracted,
    }
    consistency = _traced_tool(
        node_name,
        "validate_consistency",
        consistency_args,
        lambda: validate_consistency(**consistency_args),
    )
    return {
        "consistent": consistency.get("consistent", True),
        "issues": consistency.get("issues", []),
        "extracted_data": extracted,
        "notes": [],
    }


def _fallback_document(applicant: dict, *, node_name: str = "document_gate") -> Dict[str, Any]:
    result = _run_document_tools(applicant, node_name=node_name)
    result["notes"] = [
        "Recovered via Extraction/Consistency tools after empty/invalid LLM output."
    ]
    return result


def _run_risk_dimension_tools(
    applicant: dict, *, node_name: str = "risk_tools"
) -> Dict[str, Any]:
    """Run the five deterministic risk tools with Assurance TOOL_CALL_* emits."""
    medical_args = {
        "medical_conditions": applicant.get("medical_conditions"),
        "hospitalization_history": applicant.get("hospitalization_history"),
        "bmi": applicant.get("bmi"),
    }
    medical = _traced_tool(
        node_name,
        "assess_medical_risk",
        medical_args,
        lambda: assess_medical_risk(**medical_args),
    )
    lifestyle_args = {
        "smoking_status": applicant.get("smoking_status"),
        "hazardous_occupation": applicant.get("hazardous_occupation"),
        "hazardous_hobbies": applicant.get("hazardous_hobbies"),
    }
    lifestyle = _traced_tool(
        node_name,
        "assess_lifestyle_risk",
        lifestyle_args,
        lambda: assess_lifestyle_risk(**lifestyle_args),
    )
    financial_args = {
        "sum_insured": applicant.get("sum_insured"),
        "annual_income": applicant.get("annual_income"),
    }
    financial = _traced_tool(
        node_name,
        "assess_financial_risk",
        financial_args,
        lambda: assess_financial_risk(**financial_args),
    )
    claims_args = {
        "previous_claims_filed": applicant.get("previous_claims_filed"),
        "claims_details": applicant.get("claims_details"),
    }
    claims = _traced_tool(
        node_name,
        "assess_claims_risk",
        claims_args,
        lambda: assess_claims_risk(**claims_args),
    )
    return _traced_tool(
        node_name,
        "compute_overall_risk_score",
        {
            "medical_result": medical,
            "lifestyle_result": lifestyle,
            "financial_result": financial,
            "claims_result": claims,
        },
        lambda: compute_overall_risk_score(medical, lifestyle, financial, claims),
    )


def _fallback_risk(applicant: dict, *, node_name: str = "risk_gate") -> Dict[str, Any]:
    scored = _run_risk_dimension_tools(applicant, node_name=node_name)
    scored["confidence"] = 0.85
    scored["summary"] = "Deterministic risk recovery after empty/invalid LLM output."
    return scored


def _fallback_recommendation(
    risk: dict, *, node_name: str = "recommendation_gate"
) -> Dict[str, Any]:
    category = (risk.get("risk_category") or "MEDIUM").upper()
    premium = _traced_tool(
        node_name,
        "recommend_premium",
        {"risk_category": category},
        lambda: recommend_premium(category),
    )
    coverage_args = {
        "medical_risk": risk.get("medical_risk"),
        "lifestyle_risk": risk.get("lifestyle_risk"),
        "claims_risk": risk.get("claims_risk"),
    }
    conditions = _traced_tool(
        node_name,
        "determine_coverage_conditions",
        coverage_args,
        lambda: determine_coverage_conditions(**coverage_args),
    )
    if category == "LOW":
        recommendation = "APPROVE"
    elif category == "HIGH":
        recommendation = "REFER"
    else:
        recommendation = "APPROVE_WITH_CONDITIONS"
    return {
        "recommendation": recommendation,
        "premium": premium.get("premium"),
        "coverage_conditions": (
            conditions.get("coverage_conditions", [])
            if isinstance(conditions, dict)
            else (conditions or [])
        ),
        "rationale": risk.get("reasoning")
        or ["Recovered via premium/coverage tools after empty/invalid LLM output."],
        "confidence": float(risk.get("confidence") or 0.8),
    }


def _save_json(filename: str, data: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _finalize(**kwargs) -> Dict[str, Any]:
    """Deterministic step -- backed by tools/decision_evidence_tool.py."""
    decision = _traced_tool(
        "finalize",
        "assemble_final_decision",
        {key: value for key, value in kwargs.items()},
        lambda: assemble_final_decision(**kwargs),
    )
    _save_json("decision.json", decision)
    emit_decision_finalized(decision)
    return decision


def _maybe_draft_communication(
    trigger: str, applicant: dict, *, node_name: str = "handler", **kwargs
):
    """Deterministic step -- backed by tools/communication_tool.py."""
    call_kwargs = {
        "trigger": trigger,
        "proposal_number": applicant.get("proposal_number"),
        "broker_name": applicant.get("broker_name"),
        "applicant_name": applicant.get("applicant_name"),
        **kwargs,
    }
    result = _traced_tool(
        node_name,
        "draft_communication",
        call_kwargs,
        lambda: draft_communication(**call_kwargs),
    )
    if not result.get("success"):
        return None
    communication = result["communication"]
    safe_id = (applicant.get("proposal_number") or "UNKNOWN").replace("/", "_")
    _save_json(f"email_draft_{safe_id}.json", communication)
    return communication


def _enqueue_review(
    *,
    node_name: str,
    application_id: str | None,
    trigger: str,
    reason: str | None,
) -> Any:
    args = {
        "application_id": application_id,
        "trigger": trigger,
        "reason": reason,
    }
    return _traced_tool(
        node_name,
        "enqueue_for_human_review",
        args,
        lambda: enqueue_for_human_review(**args),
    )


def _fresh_human_review_agent(unique_name: str) -> LlmAgent:
    """The Human Review Agent is reached from three different branches
    (disclosure mismatch / material risk / low confidence). Graph nodes
    need unique names, so each branch gets its own LlmAgent instance --
    judgment-only (no tools) to avoid malformed tool-call JSON from the LLM.
    """
    return LlmAgent(
        name=unique_name,
        model=get_model(),
        instruction=human_review_agent.JUDGMENT_INSTRUCTION,
        tools=[],
    )


# ---------------------------------------------------------------------------
# FunctionNode steps — intake, gates, handlers (not duplicated agent tools)
# ---------------------------------------------------------------------------


@node
def intake(ctx: Context, node_input: str):
    """Entry point. node_input is a JSON string: {"file_path": "..."}."""
    file_path = json.loads(node_input)["file_path"]
    result = _traced_tool(
        "intake",
        "parse_proposal_document",
        {"file_path": file_path},
        lambda: parse_proposal_document(file_path),
    )
    if not result["success"]:
        raise RuntimeError(f"Failed to parse proposal: {result['error']}")
    applicant = result["applicant_data"]
    ctx.state.update(
        {
            "applicant_data": applicant,
            "audit_trail": ["Submission received and parsed (DocumentParserTool)."],
        }
    )
    return {"applicant_data": applicant}


@node
def submission_gate(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data") or {}
    # Always trust CompletenessCheckTool for routing — LLM may invent missing fields.
    completeness = _fallback_submission(applicant, node_name="submission_gate")
    llm = _try_parse(node_input)
    if llm and llm.get("notes"):
        completeness = {**completeness, "notes": llm.get("notes")}
    missing = completeness.get("missing_fields", [])
    complete = len(missing) == 0

    audit = ctx.state.get("audit_trail", []) + [
        (
            "Submission validated as complete by CompletenessCheckTool."
            if complete
            else f"CompletenessCheckTool found missing fields: {missing}"
        )
    ]
    ctx.state.update({"completeness_result": completeness, "audit_trail": audit})

    route = "complete" if complete else "incomplete"
    emit_gate_evaluated(
        gate="submission",
        route=route,
        application_id=applicant.get("proposal_number"),
        details={"missing_field_count": len(missing)},
    )
    return Event(route=route, output={"applicant_data": applicant})


@node
def handle_incomplete(ctx: Context, node_input):
    applicant = ctx.state.get("applicant_data")
    completeness = ctx.state.get("completeness_result", {})
    missing = completeness.get("missing_fields", [])

    communication = _maybe_draft_communication(
        "incomplete_submission",
        applicant,
        node_name="handle_incomplete",
        missing_fields=missing,
    )
    audit = ctx.state.get("audit_trail", []) + (
        ["Draft information request prepared (not sent)."] if communication else []
    )

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_INCOMPLETE",
        audit_trail=audit,
        recommendation="REQUEST_MORE_INFORMATION",
        decision_evidence=[f"Missing mandatory field: {f}" for f in missing],
        communication=communication,
    )


@node
def document_tools(ctx: Context, node_input):
    """Deterministic extract + consistency before judgment-only Document agent."""
    applicant = ctx.state.get("applicant_data") or {}
    if isinstance(node_input, dict) and node_input.get("applicant_data"):
        applicant = node_input["applicant_data"] or applicant
    tool_result = _run_document_tools(applicant, node_name="document_tools")
    audit = ctx.state.get("audit_trail", []) + [
        (
            "Document tools found no disclosure mismatches."
            if tool_result.get("consistent")
            else f"Document tools found mismatches: {tool_result.get('issues')}"
        )
    ]
    ctx.state.update({"document_tool_result": tool_result, "audit_trail": audit})
    return {
        "applicant_data": applicant,
        "tool_result": tool_result,
    }


@node
def document_gate(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data") or {}
    stored = ctx.state.get("document_tool_result")
    document_result = _try_parse(node_input)
    if document_result is None:
        document_result = stored or _fallback_document(
            applicant, node_name="document_gate"
        )
    # Prefer deterministic tool issues when the LLM claims consistent but tools disagree.
    if stored and stored.get("issues") and not document_result.get("issues"):
        document_result = {
            **document_result,
            "consistent": False,
            "issues": stored.get("issues"),
            "extracted_data": stored.get("extracted_data")
            or document_result.get("extracted_data"),
        }
    issues = document_result.get("issues", [])
    consistent = len(issues) == 0

    audit = ctx.state.get("audit_trail", []) + [
        (
            "Document Intelligence Agent found no disclosure mismatches."
            if consistent
            else f"Document Intelligence Agent found mismatches: {issues}"
        )
    ]
    ctx.state.update({"document_result": document_result, "audit_trail": audit})

    route = "consistent" if consistent else "mismatch"
    emit_gate_evaluated(
        gate="document",
        route=route,
        application_id=applicant.get("proposal_number"),
        details={"issue_count": len(issues)},
    )
    return Event(
        route=route,
        output={
            "applicant_data": applicant,
            "trigger": "disclosure_mismatch",
            "document_intelligence": document_result,
        },
    )


@node
def handle_mismatch(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data")
    issues = ctx.state.get("document_result", {}).get("issues", [])
    review = _try_parse(node_input) or {
        "action": "REQUEST_MORE_INFORMATION",
        "reason": "Disclosure mismatch; human review recovered after empty/invalid LLM output.",
        "requested_items": [],
    }

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        communication = _maybe_draft_communication(
            "disclosure_mismatch",
            applicant,
            node_name="handle_mismatch",
            mismatches=issues,
        )

    audit = (
        ctx.state.get("audit_trail", [])
        + [
            f"Human Review action: {review.get('action')}. Reason: {review.get('reason')}"
        ]
        + (["Draft communication prepared (not sent)."] if communication else [])
    )

    emit_human_approval(
        trigger="disclosure_mismatch",
        action=review.get("action"),
        reason=review.get("reason"),
        application_id=applicant.get("proposal_number") if applicant else None,
    )
    _enqueue_review(
        node_name="handle_mismatch",
        application_id=applicant.get("proposal_number") if applicant else None,
        trigger="disclosure_mismatch",
        reason=review.get("reason"),
    )

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_MISMATCH",
        audit_trail=audit,
        recommendation=review.get("action"),
        decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in issues],
        communication=communication,
    )


@node
def risk_tools(ctx: Context, node_input):
    """Deterministic risk dimension tools before judgment-only RiskAssessmentAgent."""
    applicant = ctx.state.get("applicant_data") or {}
    if isinstance(node_input, dict) and node_input.get("applicant_data"):
        applicant = node_input["applicant_data"] or applicant
    tool_result = _run_risk_dimension_tools(applicant, node_name="risk_tools")
    audit = ctx.state.get("audit_trail", []) + [
        "Risk dimension tools completed (medical/lifestyle/financial/claims + score)."
    ]
    ctx.state.update({"risk_tool_result": tool_result, "audit_trail": audit})
    return {
        "applicant_data": applicant,
        "tool_result": tool_result,
    }


@node
def risk_gate(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data") or {}
    stored = ctx.state.get("risk_tool_result")
    risk_result = _try_parse(node_input)
    if risk_result is None:
        if stored:
            risk_result = {
                **stored,
                "confidence": stored.get("confidence", 0.85),
                "summary": stored.get(
                    "summary",
                    "Used deterministic risk tool_result after empty/invalid LLM output.",
                ),
            }
        else:
            risk_result = _fallback_risk(applicant, node_name="risk_gate")
    material = bool(risk_result.get("material_risk"))

    audit = ctx.state.get("audit_trail", []) + [
        f"Risk assessed: score={risk_result.get('risk_score')}, "
        f"category={risk_result.get('risk_category')}, confidence={risk_result.get('confidence')}."
    ]
    ctx.state.update({"risk_result": risk_result, "audit_trail": audit})

    route = "material" if material else "ok"
    emit_gate_evaluated(
        gate="risk",
        route=route,
        application_id=applicant.get("proposal_number"),
        details={
            "risk_score": risk_result.get("risk_score"),
            "risk_category": risk_result.get("risk_category"),
            "material_risk": material,
        },
    )
    return Event(
        route=route,
        output={
            "applicant_data": applicant,
            "risk_assessment": risk_result,
            "trigger": "material_risk",
        },
    )


@node
def handle_material_risk(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data")
    risk = ctx.state.get("risk_result", {})
    review = _try_parse(node_input) or {
        "action": "REFER",
        "reason": "Material risk; human review recovered after empty/invalid LLM output.",
        "requested_items": [
            "Updated medical examination report",
            "Detailed claim history / loss run statement",
        ],
    }

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        requested = review.get("requested_items") or [
            "Updated medical examination report",
            "Detailed claim history / loss run statement",
        ]
        communication = _maybe_draft_communication(
            "human_review",
            applicant,
            node_name="handle_material_risk",
            requested_items=requested,
            review_reason=review.get("reason", ""),
        )

    audit = (
        ctx.state.get("audit_trail", [])
        + [
            f"Material risk identified -- routed to Human Review. "
            f"Action: {review.get('action')}. Reason: {review.get('reason')}"
        ]
        + (["Draft communication prepared (not sent)."] if communication else [])
    )

    emit_human_approval(
        trigger="material_risk",
        action=review.get("action"),
        reason=review.get("reason"),
        application_id=applicant.get("proposal_number") if applicant else None,
    )
    _enqueue_review(
        node_name="handle_material_risk",
        application_id=applicant.get("proposal_number") if applicant else None,
        trigger="material_risk",
        reason=review.get("reason"),
    )

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_HUMAN_REVIEW",
        audit_trail=audit,
        risk_category=risk.get("risk_category"),
        risk_score=risk.get("risk_score"),
        recommendation=review.get("action"),
        decision_evidence=risk.get("reasoning", []),
        communication=communication,
    )


@node
def recommendation_gate(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data") or {}
    risk_result = ctx.state.get("risk_result", {})
    recommendation = _try_parse(node_input) or _fallback_recommendation(
        risk_result, node_name="recommendation_gate"
    )
    confidence = recommendation.get("confidence", 0.0)
    stp = confidence >= CONFIDENCE_THRESHOLD

    audit = ctx.state.get("audit_trail", []) + [
        f"Underwriting recommendation: {recommendation.get('recommendation')} (confidence {confidence})."
    ]
    ctx.state.update({"recommendation": recommendation, "audit_trail": audit})

    route = "stp" if stp else "low_confidence"
    emit_gate_evaluated(
        gate="recommendation",
        route=route,
        application_id=applicant.get("proposal_number"),
        details={
            "confidence": confidence,
            "recommendation": recommendation.get("recommendation"),
        },
    )
    return Event(
        route=route,
        output={
            "applicant_data": applicant,
            "risk_assessment": risk_result,
            "underwriting_recommendation": recommendation,
            "trigger": "low_confidence",
        },
    )


@node
def handle_stp(ctx: Context, node_input):
    applicant = ctx.state.get("applicant_data")
    risk = ctx.state.get("risk_result", {})
    recommendation = ctx.state.get("recommendation", {})

    audit = ctx.state.get("audit_trail", []) + [
        "Confidence above threshold -- straight-through processing."
    ]

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="COMPLETED",
        audit_trail=audit,
        risk_category=risk.get("risk_category"),
        risk_score=risk.get("risk_score"),
        recommendation=recommendation.get("recommendation"),
        premium=recommendation.get("premium"),
        confidence=recommendation.get("confidence"),
        decision_evidence=recommendation.get("rationale", []),
    )


@node
def handle_low_confidence(ctx: Context, node_input: str):
    applicant = ctx.state.get("applicant_data")
    risk = ctx.state.get("risk_result", {})
    recommendation = ctx.state.get("recommendation", {})
    review = _try_parse(node_input) or {
        "action": "REQUEST_MORE_INFORMATION",
        "reason": "Low confidence; human review recovered after empty/invalid LLM output.",
        "requested_items": ["Supplementary information to support automated scoring"],
    }

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        requested = review.get("requested_items") or [
            "Supplementary information to support automated scoring"
        ]
        communication = _maybe_draft_communication(
            "human_review",
            applicant,
            node_name="handle_low_confidence",
            requested_items=requested,
            review_reason=review.get("reason", ""),
        )

    audit = (
        ctx.state.get("audit_trail", [])
        + [
            f"Confidence below threshold -- routed to Human Review. "
            f"Action: {review.get('action')}. Reason: {review.get('reason')}"
        ]
        + (["Draft communication prepared (not sent)."] if communication else [])
    )

    emit_human_approval(
        trigger="low_confidence",
        action=review.get("action"),
        reason=review.get("reason"),
        application_id=applicant.get("proposal_number") if applicant else None,
    )
    _enqueue_review(
        node_name="handle_low_confidence",
        application_id=applicant.get("proposal_number") if applicant else None,
        trigger="low_confidence",
        reason=review.get("reason"),
    )

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_HUMAN_REVIEW",
        audit_trail=audit,
        risk_category=risk.get("risk_category"),
        risk_score=risk.get("risk_score"),
        recommendation=review.get("action"),
        premium=recommendation.get("premium"),
        confidence=recommendation.get("confidence"),
        decision_evidence=recommendation.get("rationale", []),
        communication=communication,
    )


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def _build_graph() -> Workflow:
    # Submission/recommendation agents own tools. Document + risk tools run in
    # FunctionNodes; those LlmAgents are judgment-only over tool_result.
    submission_llm = submission_agent.build_agent(with_tools=True)
    document_llm = document_agent.build_agent(with_tools=False)
    risk_llm = risk_agent.build_agent(with_tools=False)
    recommendation_llm = recommendation_agent.build_agent(with_tools=True)

    human_review_mismatch_llm = _fresh_human_review_agent("HumanReviewAgent_Mismatch")
    human_review_material_llm = _fresh_human_review_agent(
        "HumanReviewAgent_MaterialRisk"
    )
    human_review_low_conf_llm = _fresh_human_review_agent(
        "HumanReviewAgent_LowConfidence"
    )

    return Workflow(
        name="underwriting_workflow_v2",
        edges=[
            ("START", intake, submission_llm, submission_gate),
            (
                submission_gate,
                {"complete": document_tools, "incomplete": handle_incomplete},
            ),
            (document_tools, document_llm, document_gate),
            (
                document_gate,
                {"consistent": risk_tools, "mismatch": human_review_mismatch_llm},
            ),
            (human_review_mismatch_llm, handle_mismatch),
            (risk_tools, risk_llm, risk_gate),
            (
                risk_gate,
                {"material": human_review_material_llm, "ok": recommendation_llm},
            ),
            (human_review_material_llm, handle_material_risk),
            (recommendation_llm, recommendation_gate),
            (
                recommendation_gate,
                {"stp": handle_stp, "low_confidence": human_review_low_conf_llm},
            ),
            (human_review_low_conf_llm, handle_low_confidence),
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
        assurance = begin_run(file_path)
        try:
            session_service = InMemorySessionService()
            user_id, session_id = "underwriting_system", str(uuid.uuid4())
            await session_service.create_session(
                app_name="insurance_underwriting_adk_v2",
                user_id=user_id,
                session_id=session_id,
            )

            workflow = _build_graph()
            plugins = [assurance.plugin] if assurance else []
            runner = Runner(
                agent=workflow,
                app_name="insurance_underwriting_adk_v2",
                session_service=session_service,
                plugins=plugins,
            )

            message = types.Content(
                role="user",
                parts=[types.Part(text=json.dumps({"file_path": file_path}))],
            )

            final_output = None
            try:
                async with asyncio.timeout(WORKFLOW_TIMEOUT_S):
                    async for event in runner.run_async(
                        user_id=user_id, session_id=session_id, new_message=message
                    ):
                        if getattr(event, "output", None) is not None:
                            final_output = event.output
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Workflow timed out after {WORKFLOW_TIMEOUT_S}s"
                ) from exc

            if final_output is None:
                raise RuntimeError("Workflow produced no final decision output.")
            return final_output
        finally:
            # Prefer WORKFLOW_RUN_COMPLETED from after_run_callback on designed
            # exits. close_run / plugin.close emits WORKFLOW_RUN_FAILED only when
            # no terminal event was recorded (crash / timeout / cancel).
            await close_run(assurance)

    return asyncio.run(_run())
