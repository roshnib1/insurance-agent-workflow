"""
Internal helpers shared by every tool in this package.

Not exposed as an ADK tool itself (never passed in an agent's `tools=[...]`)
-- just the small utilities every tool below needs so business logic
doesn't repeat itself:

  * `emit()` -- the before/after callback convention used by every tool
    function in this package. Every public tool accepts an optional
    `progress_callback` and calls `emit(progress_callback, "before", ...)`
    as its first line and `emit(progress_callback, "after", ...)` as its
    last, so workflow/progress.py can subscribe to a uniform event shape
    (`{"phase", "step", "event", "tool", ...}`) regardless of which tool
    fired it. A tool never *requires* a callback -- this makes every tool
    trivially unit-testable on its own with no controller/progress wiring.

  * Small field-name constants mirrored here (not yet imported from
    schemas.models, which lands in a later module). Once schemas/models.py
    exists, these will be replaced by a single import; keeping them local
    for now means this tools/ package works standalone.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

# ---------------------------------------------------------------------------
# Callback convention (before/after every tool step)
# ---------------------------------------------------------------------------

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def emit(callback: ProgressCallback, event: str, tool: str, **data: Any) -> None:
    """
    Fire a structured progress event if a callback was supplied.

    event: "before" | "after" | "failed"
    tool:  the tool's own name, e.g. "cat_vendor_tool"
    data:  any extra structured fields (counts, decisions, ids, etc.)

    Never raises -- a broken callback (e.g. a UI widget that's gone away)
    must never take down the underwriting workflow itself.
    """
    if callback is None:
        return
    try:
        callback({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "event": event,
            **data,
        })
    except Exception:
        pass


def new_ticket_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Small shared parsing/formatting helpers
# ---------------------------------------------------------------------------

def to_number(value: Optional[str]) -> Optional[float]:
    """'INR 185,00,00,000' -> 1850000000.0 ; None-safe."""
    if not value:
        return None
    digits = re.sub(r"[^\d.]", "", str(value))
    return float(digits) if digits else None


def is_affirmative(value: Optional[str]) -> bool:
    """'Yes - 100% Coverage, NFPA-13 Compliant' -> True ; 'No' -> False."""
    if not value:
        return False
    return str(value).strip().lower().startswith("yes")


def is_negative_or_none(value: Optional[str]) -> bool:
    """'None Reported' / 'No' / '' / None -> True."""
    if not value:
        return True
    lowered = str(value).strip().lower()
    return lowered in ("no", "none", "none reported", "n/a", "not applicable", "nil")


# Mandatory proposal fields required before underwriting can start.
# (Mirrors the eventual schemas.models.MANDATORY_LABELS -- kept local here.)
MANDATORY_LABELS: Dict[str, str] = {
    "proposal_number": "Proposal Number",
    "business_name": "Business Name",
    "primary_property_address": "Primary Property Address",
    "total_insured_value": "Total Insured Value (TIV)",
    "building_type": "Building Type",
    "construction_material": "Construction Material",
    "occupancy_type": "Occupancy Type",
    "requested_sum_insured": "Requested Sum Insured",
    "flood_zone": "Flood Zone",
    "earthquake_zone": "Earthquake Zone",
}

# PII-bearing fields that must never leave the system unredacted
# (e.g. in a payload sent to an external CAT vendor).
PII_FIELDS = (
    "Contact Person", "Email", "Phone", "GST Number", "PAN Number",
    "Registered Address",
)

# Fields inspected for undisclosed/underdeclared physical hazards.
HAZARD_FIELDS = (
    "Electrical Hazards", "Chemical Storage", "Flammable Materials",
    "Explosive Materials", "High Temperature Equipment", "Heavy Machinery",
    "Hazardous Processes", "Warehouse Storage",
)
