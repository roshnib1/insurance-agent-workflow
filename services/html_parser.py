"""
Parses the enterprise proposal-form HTML layout (8 fixed sections, each
built from repeated `<div class="field">` blocks with a `.label` and
`.value`) into a raw dict of label -> value, plus any "attached supporting
documents" tables (used later for disclosure-mismatch detection).

This is intentionally coupled to the known form layout used across the
four demo proposal forms -- it is not a generic HTML scraper.
"""

from bs4 import BeautifulSoup
from typing import Dict, Any, List

MISSING_MARKERS = (
    "left blank",
    "not signed",
    "not provided",
    "not applicable",
)


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_missing_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in MISSING_MARKERS)


def parse_html_proposal(html_content: str) -> Dict[str, Any]:
    """
    Returns:
        {
            "fields": {label: value_or_None, ...},
            "missing_labels": [label, ...],
            "attached_documents": {table_title: [{col_label: col_value}, ...]},
        }
    """
    soup = BeautifulSoup(html_content, "html.parser")

    fields: Dict[str, Any] = {}
    missing_labels: List[str] = []

    for field_div in soup.select("div.field"):
        label_el = field_div.select_one(".label")
        value_el = field_div.select_one(".value")
        if not label_el or not value_el:
            continue

        label = _clean(label_el.get_text())
        value = _clean(value_el.get_text())

        if not value or _is_missing_marker(value):
            fields[label] = None
            missing_labels.append(label)
        else:
            fields[label] = value

    # Previous claims table (section 7)
    claims_rows: List[Dict[str, str]] = []
    claims_table = soup.select_one("table.claims")
    if claims_table and not soup.select_one(".attach-note table.claims") is claims_table:
        headers = [_clean(th.get_text()) for th in claims_table.select("thead th")]
        for row in claims_table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) == len(headers) and headers:
                claims_rows.append(
                    {headers[i]: _clean(cells[i].get_text()) for i in range(len(headers))}
                )

    # Attached supporting documents block (section only present on mismatch forms)
    attached_documents: Dict[str, List[Dict[str, str]]] = {}
    attach_note = soup.select_one("div.attach-note")
    if attach_note:
        for table in attach_note.select("table.claims"):
            title_el = table.select_one("thead th")
            title = _clean(title_el.get_text()) if title_el else "Attached Document"
            rows = []
            for row in table.select("tbody tr"):
                cells = row.select("td")
                if len(cells) == 2:
                    rows.append({_clean(cells[0].get_text()): _clean(cells[1].get_text())})
            attached_documents[title] = rows

    return {
        "fields": fields,
        "missing_labels": missing_labels,
        "claims_rows": claims_rows,
        "attached_documents": attached_documents,
    }


def load_and_parse_html(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return parse_html_proposal(content)
