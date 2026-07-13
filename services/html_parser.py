"""
Parses the enterprise commercial-property proposal-form HTML layout
(repeated `.section` blocks, each built from `<div class="field">` with a
`.lbl` and `.val`) into a flat dict of label -> value, plus the document's
own "Proposal Reference" (present on linked electrical/engineering/loss-run
reports, used by document_linker.py to associate a report with a proposal).

Intentionally coupled to the known form layout used across data/*.html --
not a generic HTML scraper.
"""

from typing import Any, Dict, List

from bs4 import BeautifulSoup

MISSING_MARKERS = ("left blank", "not signed", "not provided", "not applicable", "n/a")


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_missing_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in MISSING_MARKERS)


def parse_html_document(html_content: str) -> Dict[str, Any]:
    """
    Returns:
        {
          "fields": {label: value_or_None, ...},
          "missing_labels": [label, ...],
          "proposal_reference": str | None,   # "Proposal Number" (on a
              # proposal itself) or "Proposal Reference" (on a linked
              # report) -- whichever is present.
          "document_title": str | None,       # e.g. "Electrical Safety
              # Inspection Report" -- used to classify doc_type.
        }
    """
    soup = BeautifulSoup(html_content, "html.parser")

    fields: Dict[str, Any] = {}
    missing_labels: List[str] = []

    for field_div in soup.select("div.field"):
        label_el = field_div.select_one(".lbl")
        value_el = field_div.select_one(".val")
        if not label_el or not value_el:
            continue

        label = _clean(label_el.get_text())
        value = _clean(value_el.get_text())

        if not value or _is_missing_marker(value):
            fields[label] = None
            missing_labels.append(label)
        else:
            fields[label] = value

    proposal_reference = fields.get("Proposal Number") or fields.get("Proposal Reference")

    title_el = soup.select_one(".doc-title") or soup.select_one("title")
    document_title = _clean(title_el.get_text()) if title_el else None

    return {
        "fields": fields,
        "missing_labels": missing_labels,
        "proposal_reference": proposal_reference,
        "document_title": document_title,
    }


def load_and_parse_html(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    result = parse_html_document(content)
    result["raw_html"] = content
    return result
