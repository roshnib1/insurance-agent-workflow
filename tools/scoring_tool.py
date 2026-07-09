"""
RiskScoringTool (ADK tool)

New tool. Aggregates the four dimension-level risk tool outputs
(MedicalRiskTool, LifestyleRiskTool, FinancialRiskTool, ClaimsHistoryTool)
into the overall risk_score / risk_category / material_risk flag.

Previously this aggregation was split between prose in risk_agent.py's
instruction and a post-hoc Python patch applied *after* the LLM
responded (risk_agent.run() recomputing material_risk from
result["risk_score"]). This tool becomes the single source of truth for
that aggregation, anchored to the same MATERIAL_RISK_THRESHOLD = 45 used
throughout the rest of the project (risk_agent.py, controller.py).
"""

from typing import Any, Dict, List

MATERIAL_RISK_THRESHOLD = 45


def compute_overall_risk_score(
    medical_result: Dict[str, Any],
    lifestyle_result: Dict[str, Any],
    financial_result: Dict[str, Any],
    claims_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Combine the four risk-dimension tool results into an overall risk score.

    Args:
        medical_result: Output of assess_medical_risk.
        lifestyle_result: Output of assess_lifestyle_risk.
        financial_result: Output of assess_financial_risk.
        claims_result: Output of assess_claims_risk.

    Returns:
        {
          "risk_score": int (0-100),
          "risk_category": "LOW"|"MEDIUM"|"HIGH",
          "material_risk": bool,
          "medical_risk": "LOW"|"MEDIUM"|"HIGH",
          "lifestyle_risk": "LOW"|"MEDIUM"|"HIGH",
          "financial_risk": "LOW"|"MEDIUM"|"HIGH",
          "claims_risk": "LOW"|"MEDIUM"|"HIGH",
          "reasoning": [str, ...]   # combined reasoning from all four dimensions
        }
    """
    dims = [medical_result, lifestyle_result, financial_result, claims_result]
    risk_score = sum(int(d.get("points", 0)) for d in dims)
    risk_score = max(0, min(100, risk_score))

    if risk_score >= MATERIAL_RISK_THRESHOLD:
        risk_category = "HIGH"
    elif risk_score >= 20:
        risk_category = "MEDIUM"
    else:
        risk_category = "LOW"

    reasoning: List[str] = []
    for d in dims:
        reasoning.extend(d.get("reasoning", []))

    return {
        "risk_score": risk_score,
        "risk_category": risk_category,
        "material_risk": risk_score >= MATERIAL_RISK_THRESHOLD,
        "medical_risk": medical_result.get("risk_level", "LOW"),
        "lifestyle_risk": lifestyle_result.get("risk_level", "LOW"),
        "financial_risk": financial_result.get("risk_level", "LOW"),
        "claims_risk": claims_result.get("risk_level", "LOW"),
        "reasoning": reasoning,
    }
