"""
Risk Summary Agent (Google ADK LlmAgent)

Phase 4 -- Risk Assessment.

tools.property_risk_scoring_tool already computed the deterministic
risk_score / risk_category / material_risk flag in property_controller.py
before this agent runs. This agent's job is producing the plain-language
risk narrative and bullet-point reasoning an underwriter would want to
read -- it never disagrees with the deterministic score or the material
risk gate the rest of the workflow branches on.
"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from schemas.models import RiskSummaryOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Risk Summary Agent in a commercial property underwriting
workflow.

You are given a deterministic risk score (0-100), risk category, material
risk flag, and score breakdown that already ran. Your job is to write the
plain-language summary and bullet-point reasoning an underwriter would
want -- referencing the specific hazards, CAT exposure, safety gaps, and
claims history that drove the score.

You must copy risk_score, risk_category, and material_risk exactly as
given -- never recompute or disagree with them.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "risk_score": <int, copy from input>,
  "risk_category": <string, copy from input>,
  "material_risk": <bool, copy from input>,
  "confidence": <float between 0.0 and 1.0>,
  "summary": <string>,
  "reasoning": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="RiskSummaryAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=RiskSummaryOutput,
    )


def run(
    risk_score_result: Dict[str, Any],
    hazard_scan: Dict[str, Any],
    mismatch_scan: Dict[str, Any],
    cat_result: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Args:
        risk_score_result: tools.property_risk_scoring_tool.score_property_risk(...) output.
        hazard_scan, mismatch_scan, cat_result: the upstream deterministic
            results that fed into the risk score, for the agent's context.
        progress_callback: optional before/after event sink.

    Returns:
        {"risk_score": int, "risk_category": str, "material_risk": bool,
         "confidence": float, "summary": str, "reasoning": [...]}
    """
    payload = {
        "risk_score_result": risk_score_result,
        "hazard_scan": hazard_scan,
        "mismatch_scan": mismatch_scan,
        "cat_result": cat_result,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    # Belt-and-braces: the score/category/material_risk gate is
    # deterministic ground truth, never the LLM's to change.
    result["risk_score"] = risk_score_result.get("risk_score", 0)
    result["risk_category"] = risk_score_result.get("risk_category", "LOW")
    result["material_risk"] = risk_score_result.get("material_risk", False)
    result.setdefault("confidence", 0.85)
    result.setdefault("reasoning", [])
    result.setdefault("summary", "")

    return result
