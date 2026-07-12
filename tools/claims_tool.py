"""
ClaimsHistoryTool (ADK tool)

New tool. Extracts the CLAIMS scoring rule (up to ~15 pts) that
previously lived only inside risk_agent.py's instruction text: any
previous claim on record adds weight.
"""

from typing import Any, Dict, List, Optional

from tools._common import log_tool_io

MAX_CLAIMS_POINTS = 15


@log_tool_io
def assess_claims_risk(
    previous_claims_filed: Optional[str] = None,
    claims_details: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Score the claims-history risk dimension (0-15 points).

    Args:
        previous_claims_filed: Applicant's declared "Yes"/"No" answer.
        claims_details: Structured rows of previous claims, if any
            (as produced by the html/pdf parsers' claims_rows).

    Returns:
        {"dimension": "claims", "points": int, "max_points": 15,
         "risk_level": "LOW"|"MEDIUM", "reasoning": [str, ...]}
    """
    declared = str(previous_claims_filed or "").strip().lower()
    has_declared_claim = declared in ("yes", "y", "true")
    has_claim_rows = bool(claims_details)

    if has_declared_claim or has_claim_rows:
        points = MAX_CLAIMS_POINTS
        risk_level = "MEDIUM"
        reasoning = ["Previous claim(s) on record."]
        if claims_details:
            reasoning.append(f"{len(claims_details)} claim record(s) found in claim history.")
    else:
        points = 0
        risk_level = "LOW"
        reasoning = ["No previous claims on record."]

    return {
        "dimension": "claims",
        "points": points,
        "max_points": MAX_CLAIMS_POINTS,
        "risk_level": risk_level,
        "reasoning": reasoning,
    }
