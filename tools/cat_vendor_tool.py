"""
CATVendorTool (ADK tool, MOCKED)

Phase 3 -- CAT Exposure.

Represents the call to an external catastrophe-modelling vendor API
(flood/earthquake/cyclone/wildfire exposure scoring for the property's
coordinates). No real vendor integration exists yet -- this is a
deterministic stub over the proposal's own "CAT Exposure Information"
section fields, kept simple so it can be swapped for a real HTTP
integration later without changing the agent or controller code that
calls it.

Must only ever be called with an already-redacted payload -- the
controller is responsible for running pii_redaction_tool first.
"""

import re
from typing import Any, Dict

from tools._common import ProgressCallback, emit

TOOL_NAME = "cat_vendor_tool"

_ZONE_RISK_SCORES = {
    # Flood zones (letter grade -> points)
    "A": 40, "B": 25, "C": 10, "D": 5,
    # Earthquake zones (roman numeral -> points; Zone V is highest in IS 1893)
    "I": 5, "II": 10, "III": 20, "IV": 30, "V": 45,
}


def _zone_letter_or_numeral(value: str) -> str:
    match = re.search(r"Zone\s+([A-Z]+|[IVX]+)", value or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def call_cat_vendor(
    vendor_name: str,
    redacted_payload: Dict[str, Any],
    flood_zone: str,
    earthquake_zone: str,
    cyclone_zone: str,
    wildfire_zone: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        vendor_name: the (already-approved) CAT vendor's name.
        redacted_payload: PII-safe payload, as returned by pii_redaction_tool.
        flood_zone / earthquake_zone / cyclone_zone / wildfire_zone:
            raw text values from the proposal's "CAT Exposure Information"
            section, e.g. "Zone C - Low Risk", "Zone II - Low Seismic Risk".
        progress_callback: optional before/after event sink.

    Returns:
        {
          "vendor": str,
          "cat_score": int,          # 0-100, higher = more exposed
          "cat_category": "LOW" | "MEDIUM" | "HIGH",
          "flood_points": int, "earthquake_points": int,
          "cyclone_prone": bool, "wildfire_exposed": bool,
        }
    """
    emit(progress_callback, "before", TOOL_NAME, vendor=vendor_name)

    flood_points = _ZONE_RISK_SCORES.get(_zone_letter_or_numeral(flood_zone), 15)
    eq_points = _ZONE_RISK_SCORES.get(_zone_letter_or_numeral(earthquake_zone), 15)

    cyclone_prone = "non-cyclone" not in (cyclone_zone or "").lower() and bool((cyclone_zone or "").strip())
    wildfire_exposed = "negligible" not in (wildfire_zone or "").lower() and bool((wildfire_zone or "").strip())

    cat_score = flood_points + eq_points + (15 if cyclone_prone else 0) + (10 if wildfire_exposed else 0)
    cat_score = min(cat_score, 100)

    if cat_score >= 55:
        category = "HIGH"
    elif cat_score >= 25:
        category = "MEDIUM"
    else:
        category = "LOW"

    result = {
        "vendor": vendor_name,
        "cat_score": cat_score,
        "cat_category": category,
        "flood_points": flood_points,
        "earthquake_points": eq_points,
        "cyclone_prone": cyclone_prone,
        "wildfire_exposed": wildfire_exposed,
    }

    emit(progress_callback, "after", TOOL_NAME, cat_score=cat_score, cat_category=category)
    return result
