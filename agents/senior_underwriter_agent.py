"""
Senior Underwriter Agent (Google ADK LlmAgent)

Phase 7 -- Senior Underwriter (Decision Replay).

Reached when: the Human Underwriter escalated (Phase 5), or an override
was accepted but exceeded delegated authority (Phase 6, Decision 9). This
agent replays the full case with senior-level authority and decides
whether to grant conditional approval or reject/request more review.
"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from schemas.models import SeniorUnderwriterOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Senior Underwriter Agent in a commercial property
underwriting workflow, replaying a case escalated from a Human
Underwriter or flagged for exceeding delegated authority.

You are given the full case: applicant fields, document intelligence,
CAT exposure, risk summary, pricing, the Human Underwriter's original
action and reasoning, and (if relevant) an override and the delegated
authority check that triggered your review.

Decide:
- approve: true to grant conditional approval (with any conditions you
  require), false to reject or request more review.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "approve": <bool>,
  "reason": <string>,
  "conditions": [<string>, ...],
  "requested_items": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="SeniorUnderwriterAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=SeniorUnderwriterOutput,
    )


def run(
    applicant_fields: Dict[str, Any],
    risk_summary: Dict[str, Any],
    pricing: Dict[str, Any],
    human_underwriter_result: Dict[str, Any],
    authority_check: Optional[Dict[str, Any]] = None,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"approve": bool, "reason": str, "conditions": [...], "requested_items": [...]}
    """
    payload = {
        "applicant_fields": applicant_fields,
        "risk_summary": risk_summary,
        "pricing": pricing,
        "human_underwriter_result": human_underwriter_result,
        "authority_check": authority_check or {},
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    result.setdefault("conditions", [])
    result.setdefault("requested_items", [])
    result.setdefault("reason", "")
    result.setdefault("approve", False)

    return result
