"""
FinancialRiskTool (ADK tool)

New tool. Extracts the FINANCIAL scoring rule (up to ~15 pts) that
previously lived only inside risk_agent.py's instruction text: sum
insured as a multiple of declared annual income (>15x high, 10-15x
moderate, <10x normal).
"""

from typing import Any, Dict, Optional

from tools._common import log_tool_io

MAX_FINANCIAL_POINTS = 15


@log_tool_io
def assess_financial_risk(
    sum_insured: Optional[float] = None,
    annual_income: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Score the financial risk dimension (0-15 points) based on the
    sum-insured-to-income multiple.

    Args:
        sum_insured: Requested sum insured.
        annual_income: Declared annual income.

    Returns:
        {"dimension": "financial", "points": int, "max_points": 15,
         "risk_level": "LOW"|"MEDIUM"|"HIGH", "reasoning": [str, ...],
         "income_multiple": float | None}
    """
    if not sum_insured or not annual_income or annual_income <= 0:
        return {
            "dimension": "financial",
            "points": 0,
            "max_points": MAX_FINANCIAL_POINTS,
            "risk_level": "LOW",
            "reasoning": ["Insufficient data to compute sum-insured-to-income multiple."],
            "income_multiple": None,
        }

    multiple = sum_insured / annual_income

    if multiple > 15:
        points, risk_level = 15, "HIGH"
        reasoning = [f"Sum insured is {multiple:.1f}x declared annual income (>15x is high)."]
    elif multiple >= 10:
        points, risk_level = 8, "MEDIUM"
        reasoning = [f"Sum insured is {multiple:.1f}x declared annual income (10-15x is moderate)."]
    else:
        points, risk_level = 0, "LOW"
        reasoning = [f"Sum insured is {multiple:.1f}x declared annual income (<10x is normal)."]

    return {
        "dimension": "financial",
        "points": points,
        "max_points": MAX_FINANCIAL_POINTS,
        "risk_level": risk_level,
        "reasoning": reasoning,
        "income_multiple": round(multiple, 2),
    }
