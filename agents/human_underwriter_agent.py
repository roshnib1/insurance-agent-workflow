"""
Human Underwriter Agent (Google ADK LlmAgent)

Phase 5 -- Human Underwriter.

Simulates the judgment of a human underwriter reviewing the fully
assembled case (submission, document intelligence, CAT exposure, risk
assessment, pricing). Chooses one of Approve / Decline / Escalate /
Override -- property_controller.py's Decision 7 gate routes on this
`action` field into four different branches (Final Approval / Reject /
Senior UW / Governance Check).

This agent proposes the action for a human underwriter to confirm; it
never sends anything itself. If its action implies more information is
needed, property_controller.py drafts the (unsent) email via
tools.communication_tool.
"""

from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent

from schemas.models import HumanUnderwriterOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Human Underwriter Agent in a commercial property underwriting
workflow, simulating the judgment of a human underwriter reviewing a
fully assessed case.

You are given the applicant's proposal fields, document intelligence
findings, CAT exposure results, the risk summary, and the pricing
recommendation.

Decide exactly one action:
- "Approve" -- risk is acceptable at the recommended price, no further
  review needed.
- "Decline" -- risk is unacceptable even with pricing/conditions.
- "Escalate" -- needs a senior underwriter's judgment (e.g. material risk
  with borderline confidence, or exposure near/above your own authority).
- "Override" -- you are consciously approving/proceeding against a
  material-hazard or mismatch finding, with your own justification.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "action": "Approve"|"Decline"|"Escalate"|"Override",
  "reason": <string>,
  "reviewer_notes": [<string>, ...],
  "conditions": [<string>, ...]
}
"""

VALID_ACTIONS = {"Approve", "Decline", "Escalate", "Override"}


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="HumanUnderwriterAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=HumanUnderwriterOutput,
    )


def run(
    applicant_fields: Dict[str, Any],
    document_intelligence: Dict[str, Any],
    cat_exposure: Dict[str, Any],
    risk_summary: Dict[str, Any],
    pricing: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"action": "Approve"|"Decline"|"Escalate"|"Override",
         "reason": str, "reviewer_notes": [...], "conditions": [...]}
    """
    payload = {
        "applicant_fields": applicant_fields,
        "document_intelligence": document_intelligence,
        "cat_exposure": cat_exposure,
        "risk_summary": risk_summary,
        "pricing": pricing,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    result.setdefault("reviewer_notes", [])
    result.setdefault("conditions", [])
    result.setdefault("reason", "")

    # Fallback safeguard: an invalid/missing action always escalates
    # rather than silently defaulting to an approval-shaped path.
    if result.get("action") not in VALID_ACTIONS:
        result["action"] = "Escalate"
        result["reason"] = result.get("reason") or "Underwriter action was unclear; escalated as a safeguard."

    return result
