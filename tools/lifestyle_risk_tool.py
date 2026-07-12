"""
LifestyleRiskTool (ADK tool)

New tool. Extracts the LIFESTYLE scoring rules (up to ~45 pts) that
previously lived only inside risk_agent.py's instruction text:
  - Current smoker -> +20
  - Hazardous occupation exposure (e.g. aviation) -> +15
  - Genuinely hazardous hobbies (skydiving, scuba, motor racing) -> +10
    (benign hobbies like badminton, golf, running, trekking do NOT count,
    matching the original instruction's explicit carve-out)
"""

from typing import Any, Dict, List, Optional

from tools._common import log_tool_io

MAX_LIFESTYLE_POINTS = 45

HAZARDOUS_HOBBY_KEYWORDS = (
    "skydiv", "scuba", "motor racing", "car racing", "mountaineer", "bungee", "paraglid", "base jump",
)
BENIGN_HOBBY_KEYWORDS = (
    "badminton", "golf", "running", "trekking", "walking", "swimming", "cricket", "football",
    "yoga", "cycling", "tennis", "hiking",
)


def _is_negative(value) -> bool:
    """Same fix as tools/medical_risk_tool.py: check the first word, not the
    whole string, so "None" / "None reported" / "Nil" are all correctly
    treated as negative regardless of trailing text."""
    text = str(value or "").strip().lower()
    if not text:
        return True
    first_word = text.split()[0].rstrip(".,;:")
    return first_word in ("none", "no", "nil", "n/a", "nothing")


def _is_hobby_text_benign_only(hobbies_text: str) -> bool:
    parts = [p.strip() for p in hobbies_text.replace(",", "/").split("/") if p.strip()]
    if not parts:
        return True
    return all(any(benign in part for benign in BENIGN_HOBBY_KEYWORDS) for part in parts)


@log_tool_io
def assess_lifestyle_risk(
    smoking_status: Optional[str] = None,
    hazardous_occupation: Optional[str] = None,
    hazardous_hobbies: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Score the lifestyle risk dimension (0-45 points).

    Args:
        smoking_status: Applicant's declared smoking status.
        hazardous_occupation: Applicant's declared aviation/hazardous
            occupation exposure.
        hazardous_hobbies: Applicant's declared hobbies/sports.

    Returns:
        {"dimension": "lifestyle", "points": int, "max_points": 45,
         "risk_level": "LOW"|"MEDIUM"|"HIGH", "reasoning": [str, ...]}
    """
    points = 0
    reasoning: List[str] = []

    smoking = str(smoking_status or "").strip().lower()
    if smoking and smoking not in ("non-smoker", "never", "no", "none", "nil"):
        points += 20
        reasoning.append(f"Current smoker: {smoking_status}")

    occupation = str(hazardous_occupation or "").strip()
    if not _is_negative(occupation):
        points += 15
        reasoning.append(f"Hazardous occupation exposure: {hazardous_occupation}")

    hobbies_text = str(hazardous_hobbies or "").strip().lower()
    if not _is_negative(hobbies_text):
        has_hazardous_keyword = any(kw in hobbies_text for kw in HAZARDOUS_HOBBY_KEYWORDS)
        if has_hazardous_keyword and not _is_hobby_text_benign_only(hobbies_text):
            points += 10
            reasoning.append(f"Hazardous hobby/sport reported: {hazardous_hobbies}")

    points = min(points, MAX_LIFESTYLE_POINTS)
    risk_level = "HIGH" if points >= 30 else "MEDIUM" if points >= 15 else "LOW"

    if not reasoning:
        reasoning.append("No material lifestyle risk factors identified.")

    return {
        "dimension": "lifestyle",
        "points": points,
        "max_points": MAX_LIFESTYLE_POINTS,
        "risk_level": risk_level,
        "reasoning": reasoning,
    }
