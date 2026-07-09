"""
PremiumRecommendationTool (ADK tool)

New tool. Codifies the premium-band rules that previously lived only
inside recommendation_agent.py's instruction text:
  - LOW risk category -> standard rate, no loading
  - MEDIUM -> standard + 15-25% risk loading
  - HIGH -> standard + 40%+ loading or refer to specialist pricing
"""

from typing import Dict


def recommend_premium(risk_category: str) -> Dict[str, str]:
    """
    Recommend premium guidance based on risk category.

    Args:
        risk_category: "LOW", "MEDIUM", or "HIGH" (from RiskScoringTool).

    Returns:
        {"premium": "<guidance text>", "loading_band": "<band label>"}
    """
    category = str(risk_category or "").strip().upper()

    if category == "LOW":
        return {"premium": "Standard rate, no loading.", "loading_band": "0%"}
    if category == "MEDIUM":
        return {"premium": "Standard rate plus 15-25% risk loading.", "loading_band": "15-25%"}
    if category == "HIGH":
        return {
            "premium": "Standard rate plus 40%+ loading, or refer to specialist pricing.",
            "loading_band": "40%+",
        }
    return {"premium": "Insufficient data to recommend premium.", "loading_band": "UNKNOWN"}
