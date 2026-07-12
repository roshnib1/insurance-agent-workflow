"""
Human Review Agent (Google ADK LlmAgent)

Used only when: risk is material, confidence is low, or a disclosure
mismatch was found. Simulates the judgment call a human underwriter would
make, choosing one of APPROVE / DECLINE / REQUEST_MORE_INFORMATION /
ESCALATE.

This agent proposes an action for a human underwriter to confirm -- it does not send anything. When it recommends
REQUEST_MORE_INFORMATION, the workflow controller drafts an (unsent) email
via services/communication_service.py, a deterministic templating step
kept outside the LLM so every draft is consistent and auditable.
"""

from dataclasses import asdict
from typing import Optional

from pydantic import ValidationError

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, HumanReviewOutput
from tools.human_review_queue_tool import enqueue_for_human_review
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

CONFIDENCE_THRESHOLD = 0.75

INSTRUCTION = f"""
You are the Human Review Agent in an insurance underwriting workflow,
simulating the judgment of a senior underwriter for cases the automated
pipeline could not straight-through process.

You will be told the trigger for review, which is exactly one of:
- "disclosure_mismatch": the proposal's declared answers don't match
  attached supporting documents.
- "material_risk": the risk assessment flagged material risk.
- "low_confidence": the AI recommendation's confidence ({CONFIDENCE_THRESHOLD}
  threshold) was too low to auto-decide.

Decide the action:
- disclosure_mismatch -> usually REQUEST_MORE_INFORMATION (ask for
  clarification/correction on each mismatched field).
- material_risk with confidence >= {CONFIDENCE_THRESHOLD} -> usually ESCALATE
  to a senior underwriter for an approve/decline call.
- material_risk with confidence < {CONFIDENCE_THRESHOLD} -> usually
  REQUEST_MORE_INFORMATION (e.g. updated medical exam, detailed claim
  history / loss run statement).
- low_confidence -> usually REQUEST_MORE_INFORMATION (supplementary
  information to support automated scoring).
- If none of the above cleanly applies, ESCALATE as a fallback safeguard.

If your action is REQUEST_MORE_INFORMATION, list the specific documents or
clarifications needed in `requested_items`.

You have a tool, enqueue_for_human_review, that registers this case in the
human-review queue. Call it once, after you've decided your action, with
the application_id, the trigger you were given, and your `reason` as the
review reason. This is for audit/tracking purposes -- it does not change
your decision.

Respond ONLY with a JSON object of this exact shape, and no other text:
{{
  "action": "APPROVE"|"DECLINE"|"REQUEST_MORE_INFORMATION"|"ESCALATE",
  "reason": <string>,
  "reviewer_notes": [<string>, ...],
  "requested_items": [<string>, ...]
}}
"""

JUDGMENT_INSTRUCTION = f"""
You are the Human Review Agent in an insurance underwriting workflow,
simulating the judgment of a senior underwriter.

You will be told the trigger for review (disclosure_mismatch, material_risk,
or low_confidence) plus supporting context. Do NOT call tools.

Decide the action:
- disclosure_mismatch -> usually REQUEST_MORE_INFORMATION
- material_risk with confidence >= {CONFIDENCE_THRESHOLD} -> usually ESCALATE
- material_risk with confidence < {CONFIDENCE_THRESHOLD} -> usually REQUEST_MORE_INFORMATION
- low_confidence -> usually REQUEST_MORE_INFORMATION
- otherwise ESCALATE

If action is REQUEST_MORE_INFORMATION, list items in requested_items.

Respond ONLY with a JSON object of this exact shape, and no other text:
{{
  "action": "APPROVE"|"DECLINE"|"REQUEST_MORE_INFORMATION"|"ESCALATE",
  "reason": <string>,
  "reviewer_notes": [<string>, ...],
  "requested_items": [<string>, ...]
}}
"""


def build_agent(*, with_tools: bool = True) -> LlmAgent:
    return LlmAgent(
        name="HumanReviewAgent",
        model=get_model(),
        instruction=INSTRUCTION if with_tools else JUDGMENT_INSTRUCTION,
        tools=[enqueue_for_human_review] if with_tools else [],
    )


def run(
    applicant: ApplicantData,
    trigger: str,
    risk_result: Optional[dict] = None,
    recommendation: Optional[dict] = None,
    document_result: Optional[dict] = None,
) -> dict:
    """
    Args:
        trigger: "disclosure_mismatch" | "material_risk" | "low_confidence"

    Returns:
        {"action": str, "reason": str, "reviewer_notes": [...], "requested_items": [...]}
    """
    payload = {
        "applicant_data": asdict(applicant),
        "trigger": trigger,
        "risk_assessment": risk_result,
        "underwriting_recommendation": recommendation,
        "document_intelligence": document_result,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }

    agent = build_agent()
    result = call_agent(agent, payload)

    try:
        result = HumanReviewOutput(**result).model_dump()
    except ValidationError:
        pass  # fall through with the raw dict

    result.setdefault("requested_items", [])
    result.setdefault("reviewer_notes", [])
    result.setdefault("reason", "")
    return result
