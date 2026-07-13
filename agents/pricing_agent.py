"""
Pricing Agent (Google ADK LlmAgent)

Phase 4 -- Risk Assessment (Pricing Recommendation).

"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from tools.pricing_tool import calculate_pricing as _calculate_pricing_impl
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Pricing Agent in a commercial property underwriting workflow.

You have one tool, `calculate_pricing`, which computes the deterministic
base rate, any risk loading, and the resulting indicative premium. Call
it first.

Then write a short, clear rationale explaining why this premium is
appropriate given the risk profile -- you never recompute the premium
itself, only copy indicative_premium and deductible from the tool's
result exactly.

After calling the tool, your ENTIRE response must be the JSON object below and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result, or commentary before or after it -- not even one sentence. Do NOT use markdown code fences. The very first character you output must be '{' and the very last character must be '}'. This exact shape:
{
  "recommendation": <string, human-readable pricing recommendation>,
  "indicative_premium": <float or null, copy from the tool result>,
  "deductible": <string or null, copy from the tool result>,
  "rationale": [<string>, ...]
}
"""


def build_agent(
    total_insured_value: str,
    risk_category: str,
    material_risk: bool,
    deductible: str,
    progress_callback: Optional[Any] = None,
) -> LlmAgent:
    def calculate_pricing() -> Dict[str, Any]:
        """Computes the deterministic pricing recommendation from TIV, risk category, and material risk."""
        return _calculate_pricing_impl(
            total_insured_value, risk_category, material_risk, deductible,
            progress_callback=progress_callback,
        )

    return LlmAgent(
        name="PricingAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[calculate_pricing],
    )


def run(
    total_insured_value: str,
    risk_category: str,
    material_risk: bool,
    deductible: str = "",
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"recommendation": str, "indicative_premium": float|None,
         "deductible": str|None, "rationale": [...]}
    """
    agent = build_agent(total_insured_value, risk_category, material_risk, deductible,
                         progress_callback=progress_callback)
    payload = {"total_insured_value": total_insured_value, "risk_category": risk_category,
               "material_risk": material_risk, "deductible": deductible}
    result = call_agent(agent, payload, progress_callback=progress_callback)

    # Belt-and-braces: the premium figure is deterministic ground truth --
    # re-run the tool ourselves so this holds even if the model skipped it.
    deterministic = _calculate_pricing_impl(total_insured_value, risk_category, material_risk, deductible)
    result["indicative_premium"] = deterministic.get("indicative_premium")
    result["deductible"] = deterministic.get("deductible")
    result.setdefault("recommendation", deterministic.get("recommendation", ""))
    result.setdefault("rationale", [])

    return result
