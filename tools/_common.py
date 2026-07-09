"""
Internal helpers shared by the tools in this package.

Not exposed as an ADK tool itself (not passed in any agent's `tools=[...]`)
-- just a small conversion utility so each tool doesn't duplicate the same
dict -> ApplicantData reconstruction logic.
"""

from dataclasses import fields as dataclass_fields
from typing import Any, Dict

from schemas.models import ApplicantData

_APPLICANT_FIELD_NAMES = {f.name for f in dataclass_fields(ApplicantData)}


def dict_to_applicant(data: Dict[str, Any]) -> ApplicantData:
    """Reconstruct an ApplicantData instance from a plain dict (e.g. as
    passed back and forth through an LLM tool call), ignoring any extra
    keys that aren't part of the schema."""
    filtered = {k: v for k, v in (data or {}).items() if k in _APPLICANT_FIELD_NAMES}
    return ApplicantData(**filtered)
