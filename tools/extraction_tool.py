"""
DataExtractionTool (ADK tool)

New tool. Previously "extraction" from attached supporting documents was
only described in prose inside document_agent.py's instruction -- never a
real function. This flattens the attached_documents structure produced by
services/html_parser.py (a dict of document title -> list of
{label: value} rows) into a single flat dict, so the Document
Intelligence Agent has structured data to hand to ConsistencyValidationTool
instead of reasoning over nested tables itself.
"""

from typing import Any, Dict

from tools._common import log_tool_io


@log_tool_io
def extract_supporting_document_data(attached_documents: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten attached supporting document tables into a single structured dict.

    Args:
        attached_documents: Dict of {document_title: [{label: value}, ...]},
            as produced by the html/pdf parsers (e.g. medical examination
            report, salary proof, claim history extract).

    Returns:
        {
          "success": True,
          "extracted_data": {"<document title> - <label>": "<value>", ...},
          "document_titles": [<title>, ...]
        }
    """
    try:
        extracted: Dict[str, str] = {}
        for title, rows in (attached_documents or {}).items():
            for row in rows or []:
                for label, value in row.items():
                    extracted[f"{title} - {label}"] = value

        return {
            "success": True,
            "extracted_data": extracted,
            "document_titles": list((attached_documents or {}).keys()),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "extracted_data": {}, "document_titles": []}
