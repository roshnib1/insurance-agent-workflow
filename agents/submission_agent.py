"""
Submission Intake Agent (Google ADK LlmAgent)

Business question: "Is this submission complete enough to start underwriting?"

Parsing/normalization of the raw PDF/HTML file into ApplicantData happens in
services/ (deterministic, not an LLM concern -- the workflow shouldn't burn
model calls re-deriving what a parser already extracts reliably). This
agent's job is the judgment call on completeness: given the normalized data
and the list of mandatory fields, decide if underwriting can proceed, which
fields are missing, and how confident it is.
"""

from dataclasses import asdict

from pydantic import ValidationError

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, SubmissionIntakeOutput
from services.normalizer import MANDATORY_LABELS, find_missing_mandatory_fields
from tools.completeness_tool import check_submission_completeness
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Submission Intake Agent in an insurance underwriting workflow.

You receive a normalized insurance proposal (JSON) and a list of mandatory
fields required before underwriting can begin.

You have a tool, check_submission_completeness, that runs the deterministic
mandatory-field check. Call it first with the applicant_data you were given.
Then apply your own judgment on top of its result -- for example, spotting
placeholder text like "not provided" / "left blank" / "not applicable" in a
field the tool didn't flag as missing.

Decide:
1. Is the submission complete enough to start underwriting?
2. Which mandatory fields (by their human-readable label) are missing,
   null, empty, or clearly unusable?
3. How confident are you in this completeness assessment (0.0-1.0)?

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
        tools=[check_submission_completeness],
    )


def run(applicant: ApplicantData) -> dict:
    """
    Returns:
        {"complete": bool, "missing_fields": [...], "confidence": float, "notes": [...]}
    """
    # Deterministic pre-check so the LLM has ground truth to reason over
    # (and so completeness is never solely a hallucination-prone judgment).
    deterministic_missing = find_missing_mandatory_fields(applicant)

    payload = {
        "applicant_data": asdict(applicant),
        "mandatory_fields": list(MANDATORY_LABELS.values()),
        "deterministic_missing_fields_check": deterministic_missing,
    }

    agent = build_agent()
    result = call_agent(agent, payload)

    # Validate/coerce the agent's raw JSON against the expected shape now
    # that output_schema is no longer enforcing it for us (output_schema
    # and tools can't be used together in ADK -- see build_agent() above).
    try:
        result = SubmissionIntakeOutput(**result).model_dump()
    except ValidationError:
        pass  # fall through with the raw dict; downstream code still has defaults below

    result.setdefault("missing_fields", [])
    result.setdefault("confidence", 0.5)
    result.setdefault("notes", [])

    # Belt-and-braces: never let the LLM under-report a field the
    # deterministic check flagged as missing.
    missing = sorted(set(result.get("missing_fields", [])) | set(deterministic_missing))
    result["missing_fields"] = missing
    result["complete"] = len(missing) == 0

    return result
