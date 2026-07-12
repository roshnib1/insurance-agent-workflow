"""
DocumentParserTool (ADK tool)

Wraps the existing deterministic parsers (services/html_parser.py,
services/pdf_parser.py) plus services/normalizer.py so the Submission
Intake Agent can call parsing as a tool, instead of the orchestrator
parsing the file in plain Python before any agent is invoked.

Reuses 100% of the existing parsing/normalization code -- this file adds
no new parsing logic, only an ADK-callable wrapper with typed
input/output and error handling.
"""

import os
from dataclasses import asdict
from typing import Any, Dict

from services.html_parser import load_and_parse_html
from services.pdf_parser import parse_pdf_proposal
from services.normalizer import normalize
from tools._common import log_tool_io


@log_tool_io
def parse_proposal_document(file_path: str) -> Dict[str, Any]:
    """
    Parse a PDF or HTML insurance proposal file into normalized applicant data.

    Args:
        file_path: Path to the proposal file (.html, .htm, or .pdf).

    Returns:
        On success: {"success": True, "applicant_data": {<normalized ApplicantData fields>}}
        On failure: {"success": False, "error": "<message>"}
    """
    try:
        extension = os.path.splitext(file_path)[1].lower()
        if extension in (".html", ".htm"):
            raw = load_and_parse_html(file_path)
        elif extension == ".pdf":
            raw = parse_pdf_proposal(file_path)
        else:
            return {"success": False, "error": f"Unsupported proposal format: {extension}"}

        applicant = normalize(raw)
        return {"success": True, "applicant_data": asdict(applicant)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
