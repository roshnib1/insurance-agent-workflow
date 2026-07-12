"""
DelegatedAuthorityTool (ADK tool)

Phase 6 -- Override (Decision 9: "Exposure exceeds delegated authority?").

Deterministic authority-limit lookup. Each underwriting role has a fixed
TIV ceiling it may bind or override within; anything above that must
escalate to a Senior Underwriter. Kept as a tool, not agent judgment,
because delegated-authority limits are a compliance control, not
something an LLM should be free to reinterpret case-by-case.
"""

from typing import Any, Dict

from tools._common import ProgressCallback, emit, to_number

TOOL_NAME = "delegated_authority_tool"

# Illustrative delegated-authority ceilings (max TIV a role may bind/override).
DELEGATED_AUTHORITY_LIMITS_INR = {
    "underwriter": 100_00_00_000,        # INR 100 Cr
    "senior_underwriter": 500_00_00_000,  # INR 500 Cr
    "chief_underwriting_officer": None,   # None == unlimited
}


def check_delegated_authority(
    total_insured_value: str,
    role: str = "underwriter",
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        total_insured_value: raw TIV text, e.g. "INR 185,00,00,000".
        role: the underwriting role attempting to approve/override --
            one of "underwriter", "senior_underwriter", "chief_underwriting_officer".
        progress_callback: optional before/after event sink.

    Returns:
        {
          "tiv": float | None,
          "role": str,
          "authority_limit": float | None,
          "exceeds_authority": bool,
          "escalation_required": bool,
        }
    """
    emit(progress_callback, "before", TOOL_NAME, role=role)

    tiv = to_number(total_insured_value)
    limit = DELEGATED_AUTHORITY_LIMITS_INR.get(role, DELEGATED_AUTHORITY_LIMITS_INR["underwriter"])

    exceeds = bool(tiv is not None and limit is not None and tiv > limit)

    result = {
        "tiv": tiv,
        "role": role,
        "authority_limit": limit,
        "exceeds_authority": exceeds,
        "escalation_required": exceeds,
    }

    emit(progress_callback, "after", TOOL_NAME, exceeds_authority=exceeds)
    return result
