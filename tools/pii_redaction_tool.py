"""
PIIRedactionTool (ADK tool)

Phase 3 -- CAT Exposure (Decision 4: "Does payload contain PII?").

Strips personally-identifiable fields (contact name, email, phone, GST/PAN,
registered address) out of any payload before it's sent to an external CAT
vendor API. Property-level fields (address of the *insured location*,
building attributes, CAT-zone data) are left untouched -- those aren't PII
and are exactly what the vendor needs to compute exposure.

Deterministic and allowlist-driven on purpose: redaction must never depend
on a model's judgment call about what "counts" as sensitive.
"""

from typing import Any, Dict, List, Tuple

from tools._common import PII_FIELDS, ProgressCallback, emit

TOOL_NAME = "pii_redaction_tool"

REDACTED_PLACEHOLDER = "[REDACTED]"


def redact_pii(
    payload: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        payload: flat {field: value} dict about to be sent externally.
        progress_callback: optional before/after event sink.

    Returns:
        {
          "redacted_payload": dict,   # safe to send externally
          "pii_found": bool,
          "redacted_fields": [str, ...],
        }
    """
    emit(progress_callback, "before", TOOL_NAME, field_count=len(payload))

    redacted_payload = dict(payload)
    redacted_fields: List[str] = []

    for field in PII_FIELDS:
        if field in redacted_payload and redacted_payload[field]:
            redacted_payload[field] = REDACTED_PLACEHOLDER
            redacted_fields.append(field)

    result = {
        "redacted_payload": redacted_payload,
        "pii_found": len(redacted_fields) > 0,
        "redacted_fields": redacted_fields,
    }

    emit(progress_callback, "after", TOOL_NAME, redacted_count=len(redacted_fields))
    return result
