"""
HazardDetectionTool (ADK tool)

Phase 2 -- Document Intelligence.

Scans the proposal's "Operational Hazards" fields (Electrical Hazards,
Chemical Storage, Flammable/Explosive Materials, High Temperature
Equipment, Heavy Machinery, Hazardous Processes, Warehouse Storage) for
anything declared as present, so DocumentIntelligenceAgent has a
deterministic starting point before reasoning over cross-document
consistency with attached inspection reports.

This tool only looks at what the *proposal itself* declares. Comparing
that declaration against an attached electrical/engineering report is
mismatch_detection_tool's job.
"""

from typing import Any, Dict, List

from tools._common import HAZARD_FIELDS, ProgressCallback, emit, is_negative_or_none

TOOL_NAME = "hazard_detection_tool"


def detect_hazards(
    fields: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        fields: flat {label: value} dict, as produced by parse_submission_tool.
        progress_callback: optional before/after event sink.

    Returns:
        {
          "hazards_declared": [{"field": str, "value": str}, ...],
          "hazard_count": int,
          "has_declared_hazard": bool,
        }
    """
    emit(progress_callback, "before", TOOL_NAME, fields_checked=len(HAZARD_FIELDS))

    declared: List[Dict[str, str]] = []
    for label in HAZARD_FIELDS:
        value = fields.get(label)
        if value and not is_negative_or_none(value):
            declared.append({"field": label, "value": value})

    result = {
        "hazards_declared": declared,
        "hazard_count": len(declared),
        "has_declared_hazard": len(declared) > 0,
    }

    emit(progress_callback, "after", TOOL_NAME, hazard_count=result["hazard_count"])
    return result
