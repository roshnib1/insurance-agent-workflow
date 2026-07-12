"""
CompletenessCheckTool (ADK tool)

Wraps services/normalizer.find_missing_mandatory_fields so the Submission
Intake Agent decides for itself when to run the completeness check,
instead of the orchestrator running it as a Python pre-check outside the
agent (as it currently does inside agents/submission_agent.py's run()).
"""

from typing import Any, Dict

from services.normalizer import find_missing_mandatory_fields, MANDATORY_LABELS
from tools._common import dict_to_applicant, log_tool_io


@log_tool_io
def check_submission_completeness(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check whether a normalized insurance proposal has all mandatory fields.

    Args:
        applicant_data: Normalized applicant data (as produced by
            parse_proposal_document), containing fields like
            proposal_number, applicant_name, dob, annual_income,
            sum_insured, medical_conditions, signature, etc.

    Returns:
        {
          "complete": bool,
          "missing_fields": [<human-readable label>, ...],
          "mandatory_fields": [<all mandatory labels, for reference>, ...]
        }
    """
    try:
        applicant = dict_to_applicant(applicant_data)
        missing = find_missing_mandatory_fields(applicant)
        return {
            "complete": len(missing) == 0,
            "missing_fields": missing,
            "mandatory_fields": list(MANDATORY_LABELS.values()),
        }
    except Exception as exc:
        return {"complete": False, "missing_fields": [], "mandatory_fields": [], "error": str(exc)}
