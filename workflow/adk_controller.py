"""
adk_controller.py — v2 workflow, built on Google ADK's own graph engine.

Where workflow/controller.py (v1) is a hand-written Python function that
calls each agent and branches with if/else, this version expresses the
same 5-agent business workflow as an actual `google.adk.workflow.Workflow`
graph: LlmAgent nodes and small deterministic FunctionNode gates, wired
together with conditional edges. ADK's own Runner drives execution,
routing, and event streaming -- this module only *defines* the graph and
the gate logic, it doesn't run a manual call/inspect/branch loop itself.

Still explicitly NOT a `SequentialAgent`: SequentialAgent (and its
replacement) only runs nodes in a straight line. The branching this
workflow needs (complete? consistent? material risk? confidence above
threshold?) requires the conditional-edge graph API
(`Workflow(edges=[..., (gate, {route: node, ...}), ...])`), which is what's
used here -- a gate node signals its branch by returning `Event(route=...)`.

Every business agent is reused unchanged from agents/*.py (same
instructions, same tools -- MedicalRiskTool, ConsistencyTool, etc.). This
file adds three deterministic FunctionNode steps that don't call an LLM:
parsing the proposal file, drafting communications, and assembling the
final decision -- each backed by the corresponding tool in tools/.

Shared state (applicant data, audit trail, each agent's result) is carried
via `ctx.state` -- ADK's own per-run state store -- because an LlmAgent
node's output is only its own structured response, not an echo of
whatever it was given; anything that needs to survive past an LLM node has
to be written to ctx.state explicitly and read back afterwards.
"""

import json
import os
import uuid
from typing import Any, Dict

from google.adk.agents import LlmAgent
from google.adk import Context, Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow, node
from google.genai import types

from agents import submission_agent, document_agent, risk_agent, recommendation_agent, human_review_agent
from tools.document_parser_tool import parse_proposal_document
from tools.communication_tool import draft_communication
from tools.decision_evidence_tool import assemble_final_decision
from workflow.model_config import get_model

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
CONFIDENCE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _parse(node_input: Any) -> Dict[str, Any]:
    """LlmAgent nodes emit raw JSON text (no output_schema, since
    output_schema and tools can't be used together in ADK). Gates receive
    that text and need it as a dict."""
    if isinstance(node_input, dict):
        return node_input
    text = node_input.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _save_json(filename: str, data: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _finalize(**kwargs) -> Dict[str, Any]:
    """Deterministic step -- backed by tools/decision_evidence_tool.py."""
    decision = assemble_final_decision(**kwargs)
    _save_json("decision.json", decision)
    return decision


def _maybe_draft_communication(trigger: str, applicant: dict, **kwargs):
    """Deterministic step -- backed by tools/communication_tool.py."""
    result = draft_communication(
        trigger=trigger,
        proposal_number=applicant.get("proposal_number"),
        broker_name=applicant.get("broker_name"),
        applicant_name=applicant.get("applicant_name"),
        **kwargs,
    )
    if not result.get("success"):
        return None
    communication = result["communication"]
    safe_id = (applicant.get("proposal_number") or "UNKNOWN").replace("/", "_")
    _save_json(f"email_draft_{safe_id}.json", communication)
    return communication


def _fresh_human_review_agent(unique_name: str) -> LlmAgent:
    """The Human Review Agent is reached from three different branches
    (disclosure mismatch / material risk / low confidence). Graph nodes
    need unique names, so each branch gets its own LlmAgent instance --
    same instruction and tools as agents/human_review_agent.py, just a
    distinct node name."""
    template = human_review_agent.build_agent()
    return LlmAgent(name=unique_name, model=get_model(), instruction=human_review_agent.INSTRUCTION, tools=list(template.tools))


# ---------------------------------------------------------------------------
# FunctionNode steps
# ---------------------------------------------------------------------------

@node
def intake(ctx: Context, node_input: str):
    """Entry point. node_input is a JSON string: {"file_path": "..."}."""
    file_path = json.loads(node_input)["file_path"]
    result = parse_proposal_document(file_path)
    if not result["success"]:
        raise RuntimeError(f"Failed to parse proposal: {result['error']}")
    applicant = result["applicant_data"]
    ctx.state.update({
        "applicant_data": applicant,
        "audit_trail": ["Submission received and parsed (DocumentParserTool)."],
    })
    return {"applicant_data": applicant}


@node
def submission_gate(ctx: Context, node_input: str):
    completeness = _parse(node_input)
    missing = completeness.get("missing_fields", [])
    complete = len(missing) == 0

    audit = ctx.state.get("audit_trail", []) + [
        "Submission validated as complete by Submission Intake Agent."
        if complete else f"Submission Intake Agent found missing fields: {missing}"
    ]
    ctx.state.update({"completeness_result": completeness, "audit_trail": audit})

    route = "complete" if complete else "incomplete"
    return Event(route=route, output={"applicant_data": ctx.state.get("applicant_data")})


@node
def handle_incomplete(ctx: Context, node_input):
    applicant = ctx.state.get("applicant_data")
    completeness = ctx.state.get("completeness_result", {})
    missing = completeness.get("missing_fields", [])

    communication = _maybe_draft_communication("incomplete_submission", applicant, missing_fields=missing)
    audit = ctx.state.get("audit_trail", []) + (["Draft information request prepared (not sent)."] if communication else [])

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_INCOMPLETE",
        audit_trail=audit,
        recommendation="REQUEST_MORE_INFORMATION",
        decision_evidence=[f"Missing mandatory field: {f}" for f in missing],
        communication=communication,
    )


@node
def document_gate(ctx: Context, node_input: str):
    document_result = _parse(node_input)
    issues = document_result.get("issues", [])
    consistent = len(issues) == 0

    audit = ctx.state.get("audit_trail", []) + [
        "Document Intelligence Agent found no disclosure mismatches."
        if consistent else f"Document Intelligence Agent found mismatches: {issues}"
    ]
    ctx.state.update({"document_result": document_result, "audit_trail": audit})

    applicant = ctx.state.get("applicant_data")
    route = "consistent" if consistent else "mismatch"
    return Event(
        route=route,
        output={"applicant_data": applicant, "trigger": "disclosure_mismatch", "document_intelligence": document_result},
    )


@node
def handle_mismatch(ctx: Context, node_input: str):
    review = _parse(node_input)
    applicant = ctx.state.get("applicant_data")
    issues = ctx.state.get("document_result", {}).get("issues", [])

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        communication = _maybe_draft_communication("disclosure_mismatch", applicant, mismatches=issues)

    audit = ctx.state.get("audit_trail", []) + [
        f"Human Review action: {review.get('action')}. Reason: {review.get('reason')}"
    ] + (["Draft communication prepared (not sent)."] if communication else [])

    return _finalize(
        application_id=applicant.get("proposal_number"),
        status="STOPPED_MISMATCH",
        audit_trail=audit,
        recommendation=review.get("action"),
        decision_evidence=[f"{i.get('field', 'Field')} mismatch" for i in issues],
        communication=communication,
    )


@node
def risk_gate(ctx: Context, node_input: str):
    risk_result = _parse(node_input)
    material = bool(risk_result.get("material_risk"))

    audit = ctx.state.get("audit_trail", []) + [
        f"Risk assessed: score={risk_result.get('risk_score')}, "
        f"category={risk_result.get('risk_category')}, confidence={risk_result.get('confidence')}."
    ]
    ctx.state.update({"risk_result": risk_result, "audit_trail": audit})

    applicant = ctx.state.get("applicant_data")
    route = "material" if material else "ok"
    return Event(
        route=route,
        output={"applicant_data": applicant, "risk_assessment": risk_result, "trigger": "material_risk"},
    )


@node
def handle_material_risk(ctx: Context, node_input: str):
    review = _parse(node_input)
    applicant = ctx.state.get("applicant_data")
    risk = ctx.state.get("risk_result", {})

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        requested = review.get("requested_items") or [
            "Updated medical examination report",
            "Detailed claim history / loss run statement",
        ]
        communication = _maybe_draft_communication(
            "human_review", applicant, requested_items=requested, review_reason=review.get("reason", ""),
        )

    audit = ctx.state.get("audit_trail", []) + [
        f"Material risk identified -- routed to Human Review. "
        f"Action: {review.get('action')}. Reason: {review.get('reason')}"
    ] + (["Draft communication prepared (not sent)."] if communication else [])

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
    recommendation = _parse(node_input)
    confidence = recommendation.get("confidence", 0.0)
    stp = confidence >= CONFIDENCE_THRESHOLD

    audit = ctx.state.get("audit_trail", []) + [
        f"Underwriting recommendation: {recommendation.get('recommendation')} (confidence {confidence})."
    ]
    ctx.state.update({"recommendation": recommendation, "audit_trail": audit})

    applicant = ctx.state.get("applicant_data")
    risk_result = ctx.state.get("risk_result", {})
    route = "stp" if stp else "low_confidence"
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

    audit = ctx.state.get("audit_trail", []) + ["Confidence above threshold -- straight-through processing."]

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
    review = _parse(node_input)
    applicant = ctx.state.get("applicant_data")
    risk = ctx.state.get("risk_result", {})
    recommendation = ctx.state.get("recommendation", {})

    communication = None
    if review.get("action") == "REQUEST_MORE_INFORMATION":
        requested = review.get("requested_items") or ["Supplementary information to support automated scoring"]
        communication = _maybe_draft_communication(
            "human_review", applicant, requested_items=requested, review_reason=review.get("reason", ""),
        )

    audit = ctx.state.get("audit_trail", []) + [
        f"Confidence below threshold -- routed to Human Review. "
        f"Action: {review.get('action')}. Reason: {review.get('reason')}"
    ] + (["Draft communication prepared (not sent)."] if communication else [])

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
    submission_llm = submission_agent.build_agent()
    document_llm = document_agent.build_agent()
    risk_llm = risk_agent.build_agent()
    recommendation_llm = recommendation_agent.build_agent()

    human_review_mismatch_llm = _fresh_human_review_agent("HumanReviewAgent_Mismatch")
    human_review_material_llm = _fresh_human_review_agent("HumanReviewAgent_MaterialRisk")
    human_review_low_conf_llm = _fresh_human_review_agent("HumanReviewAgent_LowConfidence")

    return Workflow(
        name="underwriting_workflow_v2",
        edges=[
            ("START", intake, submission_llm, submission_gate),
            (submission_gate, {"complete": document_llm, "incomplete": handle_incomplete}),

            (document_llm, document_gate),
            (document_gate, {"consistent": risk_llm, "mismatch": human_review_mismatch_llm}),
            (human_review_mismatch_llm, handle_mismatch),

            (risk_llm, risk_gate),
            (risk_gate, {"material": human_review_material_llm, "ok": recommendation_llm}),
            (human_review_material_llm, handle_material_risk),

            (recommendation_llm, recommendation_gate),
            (recommendation_gate, {"stp": handle_stp, "low_confidence": human_review_low_conf_llm}),
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
        session_service = InMemorySessionService()
        user_id, session_id = "underwriting_system", str(uuid.uuid4())
        await session_service.create_session(
            app_name="insurance_underwriting_adk_v2", user_id=user_id, session_id=session_id
        )

        workflow = _build_graph()
        runner = Runner(agent=workflow, app_name="insurance_underwriting_adk_v2", session_service=session_service)

        message = types.Content(role="user", parts=[types.Part(text=json.dumps({"file_path": file_path}))])

        final_output = None
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
            if getattr(event, "output", None) is not None:
                final_output = event.output

        if final_output is None:
            raise RuntimeError("Workflow produced no final decision output.")
        return final_output

    return asyncio.run(_run())
