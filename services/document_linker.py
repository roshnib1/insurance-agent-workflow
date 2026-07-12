"""
document_linker.py

The spec requires the controller to "automatically load every linked
document belonging to the selected case" -- proposals and their
electrical/engineering/loss-run reports live side by side as flat files
in data/, not in per-case folders. A linked document is identified purely
by its own "Proposal Reference" field matching the proposal's "Proposal
Number" -- so this module scans every *.html in data/ once and groups
them by that reference.

doc_type is inferred from the filename (electrical_report_*,
engineering_report_*, loss_runs_*) rather than document content, since
that's a stable, deterministic signal already present in every sample
file name.
"""

import glob
import os
from typing import Dict, List

from schemas.models import LinkedDocument
from services.html_parser import load_and_parse_html

_DOC_TYPE_BY_FILENAME_PREFIX = (
    ("proposal_", "proposal"),
    ("electrical_report", "electrical_report"),
    ("engineering_report", "engineering_report"),
    ("loss_runs", "loss_runs"),
)


def _infer_doc_type(filename: str) -> str:
    lowered = filename.lower()
    for prefix, doc_type in _DOC_TYPE_BY_FILENAME_PREFIX:
        if prefix in lowered:
            return doc_type
    return "unknown"


def find_linked_documents(proposal_number: str, data_dir: str = "data") -> List[LinkedDocument]:
    """
    Scans every *.html in data_dir and returns the ones (excluding the
    proposal itself) whose "Proposal Reference" matches proposal_number.

    Returns:
        [LinkedDocument(doc_type=..., file_path=..., proposal_reference=...,
                         raw_html=...), ...]
    """
    if not proposal_number:
        return []

    linked: List[LinkedDocument] = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.html"))):
        filename = os.path.basename(path)
        doc_type = _infer_doc_type(filename)
        if doc_type == "proposal":
            continue  # never link a proposal to itself

        parsed = load_and_parse_html(path)
        if parsed.get("proposal_reference") == proposal_number:
            linked.append(LinkedDocument(
                doc_type=doc_type,
                file_path=path,
                proposal_reference=parsed.get("proposal_reference"),
                raw_html=parsed.get("raw_html", ""),
            ))

    return linked


def linked_documents_as_dict(linked: List[LinkedDocument]) -> Dict[str, str]:
    """Adapts LinkedDocument list into the {doc_label: raw_html} shape
    tools.mismatch_detection_tool.detect_mismatches expects."""
    return {doc.doc_type: doc.raw_html for doc in linked}
