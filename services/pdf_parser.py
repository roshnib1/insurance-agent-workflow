"""
Parses a text-based PDF proposal form into the same raw shape produced by
html_parser.py: {"fields": {...}, "missing_labels": [...], "proposal_reference": ...}.

Assumes "Label: Value" (or label on one line, value on the next) layout,
matching what a proposal template commonly produces when exported to PDF.
Pragmatic MVP parser, not a general-purpose PDF layout engine.
"""

import re
from typing import Any, Dict, List

import pdfplumber

from services.html_parser import _clean, _is_missing_marker  # reuse missing-value rules

KNOWN_LABELS = [
    "Proposal Number", "Proposal Reference", "Application Date", "Underwriting Office",
    "Broker Name", "Business Name", "Contact Person", "Email", "Phone",
    "GST Number", "PAN Number", "Registered Address",
    "Primary Property Address", "Building Type", "Construction Material",
    "Occupancy Type", "Year Built", "Number of Floors", "Total Floor Area",
    "Total Insured Value (TIV)", "Requested Sum Insured", "Deductible",
    "Previous Claims Count",
    "Flood Zone", "Earthquake Zone", "Cyclone Zone", "Wildfire Zone",
    "Sprinkler System", "Fire Protection System", "Smoke Detection",
    "CCTV Installed", "Security Guards", "Safety Audit Completed",
    "Electrical Hazards", "Chemical Storage", "Flammable Materials",
    "Explosive Materials", "High Temperature Equipment", "Heavy Machinery",
    "Hazardous Processes", "Warehouse Storage", "CAT Vendor",
]

_label_pattern = re.compile(
    r"(" + "|".join(re.escape(lbl) for lbl in KNOWN_LABELS) + r")\s*[:\-]\s*(.*)"
)


def parse_pdf_document(path: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    missing_labels: List[str] = []

    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    for raw_line in full_text.splitlines():
        line = _clean(raw_line)
        if not line:
            continue
        match = _label_pattern.match(line)
        if not match:
            continue
        label, value = match.group(1), _clean(match.group(2))

        if not value or _is_missing_marker(value):
            fields[label] = None
            missing_labels.append(label)
        else:
            fields[label] = value

    proposal_reference = fields.get("Proposal Number") or fields.get("Proposal Reference")

    return {
        "fields": fields,
        "missing_labels": missing_labels,
        "proposal_reference": proposal_reference,
        "document_title": None,
        "raw_html": "",
    }
