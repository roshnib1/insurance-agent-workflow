"""
ParseSubmissionTool (ADK tool)

Phase 1 -- Submission Intake.

Parses the enterprise proposal-form HTML layout (9 fixed `.section`
blocks, each built from repeated `<div class="field"><span class="lbl">
.../<span class="val">...` pairs) into a flat label -> value dict, and
separately checks which of the mandatory fields (see
tools/_common.py::MANDATORY_LABELS) are present.

Self-contained for now: once services/html_parser.py + normalizer.py
land, SubmissionIntakeAgent will call those directly for the raw parse
and use this tool only for the completeness judgment. Until then, this
tool does both so it's independently testable against data/*.html today.
"""

from typing import Any, Dict, Optional

from bs4 import BeautifulSoup

from tools._common import MANDATORY_LABELS, ProgressCallback, emit

TOOL_NAME = "parse_submission_tool"


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _parse_fields(html_content: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    fields: Dict[str, Optional[str]] = {}
    for field_div in soup.select("div.field"):
        label_el = field_div.select_one(".lbl")
        value_el = field_div.select_one(".val")
        if not label_el or not value_el:
            continue
        label = _clean(label_el.get_text())
        value = _clean(value_el.get_text())
        fields[label] = value or None
    return fields


def parse_submission(
    file_path: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Parse a proposal HTML file and check mandatory-field completeness.

    Args:
        file_path: path to a proposal_*.html file in data/.
        progress_callback: optional before/after event sink.

    Returns:
        {
          "success": bool,
          "fields": {label: value_or_None, ...},
          "complete": bool,
          "missing_fields": [<mandatory label>, ...],
          "proposal_number": str | None,
          "error": str  (only if success is False)
        }
    """
    emit(progress_callback, "before", TOOL_NAME, file_path=file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except OSError as exc:
        result = {"success": False, "error": f"Could not read {file_path}: {exc}"}
        emit(progress_callback, "failed", TOOL_NAME, error=result["error"])
        return result

    fields = _parse_fields(html_content)

    missing = []
    for internal_key, label in MANDATORY_LABELS.items():
        if not fields.get(label):
            missing.append(label)

    result = {
        "success": True,
        "fields": fields,
        "complete": len(missing) == 0,
        "missing_fields": missing,
        "proposal_number": fields.get("Proposal Number"),
    }

    emit(
        progress_callback, "after", TOOL_NAME,
        complete=result["complete"],
        missing_count=len(missing),
        proposal_number=result["proposal_number"],
    )
    return result


def check_completeness(
    fields: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Fields-only variant of the mandatory-field completeness check, for use
    as an LlmAgent tool: unlike parse_submission() above, this takes
    already-parsed fields directly (no file I/O), since the calling agent
    already has them in its own context.

    Args:
        fields: flat {label: value} dict, e.g. as produced by parse_submission.
        progress_callback: optional before/after event sink.

    Returns:
        {"complete": bool, "missing_fields": [<mandatory label>, ...]}
    """
    emit(progress_callback, "before", "check_completeness", field_count=len(fields))

    missing = [label for _, label in MANDATORY_LABELS.items() if not fields.get(label)]
    result = {"complete": len(missing) == 0, "missing_fields": missing}

    emit(progress_callback, "after", "check_completeness", complete=result["complete"], missing_count=len(missing))
    return result
