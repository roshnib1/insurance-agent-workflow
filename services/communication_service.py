"""
Generates DRAFT communications only.

Nothing in this module (or anywhere in this codebase) sends an email, SMS,
or webhook. It only prepares a CommunicationDraft object, which the
orchestrator persists as an output artifact (output/email_draft_<id>.json)
and embeds in the final decision JSON for human/SDK review before any real
send action is taken by a separate, human-operated system.
"""

from typing import List, Dict, Any, Optional

from schemas.models import CommunicationDraft


def draft_missing_information_email(
    proposal_number: Optional[str],
    broker_name: Optional[str],
    applicant_name: Optional[str],
    missing_fields: List[str],
) -> CommunicationDraft:
    recipient_name = broker_name or applicant_name or "Broker/Applicant"
    field_list = "\n".join(f"  - {field}" for field in missing_fields)

    subject = f"Additional Information Required for Insurance Proposal {proposal_number or ''}".strip()
    body = (
        f"Dear {recipient_name},\n\n"
        f"Thank you for submitting proposal {proposal_number or '[Proposal Number]'} "
        f"for {applicant_name or 'the applicant'}.\n\n"
        f"Our underwriting review process has identified that the following mandatory "
        f"information is missing or incomplete:\n\n"
        f"{field_list}\n\n"
        f"Kindly provide the above details at your earliest convenience so we can continue "
        f"the underwriting assessment. The proposal will remain on hold until this "
        f"information is received.\n\n"
        f"Regards,\nUnderwriting Operations Team\nSuryodaya Life & General Insurance Co. Ltd."
    )

    return CommunicationDraft(
        action="REQUEST_MORE_INFORMATION",
        trigger="incomplete_submission",
        recipient="Broker" if broker_name else "Applicant",
        missing_fields=missing_fields,
        subject=subject,
        body=body,
    )


def draft_disclosure_mismatch_email(
    proposal_number: Optional[str],
    broker_name: Optional[str],
    applicant_name: Optional[str],
    mismatches: List[Dict[str, str]],
) -> CommunicationDraft:
    recipient_name = broker_name or applicant_name or "Broker/Applicant"
    mismatch_list = "\n".join(
        f"  - {m.get('field', 'Field')}: declared as \"{m.get('declared', 'N/A')}\", "
        f"but supporting documents indicate \"{m.get('found', 'N/A')}\""
        for m in mismatches
    )

    subject = f"Clarification Required — Discrepancy in Proposal {proposal_number or ''}".strip()
    body = (
        f"Dear {recipient_name},\n\n"
        f"During document review of proposal {proposal_number or '[Proposal Number]'} "
        f"for {applicant_name or 'the applicant'}, our verification process identified the "
        f"following discrepancies between the proposal form and the supporting documents "
        f"submitted:\n\n"
        f"{mismatch_list}\n\n"
        f"Please confirm the accurate information or provide clarifying documentation so we "
        f"can proceed with the underwriting assessment. The proposal has been placed on hold "
        f"pending this clarification.\n\n"
        f"Regards,\nUnderwriting Operations Team\nSuryodaya Life & General Insurance Co. Ltd."
    )

    return CommunicationDraft(
        action="REQUEST_MORE_INFORMATION",
        trigger="disclosure_mismatch",
        recipient="Broker" if broker_name else "Applicant",
        missing_fields=[m.get("field", "Unknown field") for m in mismatches],
        subject=subject,
        body=body,
    )


def draft_human_review_information_request(
    proposal_number: Optional[str],
    broker_name: Optional[str],
    applicant_name: Optional[str],
    requested_items: List[str],
    review_reason: str,
) -> CommunicationDraft:
    recipient_name = broker_name or applicant_name or "Broker/Applicant"
    item_list = "\n".join(f"  - {item}" for item in requested_items)

    subject = f"Underwriting Review — Additional Documentation Needed for Proposal {proposal_number or ''}".strip()
    body = (
        f"Dear {recipient_name},\n\n"
        f"Proposal {proposal_number or '[Proposal Number]'} for {applicant_name or 'the applicant'} "
        f"is currently under underwriting review. Reason for review: {review_reason.rstrip('.')}.\n\n"
        f"To help our underwriting team complete the assessment, please provide the following:\n\n"
        f"{item_list}\n\n"
        f"We appreciate your prompt response so we can proceed with a decision.\n\n"
        f"Regards,\nUnderwriting Operations Team\nSuryodaya Life & General Insurance Co. Ltd."
    )

    return CommunicationDraft(
        action="REQUEST_MORE_INFORMATION",
        trigger="human_review",
        recipient="Broker" if broker_name else "Applicant",
        missing_fields=requested_items,
        subject=subject,
        body=body,
    )
