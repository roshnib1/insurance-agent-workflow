"""
MismatchDetectionTool (ADK tool)

Phase 2 -- Document Intelligence.

Compares what the proposal *declares* (e.g. "Electrical Hazards: None
Reported") against the narrative findings of any linked electrical
report, engineering report, or loss-run statement for the same
proposal number, and flags keyword-level contradictions.

This is a deterministic, keyword-level pre-check -- it gives
DocumentIntelligenceAgent a concrete list of candidate contradictions to
reason over, it does not itself decide "mismatch: true/false" for the
workflow (that judgment, plus any softer/contextual mismatches, is the
LLM's job).

A linked document is any data/*.html file whose "Proposal Reference"
(or equivalent identifying field) matches the proposal's own
"Proposal Number". Finding + loading those files is
services/document_linker.py's job (a later module); this tool takes
already-loaded document text and just does the comparison.
"""

import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from tools._common import HAZARD_FIELDS, ProgressCallback, emit, is_negative_or_none

TOOL_NAME = "mismatch_detection_tool"

# Narrative-language hazard signals that commonly show up in inspection
# report findings/remarks sections, independent of the report's own
# field labels (which vary between electrical / engineering / loss-run
# report layouts).
HAZARD_KEYWORDS = (
    "exposed wiring", "frayed wiring", "frayed", "exposed", "overloaded",
    "overheating", "thermal discolouration", "thermal discoloration",
    "insulation cracking", "circuit breaker bypass", "bypassing",
    "exceeds recommended threshold", "non-compliant", "code violation",
    "fire hazard", "unsafe", "hazardous condition", "deficient",
    "corrosion", "leak", "structural crack", "inadequate",
)

# Which proposal hazard field(s) a given linked-document type is actually
# relevant to. Without this, a hit anywhere in an electrical report's text
# would get cross-checked against every unrelated declared-negative hazard
# field (Chemical Storage, Explosive Materials, ...), producing false
# positives. Matched by substring against the doc_label the caller passes in.
_DOC_LABEL_TO_RELEVANT_FIELDS = {
    "electrical": ("Electrical Hazards",),
    "engineering": ("Heavy Machinery", "Hazardous Processes", "High Temperature Equipment"),
    "loss_run": (),  # loss runs inform claims history, not a HAZARD_FIELDS mismatch
}


def _relevant_fields_for(doc_label: str) -> tuple:
    lowered = doc_label.lower()
    for key, relevant_fields in _DOC_LABEL_TO_RELEVANT_FIELDS.items():
        if key in lowered:
            return relevant_fields
    return HAZARD_FIELDS  # unknown doc type: fall back to checking all of them


def _extract_document_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    body = soup.select_one(".section-body") or soup
    return " ".join(soup.get_text(" ", strip=True).split())


def _find_keyword_hits(text: str) -> List[str]:
    lowered = text.lower()
    return sorted({kw for kw in HAZARD_KEYWORDS if kw in lowered})


def detect_mismatches(
    proposal_fields: Dict[str, Any],
    linked_documents: Dict[str, str],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Args:
        proposal_fields: flat {label: value} dict for the proposal itself.
        linked_documents: {doc_label: raw_html_content} for every document
            linked to this proposal (e.g. {"electrical_report": "<html>...",
            "engineering_report": "<html>...", "loss_runs": "<html>..."}).
        progress_callback: optional before/after event sink.

    Returns:
        {
          "issues": [
            {"field": str, "declared": str, "document": str, "keyword_hits": [str, ...]},
            ...
          ],
          "issue_count": int,
          "has_mismatch": bool,
        }
    """
    emit(
        progress_callback, "before", TOOL_NAME,
        linked_document_count=len(linked_documents),
    )

    issues: List[Dict[str, Any]] = []

    for doc_label, html_content in linked_documents.items():
        doc_text = _extract_document_text(html_content)
        hits = _find_keyword_hits(doc_text)
        if not hits:
            continue

        # Only a mismatch if the proposal declared the corresponding
        # hazard field as clear/absent while the linked document's
        # narrative contains hazard language.
        for label in _relevant_fields_for(doc_label):
            declared = proposal_fields.get(label)
            if declared is not None and is_negative_or_none(declared):
                issues.append({
                    "field": label,
                    "declared": declared,
                    "document": doc_label,
                    "keyword_hits": hits,
                })

    result = {
        "issues": issues,
        "issue_count": len(issues),
        "has_mismatch": len(issues) > 0,
    }

    emit(progress_callback, "after", TOOL_NAME, issue_count=result["issue_count"])
    return result
