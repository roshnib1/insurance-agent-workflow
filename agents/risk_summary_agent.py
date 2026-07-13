"""
Risk Summary Agent (Google ADK LlmAgent)

Phase 4 -- Risk Assessment.

"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from tools.property_risk_scoring_tool import score_property_risk as _score_property_risk_impl
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Risk Summary Agent in a commercial property underwriting
workflow.

You have one tool, `score_property_risk`, which computes the
deterministic risk score (0-100), risk category, material risk flag, and
score breakdown. Call it first.

Then write the plain-language summary and bullet-point reasoning an
underwriter would want -- referencing the specific hazards, CAT
exposure, safety gaps, and claims history that drove the score. You must
copy risk_score, risk_category, and material_risk from the tool's result
exactly -- never recompute or disagree with them.

After calling the tool, your ENTIRE response must be the JSON object below and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result, or commentary before or after it -- not even one sentence. Do NOT use markdown code fences. The very first character you output must be '{' and the very last character must be '}'. This exact shape:
{
  "risk_score": <int, copy from the tool result>,
  "risk_category": <string, copy from the tool result>,
  "material_risk": <bool, copy from the tool result>,
  "confidence": <float between 0.0 and 1.0>,
  "summary": <string>,
  "reasoning": [<string>, ...]
}
"""


def build_agent(
    applicant_fields: Dict[str, Any],
    hazard_count: int,
    mismatch_count: int,
    cat_score: int,
    previous_claims_count: int,
    progress_callback: Optional[Any] = None,
) -> LlmAgent:
    def score_property_risk() -> Dict[str, Any]:
        """Computes the deterministic property risk score from hazards, CAT exposure, safety attributes, and claims history."""
        return _score_property_risk_impl(
            applicant_fields, hazard_count, mismatch_count, cat_score, previous_claims_count,
            progress_callback=progress_callback,
        )

    return LlmAgent(
        name="RiskSummaryAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[score_property_risk],
    )


def run(
    applicant_fields: Dict[str, Any],
    hazard_count: int,
    mismatch_count: int,
    cat_score: int,
    previous_claims_count: int,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"risk_score": int, "risk_category": str, "material_risk": bool,
         "confidence": float, "summary": str, "reasoning": [...]}
    """
    agent = build_agent(applicant_fields, hazard_count, mismatch_count, cat_score, previous_claims_count,
                         progress_callback=progress_callback)
    payload = {"hazard_count": hazard_count, "mismatch_count": mismatch_count,
               "cat_score": cat_score, "previous_claims_count": previous_claims_count}
    result = call_agent(agent, payload, progress_callback=progress_callback)

    # Belt-and-braces: the score/category/material_risk gate is
    # deterministic ground truth, never the LLM's to change -- re-run the
    # tool ourselves so this holds even if the model skipped calling it.
    deterministic = _score_property_risk_impl(applicant_fields, hazard_count, mismatch_count, cat_score, previous_claims_count)
    result["risk_score"] = deterministic["risk_score"]
    result["risk_category"] = deterministic["risk_category"]
    result["material_risk"] = deterministic["material_risk"]
    result.setdefault("confidence", 0.85)
    result.setdefault("reasoning", [])
    result.setdefault("summary", "")

    return result
