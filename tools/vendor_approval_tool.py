"""
VendorApprovalTool (ADK tool)

Phase 3 -- CAT Exposure (Decision 3: "Is external vendor approved?").

Deterministic allowlist check. Kept as a tool (not inline agent logic)
because the approved-vendor list is a compliance artifact that changes
independently of any model behaviour -- CATExposureAgent should never be
in a position to "reason" a disapproved vendor into an approved one.
"""

from typing import Any, Dict

from tools._common import ProgressCallback, emit

TOOL_NAME = "vendor_approval_tool"

# Approved external CAT (catastrophe) modelling vendors. In production this
# would be sourced from a governance/compliance system; hardcoded here as
# the deterministic ground truth for the demo.
APPROVED_CAT_VENDORS = {
    "GeoRisk CAT Analytics",
    "Verisk RMS Property CAT",
    "CoreLogic CAT Modelling",
}


def check_vendor_approval(
    vendor_name: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        vendor_name: the external CAT vendor's name.
        progress_callback: optional before/after event sink.

    Returns:
        {"vendor": str, "approved": bool, "approved_vendor_list": [str, ...]}
    """
    emit(progress_callback, "before", TOOL_NAME, vendor=vendor_name)

    approved = vendor_name in APPROVED_CAT_VENDORS
    result = {
        "vendor": vendor_name,
        "approved": approved,
        "approved_vendor_list": sorted(APPROVED_CAT_VENDORS),
    }

    emit(progress_callback, "after", TOOL_NAME, approved=approved)
    return result
