"""
PricingTool (ADK tool)

Phase 4 -- Risk Assessment (Pricing Recommendation step).

Deterministic base-rate x loading calculation from the Total Insured
Value (TIV) and risk category, so PricingAgent's job is presenting and
contextualizing a number -- not inventing one. Rates are illustrative
placeholders for the demo, not actuarially derived.
"""

from typing import Any, Dict

from tools._common import ProgressCallback, emit, to_number

TOOL_NAME = "pricing_tool"

# Illustrative base rate per INR 1,000 of TIV, by risk category.
_BASE_RATE_PER_1000 = {"LOW": 0.35, "MEDIUM": 0.55, "HIGH": 0.95}

# Additional loading applied on top of the base rate when risk is material.
_MATERIAL_RISK_LOADING = 0.25


def calculate_pricing(
    total_insured_value: str,
    risk_category: str,
    material_risk: bool,
    deductible: str = "",
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        total_insured_value: raw TIV text, e.g. "INR 185,00,00,000".
        risk_category: "LOW" | "MEDIUM" | "HIGH".
        material_risk: whether Decision 5 flagged this as material.
        deductible: raw deductible text from the proposal, passed through.
        progress_callback: optional before/after event sink.

    Returns:
        {
          "tiv": float | None,
          "base_rate_per_1000": float,
          "loading_applied": float,
          "indicative_premium": float | None,
          "recommendation": str,   # human-readable summary
          "deductible": str,
        }
    """
    emit(progress_callback, "before", TOOL_NAME, risk_category=risk_category, material_risk=material_risk)

    tiv = to_number(total_insured_value)
    base_rate = _BASE_RATE_PER_1000.get(risk_category, 0.55)
    loading = _MATERIAL_RISK_LOADING if material_risk else 0.0
    effective_rate = base_rate * (1 + loading)

    indicative_premium = round((tiv / 1000.0) * effective_rate, 2) if tiv else None

    if material_risk:
        recommendation = (
            f"{risk_category} risk with material hazard -- {int(loading * 100)}% loading applied "
            f"on top of the standard {risk_category.lower()}-risk rate."
        )
    else:
        recommendation = f"{risk_category} risk -- standard rate, no loading."

    result = {
        "tiv": tiv,
        "base_rate_per_1000": base_rate,
        "loading_applied": loading,
        "indicative_premium": indicative_premium,
        "recommendation": recommendation,
        "deductible": deductible,
    }

    emit(progress_callback, "after", TOOL_NAME, indicative_premium=indicative_premium)
    return result
