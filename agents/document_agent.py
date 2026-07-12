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

from pydantic import ValidationError

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, DocumentIntelligenceOutput
from tools.extraction_tool import extract_supporting_document_data
from tools.consistency_tool import validate_consistency
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Document Intelligence Agent in an insurance underwriting workflow.

You receive normalized applicant data plus any attached supporting documents
(e.g. a medical examination report, salary proof, or claim history extract),
each represented as a list of {label: value} rows.

You have two tools:
1. extract_supporting_document_data -- call this first with
   attached_documents to get a flattened extracted_data map.
2. validate_consistency -- call this with the applicant's declared
   smoking_status, previous_claims_filed, and annual_income, plus the
   extracted_data from step 1. It returns any mismatches it can detect
   deterministically (smoking status, previous claims, income variance
   over ~15%).

Use the tool's `issues` as your primary basis for the `issues` field, but
also apply your own judgment for anything the tool doesn't cover. If there
are no attached documents, or everything lines up, `consistent` should be
true and `issues` empty.

IMPORTANT: After you finish calling tools, you MUST emit a final assistant
message that contains ONLY the JSON object below (no prose, no markdown).
Do not end the turn after tool calls without that JSON.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "consistent": <bool>,
  "issues": [{"field": <string>, "declared": <string>, "found": <string>}, ...],
  "extracted_data": {<string>: <string>, ...},
  "notes": [<string>, ...]
}
"""

JUDGMENT_INSTRUCTION = """
You are the Document Intelligence Agent in an insurance underwriting workflow.

You receive a JSON payload that already includes `tool_result` from
extract_supporting_document_data + validate_consistency (consistent, issues,
extracted_data). Do NOT call tools. Apply judgment for anything the tools
may have missed; if everything lines up, keep consistent=true and issues=[].

IMPORTANT: Respond with a final message containing ONLY the JSON object below.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "consistent": <bool>,
  "issues": [{"field": <string>, "declared": <string>, "found": <string>}, ...],
  "extracted_data": {<string>: <string>, ...},
  "notes": [<string>, ...]
}
"""


def build_agent(*, with_tools: bool = True) -> LlmAgent:
    return LlmAgent(
        name="DocumentIntelligenceAgent",
        model=get_model(),
        instruction=INSTRUCTION if with_tools else JUDGMENT_INSTRUCTION,
        tools=[extract_supporting_document_data, validate_consistency] if with_tools else [],
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

    try:
        result = DocumentIntelligenceOutput(**result).model_dump()
    except ValidationError:
        pass  # fall through with the raw dict; defaults below still apply

    result.setdefault("issues", [])
    result.setdefault("extracted_data", {})
    result.setdefault("notes", [])
    result["consistent"] = len(result["issues"]) == 0

    return result
