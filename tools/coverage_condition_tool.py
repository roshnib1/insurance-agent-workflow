"""
CoverageConditionTool (ADK tool)

New tool. Codifies the coverage-condition rules that previously lived
only inside recommendation_agent.py's instruction text:
  - HIGH medical_risk -> medical exclusion/loading condition
  - HIGH lifestyle_risk -> lifestyle exclusion (e.g. smoker loading)
  - MEDIUM/HIGH claims_risk -> claims history review required
"""

from typing import Dict, List

from tools._common import log_tool_io


@log_tool_io
def determine_coverage_conditions(
    medical_risk: str = "LOW",
    lifestyle_risk: str = "LOW",
    claims_risk: str = "LOW",
) -> Dict[str, List[str]]:
    """
    Determine coverage conditions based on per-dimension risk levels.

    Args:
        medical_risk: "LOW", "MEDIUM", or "HIGH" (from RiskScoringTool).
        lifestyle_risk: "LOW", "MEDIUM", or "HIGH".
        claims_risk: "LOW", "MEDIUM", or "HIGH".

    Returns:
        {"coverage_conditions": [str, ...]}
    """
    conditions: List[str] = []

    if str(medical_risk or "").strip().upper() == "HIGH":
        conditions.append("Medical exclusion/loading applies for pre-existing conditions.")

    if str(lifestyle_risk or "").strip().upper() == "HIGH":
        conditions.append("Lifestyle-related exclusion (e.g. smoker loading) applies.")

    if str(claims_risk or "").strip().upper() in ("MEDIUM", "HIGH"):
        conditions.append("Claims history review required before final confirmation.")

    return {"coverage_conditions": conditions}
