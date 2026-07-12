"""
Submission Intake Agent (Google ADK LlmAgent)

Phase 1 -- Submission Intake.

Business question: "Is this submission complete enough to start
underwriting?" The deterministic mandatory-field check already ran in
property_controller.py (tools.parse_submission_tool) before this agent is
called -- this agent's job is the judgment call on top of it: spotting
placeholder/ambiguous values the deterministic check wouldn't catch
(e.g. a TIV of "TBD", an address that's just "Same as above" with no
prior address on file), and explaining its reasoning.
"""

from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent

from schemas.models import SubmissionIntakeOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Submission Intake Agent in a commercial property underwriting
workflow.

You receive a normalized commercial property proposal (JSON fields) and
the result of a deterministic mandatory-field completeness check that
already ran.

Apply your own judgment on top of that deterministic result -- for
example, spotting placeholder or evasive values in a field the
deterministic check didn't flag as literally missing (e.g. "TBD", "N/A",
"to be confirmed", a TIV of zero, an address that's just "same as
above").

Never report a field as present if the deterministic check already
flagged it missing -- you may only ADD fields to missing_fields, never
remove ones the deterministic check found.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "complete": <bool>,
  "missing_fields": [<string>, ...],
  "confidence": <float between 0.0 and 1.0>,
  "notes": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="SubmissionIntakeAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=SubmissionIntakeOutput,
    )


def run(
    applicant_fields: Dict[str, Any],
    deterministic_missing_fields: List[str],
    mandatory_field_labels: List[str],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Args:
        applicant_fields: flat {label: value} proposal fields.
        deterministic_missing_fields: from tools.parse_submission_tool
            (or services.normalizer.find_missing_mandatory_fields).
        mandatory_field_labels: the full mandatory-field label list, for
            the agent's reference.
        progress_callback: optional before/after event sink (see
            workflow/adk_runtime.py::call_agent).

    Returns:
        {"complete": bool, "missing_fields": [...], "confidence": float, "notes": [...]}
    """
    payload = {
        "applicant_fields": applicant_fields,
        "mandatory_fields": mandatory_field_labels,
        "deterministic_missing_fields_check": deterministic_missing_fields,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    result.setdefault("missing_fields", [])
    result.setdefault("confidence", 0.85)
    result.setdefault("notes", [])

    # Belt-and-braces: never let the LLM under-report a field the
    # deterministic check flagged as missing.
    missing = sorted(set(result.get("missing_fields", [])) | set(deterministic_missing_fields))
    result["missing_fields"] = missing
    result["complete"] = len(missing) == 0

    return result
