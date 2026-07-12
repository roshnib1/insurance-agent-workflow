"""
PropertyRiskScoringTool (ADK tool)

Phase 4 -- Risk Assessment.

Deterministic ground-truth risk score, computed from three inputs so
RiskSummaryAgent has a concrete number to reason over rather than
eyeballing risk from raw text every time:

  1. Declared/undisclosed hazards          (hazard_detection_tool /
                                             mismatch_detection_tool output)
  2. CAT exposure score                    (cat_vendor_tool output)
  3. Building safety attributes            (sprinkler, fire protection,
                                             CCTV, guards, safety audit --
                                             each present/compliant lowers
                                             the score; each absent raises it)

The 45-point "material risk" threshold mirrors the flowchart's
Decision 5 -- exposed here as MATERIAL_RISK_THRESHOLD so the agent's
material_risk flag and this tool's material_risk flag can never disagree.
"""

from typing import Any, Dict, List

from tools._common import ProgressCallback, emit, is_negative_or_none

TOOL_NAME = "property_risk_scoring_tool"

MATERIAL_RISK_THRESHOLD = 45

# (field label, points added if the safety measure is ABSENT/non-compliant)
_SAFETY_FIELDS = (
    ("Sprinkler System", 12),
    ("Fire Protection System", 8),
    ("Smoke Detection", 6),
    ("CCTV Installed", 4),
    ("Security Guards", 4),
    ("Safety Audit Completed", 10),
)


def score_property_risk(
    fields: Dict[str, Any],
    hazard_count: int,
    mismatch_count: int,
    cat_score: int,
    previous_claims_count: int = 0,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        fields: flat proposal {label: value} dict (for safety attributes).
        hazard_count: from hazard_detection_tool.
        mismatch_count: from mismatch_detection_tool.
        cat_score: 0-100, from cat_vendor_tool.
        previous_claims_count: prior claims on this risk.
        progress_callback: optional before/after event sink.

    Returns:
        {
          "risk_score": int (0-100),
          "risk_category": "LOW" | "MEDIUM" | "HIGH",
          "material_risk": bool,
          "score_breakdown": {"hazards": int, "mismatches": int, "cat": int,
                               "safety_gaps": int, "claims_history": int},
          "safety_gaps": [str, ...],
        }
    """
    emit(progress_callback, "before", TOOL_NAME, hazard_count=hazard_count, mismatch_count=mismatch_count)

    hazard_points = min(hazard_count * 10, 30)
    mismatch_points = min(mismatch_count * 15, 30)
    cat_points = round(cat_score * 0.3)
    claims_points = min(previous_claims_count * 5, 15)

    safety_gaps: List[str] = []
    safety_points = 0
    for label, penalty in _SAFETY_FIELDS:
        value = fields.get(label)
        # Compliant if the field has a real answer that isn't an explicit
        # "No"/"None"/absent value -- several safety fields are descriptive
        # ("Wet Riser, Hydrant System...") rather than a literal "Yes -" prefix.
        compliant = bool(value) and not is_negative_or_none(value)
        if not compliant:
            safety_points += penalty
            safety_gaps.append(label)

    raw_score = hazard_points + mismatch_points + cat_points + claims_points + safety_points
    risk_score = min(raw_score, 100)

    if risk_score >= 60:
        category = "HIGH"
    elif risk_score >= 30:
        category = "MEDIUM"
    else:
        category = "LOW"

    result = {
        "risk_score": risk_score,
        "risk_category": category,
        "material_risk": risk_score >= MATERIAL_RISK_THRESHOLD,
        "score_breakdown": {
            "hazards": hazard_points,
            "mismatches": mismatch_points,
            "cat": cat_points,
            "safety_gaps": safety_points,
            "claims_history": claims_points,
        },
        "safety_gaps": safety_gaps,
    }

    emit(progress_callback, "after", TOOL_NAME, risk_score=risk_score, risk_category=category)
    return result
