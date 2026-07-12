"""
Document Intelligence Agent (Google ADK LlmAgent)

Phase 2 -- Document Intelligence (OCR + Entity Extraction + Hazard
Detection, cross-document reasoning over Proposal + Electrical Report +
Engineering Report + Loss Runs).

The deterministic keyword-level cross-check already ran in
property_controller.py (tools.hazard_detection_tool +
tools.mismatch_detection_tool) before this agent is called. This agent's
job is judging whether those candidate issues amount to a genuine
disclosure mismatch worth mandatory human review, and adding any softer,
contextual inconsistencies a keyword match wouldn't catch (e.g. a loss
run showing a fire-related claim the proposal's hazard fields don't
reflect at all).
"""

from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent

from schemas.models import DocumentIntelligenceOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the Document Intelligence Agent in a commercial property
underwriting workflow.

You receive:
- the proposal's declared fields (including declared operational hazards),
- a deterministic hazard scan of the proposal itself,
- a deterministic keyword-level cross-check between the proposal's
  declarations and any linked electrical/engineering/loss-run reports,
- the raw text of any linked documents.

Decide whether a genuine disclosure mismatch exists: does the proposal's
declaration meaningfully conflict with what a linked report actually
found? Never clear a mismatch the deterministic cross-check already
flagged -- you may only ADD issues it missed, never remove ones it found.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "disclosure_mismatch": <bool>,
  "issues": [{"field": <string>, "declared": <string>, "document": <string>, "keyword_hits": [<string>, ...]}, ...],
  "extracted_hazards": [{"field": <string>, "value": <string>}, ...],
  "notes": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="DocumentIntelligenceAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=DocumentIntelligenceOutput,
    )


def run(
    applicant_fields: Dict[str, Any],
    hazard_scan: Dict[str, Any],
    mismatch_scan: Dict[str, Any],
    linked_document_labels: List[str],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Args:
        applicant_fields: flat proposal {label: value} dict.
        hazard_scan: tools.hazard_detection_tool.detect_hazards(...) output.
        mismatch_scan: tools.mismatch_detection_tool.detect_mismatches(...) output.
        linked_document_labels: doc types actually linked to this case
            (e.g. ["electrical_report", "loss_runs"]).
        progress_callback: optional before/after event sink.

    Returns:
        {"disclosure_mismatch": bool, "issues": [...], "extracted_hazards": [...], "notes": [...]}
    """
    payload = {
        "applicant_fields": applicant_fields,
        "deterministic_hazard_scan": hazard_scan,
        "deterministic_mismatch_scan": mismatch_scan,
        "linked_documents": linked_document_labels,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    result.setdefault("issues", [])
    result.setdefault("extracted_hazards", hazard_scan.get("hazards_declared", []))
    result.setdefault("notes", [])

    # Belt-and-braces: never let the LLM clear issues the deterministic
    # scan already found.
    deterministic_issues = mismatch_scan.get("issues", [])
    known_fields = {i.get("field") for i in result["issues"]}
    for issue in deterministic_issues:
        if issue.get("field") not in known_fields:
            result["issues"].append(issue)

    result["disclosure_mismatch"] = len(result["issues"]) > 0

    return result
