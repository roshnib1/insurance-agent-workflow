"""
DraftCommunicationTool (ADK tool)

Wraps all three draft functions in services/communication_service.py
behind one tool that selects the right template by trigger type, so the
Human Review Agent can call one tool instead of the orchestrator picking
the function directly (as controller.py currently does).

Drafts only -- nothing here sends an email/SMS/webhook, exactly as in the
underlying service module.
"""

from typing import Any, Dict, List, Optional

from schemas.models import to_dict
from services.communication_service import (
    draft_missing_information_email,
    draft_disclosure_mismatch_email,
    draft_human_review_information_request,
)
from tools._common import log_tool_io

VALID_TRIGGERS = ("incomplete_submission", "disclosure_mismatch", "human_review")


@log_tool_io
def draft_communication(
    trigger: str,
    proposal_number: Optional[str] = None,
    broker_name: Optional[str] = None,
    applicant_name: Optional[str] = None,
    missing_fields: Optional[List[str]] = None,
    mismatches: Optional[List[Dict[str, str]]] = None,
    requested_items: Optional[List[str]] = None,
    review_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Draft an (unsent) communication for the given trigger.

    Args:
        trigger: One of "incomplete_submission", "disclosure_mismatch", "human_review".
        proposal_number, broker_name, applicant_name: Applicant identifiers.
        missing_fields: Required when trigger == "incomplete_submission".
        mismatches: Required when trigger == "disclosure_mismatch"
            (list of {"field", "declared", "found"}).
        requested_items: Required when trigger == "human_review".
        review_reason: Required when trigger == "human_review".

    Returns:
        On success: {"success": True, "communication": {<CommunicationDraft fields>}}
        On failure: {"success": False, "error": "<message>"}
    """
    try:
        if trigger == "incomplete_submission":
            draft = draft_missing_information_email(
                proposal_number=proposal_number,
                broker_name=broker_name,
                applicant_name=applicant_name,
                missing_fields=missing_fields or [],
            )
        elif trigger == "disclosure_mismatch":
            draft = draft_disclosure_mismatch_email(
                proposal_number=proposal_number,
                broker_name=broker_name,
                applicant_name=applicant_name,
                mismatches=mismatches or [],
            )
        elif trigger == "human_review":
            draft = draft_human_review_information_request(
                proposal_number=proposal_number,
                broker_name=broker_name,
                applicant_name=applicant_name,
                requested_items=requested_items or [],
                review_reason=review_reason or "",
            )
        else:
            return {"success": False, "error": f"Unknown trigger '{trigger}'. Must be one of {VALID_TRIGGERS}."}

        return {"success": True, "communication": to_dict(draft)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
