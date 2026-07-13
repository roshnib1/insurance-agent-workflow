"""
Evidence Generation Agent (Google ADK LlmAgent)

Phase 8 -- Final Decision.


"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from schemas.models import EvidenceSummaryOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Evidence Generation Agent in a commercial property
underwriting workflow.

You are given the complete final case state: applicant fields, document
intelligence, CAT exposure, risk summary, pricing, and the final
decision (status, decision mode, decision maker, recommendation).

Write one clear paragraph summarizing the case and its outcome, suitable
for underwriting leadership (a CUO or CRO skimming a portfolio report).
Reference the specific factors that drove the outcome -- do not write a
generic summary.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "ai_summary": <string>
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="EvidenceGenerationAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=EvidenceSummaryOutput,
    )


def run(
    applicant_fields: Dict[str, Any],
    document_intelligence: Dict[str, Any],
    cat_exposure: Dict[str, Any],
    risk_summary: Dict[str, Any],
    pricing: Dict[str, Any],
    final_decision_context: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> str:
    """Returns the ai_summary string."""
    payload = {
        "applicant_fields": applicant_fields,
        "document_intelligence": document_intelligence,
        "cat_exposure": cat_exposure,
        "risk_summary": risk_summary,
        "pricing": pricing,
        "final_decision_context": final_decision_context,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    return result.get("ai_summary", "")
