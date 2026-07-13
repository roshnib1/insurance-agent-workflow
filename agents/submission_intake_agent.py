"""
Submission Intake Agent (Google ADK LlmAgent)

Phase 1 -- Submission Intake.

"""

from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent

from tools.parse_submission_tool import check_completeness as _check_completeness_impl
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Submission Intake Agent in a commercial property underwriting
workflow.

You have one tool, `check_completeness`, which runs the deterministic
mandatory-field check against this submission. Call it first.

Then apply your own judgment on top of that result -- for example,
spotting placeholder or evasive values in a field the deterministic check
didn't flag as literally missing (e.g. "TBD", "N/A", "to be confirmed",
a TIV of zero, an address that's just "same as above").

A field is only "missing" if it has no real value at all -- empty, null,
or a placeholder like the examples above. A field with a genuine negative
or partial answer (e.g. "No", "None", "Not Installed", "Not Applicable
for this site") is present and answered, not missing, even if that answer
is unfavorable -- never add a field to missing_fields just because its
value is negative.

Never report a field as present if check_completeness already flagged it
missing -- you may only ADD fields to missing_fields, never remove ones
the tool found.

After calling the tool, your ENTIRE response must be the JSON object below and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result, or commentary before or after it -- not even one sentence. Do NOT use markdown code fences. The very first character you output must be '{' and the very last character must be '}'. This exact shape:
{
  "complete": <bool>,
  "missing_fields": [<string>, ...],
  "confidence": <float between 0.0 and 1.0>,
  "notes": [<string>, ...]
}
"""


def build_agent(applicant_fields: Dict[str, Any], progress_callback: Optional[Any] = None) -> LlmAgent:
    def check_completeness() -> Dict[str, Any]:
        """Runs the deterministic mandatory-field completeness check on this submission."""
        return _check_completeness_impl(applicant_fields, progress_callback=progress_callback)

    return LlmAgent(
        name="SubmissionIntakeAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[check_completeness],
    )


def run(
    applicant_fields: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"complete": bool, "missing_fields": [...], "confidence": float, "notes": [...]}
    """
    agent = build_agent(applicant_fields, progress_callback=progress_callback)
    result = call_agent(agent, {"applicant_fields": applicant_fields}, progress_callback=progress_callback)

    result.setdefault("missing_fields", [])
    result.setdefault("confidence", 0.85)
    result.setdefault("notes", [])

    # Belt-and-braces: re-run the deterministic check ourselves and never
    # let the agent's answer under-report a field it flagged missing --
    # guards against the model skipping the tool call or misreporting it.
    deterministic = _check_completeness_impl(applicant_fields)
    missing = sorted(set(result.get("missing_fields", [])) | set(deterministic["missing_fields"]))
    result["missing_fields"] = missing
    result["complete"] = len(missing) == 0

    return result