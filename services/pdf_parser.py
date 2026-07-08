"""
Parses a text-based PDF proposal form into the same raw shape produced by
html_parser.py: {"fields": {...}, "missing_labels": [...], "claims_rows": [...],
"attached_documents": {...}}.

Assumes the PDF was generated from the same proposal template (label on one
line, value on the next -- or "Label: Value" on one line), which is the
common case when a proposal form is exported to PDF from the HTML/print flow.
This is a pragmatic MVP parser, not a general-purpose PDF layout engine.
"""

import re
from typing import Dict, Any, List

import pdfplumber

from services.html_parser import _is_missing_marker, _clean  # reuse missing-value rules

KNOWN_LABELS = [
    "Proposal Number", "Application Date", "Insurance Product", "Distribution Channel",
    "Broker / Agent Name", "Broker Licence Code",
    "Full Name", "Date of Birth", "Gender", "Marital Status", "Nationality", "PAN",
    "Residential Address", "Mobile Number", "Email Address",
    "Employer Name", "Designation", "Nature of Work", "Years in Current Employment",
    "Declared Annual Income", "Additional Income Sources", "Existing Insurance Policies",
    "Requested Sum Insured", "Policy Term", "Premium Payment Frequency", "Plan Variant",
    "Nominee Name", "Nominee Relationship",
    "Height", "Weight", "Existing Medical Conditions", "Current Medications",
    "Family Medical History", "Last Medical Checkup Date", "Hospitalization History",
    "Smoking Status", "Alcohol Consumption", "Hazardous Hobbies / Sports",
    "Frequent Travel to High-Risk Regions", "Criminal History / Litigation",
    "Aviation / Hazardous Occupation Exposure",
    "Previous Insurance Claims Filed",
    "Applicant Signature", "Place", "Date",
]

_label_pattern = re.compile(
    r"(" + "|".join(re.escape(lbl) for lbl in KNOWN_LABELS) + r")\s*[:\-]\s*(.*)"
)


def parse_pdf_proposal(path: str) -> Dict[str, Any]:
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

    # Claims / attached-document tables are not reliably recoverable from
    # plain PDF text extraction in this MVP; downstream agents treat their
    # absence as "no structured table found" rather than an error.
    return {
        "fields": fields,
        "missing_labels": missing_labels,
        "claims_rows": [],
        "attached_documents": {},
    }
