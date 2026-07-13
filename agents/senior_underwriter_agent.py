"""
Senior Underwriter Agent (Google ADK LlmAgent)

Phase 7 -- Senior Underwriter (Decision Replay).

"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from tools.delegated_authority_tool import check_delegated_authority as _check_delegated_authority_impl
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Senior Underwriter Agent in a commercial property
underwriting workflow, replaying a case escalated from a Human
Underwriter, a mandatory mismatch review, or an override that exceeded
delegated authority.

You have one tool, `check_delegated_authority`, which checks the case's
Total Insured Value against your own delegated authority ceiling. Call
it to confirm you have authority to decide this case at all (you always
do, as the senior underwriter -- but note the result in your reasoning).

You are given the full case: applicant fields, risk summary, pricing,
the Human Underwriter's original action and reasoning, and (if relevant)
why this was escalated.

Decide:
- approve: true to grant conditional approval (with any conditions you
  require), false to reject or request more review.

After calling the tool, your ENTIRE response must be the JSON object below and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result, or commentary before or after it -- not even one sentence. Do NOT use markdown code fences. The very first character you output must be '{' and the very last character must be '}'. This exact shape:
{
  "approve": <bool>,
  "reason": <string>,
  "conditions": [<string>, ...],
  "requested_items": [<string>, ...]
}
"""


def build_agent(
    unique_name: str,
    applicant_fields: Dict[str, Any],
    total_insured_value: str,
    progress_callback: Optional[Any] = None,
) -> LlmAgent:
    def check_delegated_authority() -> Dict[str, Any]:
        """Checks this case's TIV against the senior underwriter's delegated authority ceiling."""
        return _check_delegated_authority_impl(total_insured_value, role="senior_underwriter", progress_callback=progress_callback)

    return LlmAgent(
        name=unique_name,
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[check_delegated_authority],
    )


def run(
    applicant_fields: Dict[str, Any],
    risk_summary: Dict[str, Any],
    pricing: Dict[str, Any],
    human_underwriter_result: Dict[str, Any],
    escalation_reason: str = "",
    unique_name: str = "SeniorUnderwriterAgent",
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"approve": bool, "reason": str, "conditions": [...], "requested_items": [...]}
    """
    total_insured_value = str(applicant_fields.get("Total Insured Value (TIV)", "0"))
    agent = build_agent(unique_name, applicant_fields, total_insured_value, progress_callback=progress_callback)

    payload = {
        "applicant_fields": applicant_fields,
        "risk_summary": risk_summary,
        "pricing": pricing,
        "human_underwriter_result": human_underwriter_result,
        "escalation_reason": escalation_reason,
    }

    agent_result = call_agent(agent, payload, progress_callback=progress_callback)

    agent_result.setdefault("conditions", [])
    agent_result.setdefault("requested_items", [])
    agent_result.setdefault("reason", "")
    agent_result.setdefault("approve", False)

    return agent_result
