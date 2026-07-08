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

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, SubmissionIntakeOutput
from services.normalizer import MANDATORY_LABELS, find_missing_mandatory_fields
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Submission Intake Agent in an insurance underwriting workflow.

You receive a normalized insurance proposal (JSON) and a list of mandatory
fields required before underwriting can begin.

Decide:
1. Is the submission complete enough to start underwriting?
2. Which mandatory fields (by their human-readable label) are missing,
   null, empty, or clearly unusable (e.g. placeholder text)?
3. How confident are you in this completeness assessment (0.0-1.0)?

A field counts as missing if its value is null, empty, or a placeholder
like "not provided" / "left blank" / "not applicable".

Respond ONLY with JSON matching the required schema. Do not add commentary
outside the JSON.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="SubmissionIntakeAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=SubmissionIntakeOutput,
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

    # Belt-and-braces: never let the LLM under-report a field the
    # deterministic check flagged as missing.
    missing = sorted(set(result.get("missing_fields", [])) | set(deterministic_missing))
    result["missing_fields"] = missing
    result["complete"] = len(missing) == 0

    return result
