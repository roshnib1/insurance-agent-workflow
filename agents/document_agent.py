"""
Document Intelligence Agent (Google ADK LlmAgent)

Business question: "Can we trust the submitted information?"

Receives the normalized applicant data plus any attached supporting
documents (medical report, salary proof, claim history extract -- already
extracted into simple tables by services/html_parser.py) and reasons about
whether the proposal's self-declared answers are consistent with what the
supporting documents actually show.
"""

from dataclasses import asdict

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, DocumentIntelligenceOutput
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Document Intelligence Agent in an insurance underwriting workflow.

You receive normalized applicant data plus any attached supporting documents
(e.g. a medical examination report, salary proof, or claim history extract),
each represented as a list of {label: value} rows.

Decide whether the applicant's self-declared answers on the proposal are
CONSISTENT with what the attached documents actually show. Pay particular
attention to:
- Smoking status (declared vs. medical report finding)
- Previous claims filed (declared "No" vs. a claim history extract that
  actually lists claims)
- Declared annual income vs. salary proof / Form 16 (flag if the variance
  exceeds roughly 15%)

For every mismatch found, add an entry to `issues` with keys:
"field", "declared", "found". If there are no attached documents, or
everything lines up, `consistent` should be true and `issues` empty.

Respond ONLY with JSON matching the required schema. Do not add commentary
outside the JSON.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="DocumentIntelligenceAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=DocumentIntelligenceOutput,
    )


def run(applicant: ApplicantData) -> dict:
    """
    Returns:
        {"consistent": bool, "issues": [...], "extracted_data": {...}, "notes": [...]}
    """
    payload = {
        "applicant_data": asdict(applicant),
        "attached_documents": applicant.attached_documents,
    }

    agent = build_agent()
    result = call_agent(agent, payload)

    result.setdefault("issues", [])
    result.setdefault("extracted_data", {})
    result["consistent"] = len(result["issues"]) == 0

    return result
