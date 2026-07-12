"""
MedicalRiskTool (ADK tool)

New tool. Extracts the MEDICAL scoring rules (up to ~45 pts) that
previously lived only inside risk_agent.py's instruction text, as one of
four dimension-level tools that RiskScoringTool later aggregates. Mirrors
the exact weighting described in the original instruction:
  - Existing medical conditions reported -> +20
  - Hospitalization history (last ~10 years) -> +15
  - BMI >= 30 (obesity) -> +10; BMI 25-30 (overweight) -> +5
"""

from typing import Any, Dict, Optional

from tools._common import log_tool_io

MAX_MEDICAL_POINTS = 45


def _is_negative(value: Optional[str]) -> bool:
    """True if `value` reads as a negative/absent declaration.

    Bug fix: the previous check compared the *whole* string against
    ("none", "no", "nil"), so real proposal phrasing like "None reported"
    or "None in the last 10 years" never matched and was scored as if the
    applicant DID have a condition/hospitalization. Checking just the
    first word instead correctly treats those as negative, while a real
    condition (e.g. "Nodule found in lung scan") still isn't misread as
    negative just because it happens to start with similar letters.
    """
    text = str(value or "").strip().lower()
    if not text:
        return True
    first_word = text.split()[0].rstrip(".,;:")
    return first_word in ("none", "no", "nil", "n/a", "nothing")


@log_tool_io
def assess_medical_risk(
    medical_conditions: Optional[str] = None,
    hospitalization_history: Optional[str] = None,
    bmi: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Score the medical risk dimension (0-45 points).

    Args:
        medical_conditions: Applicant's declared existing medical conditions.
        hospitalization_history: Applicant's declared hospitalization history.
        bmi: Applicant's BMI, if known.

    Returns:
        {"dimension": "medical", "points": int, "max_points": 45,
         "risk_level": "LOW"|"MEDIUM"|"HIGH", "reasoning": [str, ...]}
    """
    points = 0
    reasoning = []

    if not _is_negative(medical_conditions):
        points += 20
        reasoning.append(f"Existing medical conditions reported: {medical_conditions}")

    if not _is_negative(hospitalization_history):
        points += 15
        reasoning.append(f"Hospitalization history reported: {hospitalization_history}")

    if bmi is not None:
        if bmi >= 30:
            points += 10
            reasoning.append(f"BMI {bmi} indicates obesity.")
        elif bmi >= 25:
            points += 5
            reasoning.append(f"BMI {bmi} indicates overweight.")

    points = min(points, MAX_MEDICAL_POINTS)
    risk_level = "HIGH" if points >= 30 else "MEDIUM" if points >= 15 else "LOW"

    if not reasoning:
        reasoning.append("No material medical risk factors identified.")

    return {
        "dimension": "medical",
        "points": points,
        "max_points": MAX_MEDICAL_POINTS,
        "risk_level": risk_level,
        "reasoning": reasoning,
    }
