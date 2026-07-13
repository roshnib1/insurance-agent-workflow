"""
Document Intelligence Agent (Google ADK LlmAgent)

Phase 2 -- Document Intelligence (OCR + Entity Extraction + Hazard
Detection, cross-document reasoning over Proposal + Electrical Report +
Engineering Report + Loss Runs).

Now calls tools.detect_hazards and tools.detect_mismatches itself via
real LLM-directed function calling, rather than receiving precomputed
results from the controller. Both tools are bound via closure to this
call's applicant fields + linked document HTML, so the model just
decides which to call -- it never has to reproduce a large fields/HTML
blob as a tool-call argument.

Has `tools=[...]`, so no `output_schema` (ADK constraint) -- final answer
is free-form JSON text, parsed manually in run() below.
"""

from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent

from tools.hazard_detection_tool import detect_hazards
from tools.mismatch_detection_tool import detect_mismatches
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Document Intelligence Agent in a commercial property
underwriting workflow.

You have two tools:
- `scan_declared_hazards` -- deterministic scan of the proposal's own
  declared hazard fields.
- `cross_check_disclosure_mismatch` -- deterministic keyword-level cross
  check between the proposal's declarations and any linked
  electrical/engineering/loss-run reports.

Call both. Then decide whether a genuine disclosure mismatch exists: does
the proposal's declaration meaningfully conflict with what a linked
report actually found? Never clear a mismatch the cross-check tool
already flagged -- you may only ADD issues it missed, never remove ones
it found. Also add any softer, contextual inconsistencies the tools
wouldn't catch (e.g. a loss run showing a fire-related claim the
proposal's hazard fields don't reflect at all).

After calling the tools, your ENTIRE response must be the JSON object below and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result, or commentary before or after it -- not even one sentence. Do NOT use markdown code fences. The very first character you output must be '{' and the very last character must be '}'. This exact shape:
{
  "disclosure_mismatch": <bool>,
  "issues": [{"field": <string>, "declared": <string>, "document": <string>, "keyword_hits": [<string>, ...]}, ...],
  "extracted_hazards": [{"field": <string>, "value": <string>}, ...],
  "notes": [<string>, ...]
}
"""


def build_agent(
    applicant_fields: Dict[str, Any],
    linked_documents_html: Dict[str, str],
    progress_callback: Optional[Any] = None,
) -> LlmAgent:
    def scan_declared_hazards() -> Dict[str, Any]:
        """Scans the proposal's declared hazard fields for anything present."""
        return detect_hazards(applicant_fields, progress_callback=progress_callback)

    def cross_check_disclosure_mismatch() -> Dict[str, Any]:
        """Cross-checks the proposal's hazard declarations against linked electrical/engineering/loss-run reports."""
        return detect_mismatches(applicant_fields, linked_documents_html, progress_callback=progress_callback)

    return LlmAgent(
        name="DocumentIntelligenceAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[scan_declared_hazards, cross_check_disclosure_mismatch],
    )


def run(
    applicant_fields: Dict[str, Any],
    linked_documents_html: Dict[str, str],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"disclosure_mismatch": bool, "issues": [...], "extracted_hazards": [...], "notes": [...]}
    """
    agent = build_agent(applicant_fields, linked_documents_html, progress_callback=progress_callback)
    payload = {"applicant_fields": applicant_fields, "linked_documents": list(linked_documents_html.keys())}
    result = call_agent(agent, payload, progress_callback=progress_callback)

    result.setdefault("issues", [])
    result.setdefault("extracted_hazards", [])
    result.setdefault("notes", [])

    # Belt-and-braces: re-run the deterministic cross-check ourselves and
    # never let the agent's answer clear issues it already found.
    deterministic_mismatches = detect_mismatches(applicant_fields, linked_documents_html)
    known_fields = {i.get("field") for i in result["issues"]}
    for issue in deterministic_mismatches.get("issues", []):
        if issue.get("field") not in known_fields:
            result["issues"].append(issue)

    if not result["extracted_hazards"]:
        result["extracted_hazards"] = detect_hazards(applicant_fields).get("hazards_declared", [])

    result["disclosure_mismatch"] = len(result["issues"]) > 0

    return result
