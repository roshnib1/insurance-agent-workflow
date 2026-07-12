"""
Pricing Agent (Google ADK LlmAgent)

Phase 4 -- Risk Assessment (Pricing Recommendation).

tools.pricing_tool already computed the deterministic base rate, loading,
and indicative premium in property_controller.py before this agent runs.
This agent's job is writing the underwriter-facing rationale for that
number -- it never recomputes the premium itself.
"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from schemas.models import PricingOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Pricing Agent in a commercial property underwriting workflow.

You are given a deterministic pricing calculation (base rate, any risk
loading applied, and the resulting indicative premium) that already ran.
Your job is to write a short, clear rationale explaining why this premium
is appropriate given the risk profile -- you never recompute the premium
itself.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "recommendation": <string, human-readable pricing recommendation>,
  "indicative_premium": <float or null, copy from input>,
  "deductible": <string or null, copy from input>,
  "rationale": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="PricingAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=PricingOutput,
    )


def run(
    pricing_result: Dict[str, Any],
    risk_category: str,
    material_risk: bool,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Args:
        pricing_result: tools.pricing_tool.calculate_pricing(...) output.
        risk_category, material_risk: for the agent's context.
        progress_callback: optional before/after event sink.

    Returns:
        {"recommendation": str, "indicative_premium": float|None,
         "deductible": str|None, "rationale": [...]}
    """
    payload = {
        "pricing_result": pricing_result,
        "risk_category": risk_category,
        "material_risk": material_risk,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    # Belt-and-braces: the premium figure is deterministic ground truth.
    result["indicative_premium"] = pricing_result.get("indicative_premium")
    result["deductible"] = pricing_result.get("deductible")
    result.setdefault("recommendation", pricing_result.get("recommendation", ""))
    result.setdefault("rationale", [])

    return result
