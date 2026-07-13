"""
CommunicationTool (ADK tool)

Generates -- and ONLY ever generates -- professional email drafts for
every point in the workflow where a real underwriting platform would
normally send mail. This tool never sends anything: no SMTP, no
Outlook/Gmail/Graph/SendGrid API, no network call of any kind. Every
draft is written to disk as a JSON + plaintext pair under
output/emails/ with status permanently fixed to "DRAFT_NOT_SENT".

File layout produced:
    output/emails/email_001.json
    output/emails/email_001.txt
    output/emails/email_002.json
    ...

Callers (agents/nodes) never write email files themselves -- they call
draft_email() with a `trigger` and the case context, and get back both
the full email dict and a short `reference` dict shaped exactly like the
entries decision.json's top-level "communication" list expects.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools._common import ProgressCallback, emit

TOOL_NAME = "communication_tool"

# ---------------------------------------------------------------------------
# Trigger registry: subject template, default recipient role, workflow phase
# ---------------------------------------------------------------------------

_TRIGGER_DEFAULTS = {
    "incomplete_submission": {
        "subject": "Additional Information Required — Proposal {proposal_number}",
        "recipient_role": "Broker",
        "workflow_phase": "PHASE_1_SUBMISSION_INTAKE",
    },
    "disclosure_mismatch": {
        "subject": "Mandatory Review — Disclosure Discrepancy on Proposal {proposal_number}",
        "recipient_role": "Underwriter",
        "workflow_phase": "PHASE_2_DOCUMENT_INTELLIGENCE",
    },
    "escalation_senior_underwriter": {
        "subject": "Escalation for Review — Proposal {proposal_number}",
        "recipient_role": "Senior Underwriter",
        "workflow_phase": "PHASE_7_SENIOR_UNDERWRITER",
    },
    "information_request": {
        "subject": "Further Information Requested — Proposal {proposal_number}",
        "recipient_role": "Broker",
        "workflow_phase": "PHASE_7_SENIOR_UNDERWRITER",
    },
    "conditional_approval": {
        "subject": "Proposal {proposal_number} — Conditional Approval",
        "recipient_role": "Broker",
        "workflow_phase": "PHASE_8_FINAL_DECISION",
    },
    "rejection": {
        "subject": "Proposal {proposal_number} — Underwriting Decision",
        "recipient_role": "Broker",
        "workflow_phase": "PHASE_8_FINAL_DECISION",
    },
    "override_notification": {
        "subject": "Management Visibility — Underwriting Override on Proposal {proposal_number}",
        "recipient_role": "Chief Underwriting Officer",
        "workflow_phase": "PHASE_6_OVERRIDE",
    },
}


def _synth_email(role: str, name: Optional[str], org_hint: Optional[str]) -> str:
    """Best-effort role-based address when no real recipient_email is supplied
    (this is an offline demo -- nothing is ever sent to it)."""
    slug = re.sub(r"[^a-z0-9]+", ".", (name or role).lower()).strip(".")
    domain = re.sub(r"[^a-z0-9]+", "", (org_hint or "underwriting").lower())[:20] or "underwriting"
    return f"{slug}@{domain}.example"


def _build_body(
    trigger: str,
    proposal_number: str,
    insured_name: str,
    broker_name: str,
    reason: str,
    required_action: str,
    deadline: Optional[str],
    context: Dict[str, Any],
    signatory: str,
) -> str:
    lines: List[str] = []

    lines.append(f"Proposal Number: {proposal_number}")
    lines.append(f"Insured: {insured_name}")
    lines.append(f"Broker: {broker_name}")
    lines.append("")

    if trigger == "incomplete_submission":
        lines.append(f"Dear {broker_name},")
        lines.append("")
        lines.append(f"The submission for {insured_name} (Proposal {proposal_number}) cannot proceed to "
                      f"underwriting review until the following mandatory items are provided:")
        for f in context.get("missing_fields", []):
            lines.append(f"  - {f}")

    elif trigger == "disclosure_mismatch":
        lines.append(f"A disclosure discrepancy was identified on Proposal {proposal_number} ({insured_name}) "
                      f"during document intelligence processing and requires mandatory human review before "
                      f"underwriting can continue:")
        for m in context.get("mismatches", []):
            lines.append(f"  - {m.get('field')}: proposal declared '{m.get('declared')}'; "
                          f"{m.get('document', 'a linked report')} indicates otherwise.")

    elif trigger == "escalation_senior_underwriter":
        lines.append(f"Proposal {proposal_number} ({insured_name}) has been escalated for Senior Underwriter "
                      f"review.")
        lines.append(f"Reason: {reason}")

    elif trigger == "information_request":
        lines.append(f"Dear {broker_name},")
        lines.append("")
        lines.append(f"Following review of Proposal {proposal_number} ({insured_name}), the following is "
                      f"required before a final decision can be issued:")
        for item in context.get("requested_items", []):
            lines.append(f"  - {item}")

    elif trigger == "conditional_approval":
        lines.append(f"Dear {broker_name},")
        lines.append("")
        lines.append(f"We are pleased to confirm conditional approval of Proposal {proposal_number} "
                      f"for {insured_name}, subject to the following conditions:")
        for c in context.get("conditions", []):
            lines.append(f"  - {c}")

    elif trigger == "rejection":
        lines.append(f"Dear {broker_name},")
        lines.append("")
        lines.append(f"After underwriting review, Proposal {proposal_number} for {insured_name} has not "
                      f"been approved.")
        lines.append(f"Reason: {reason}")

    elif trigger == "override_notification":
        lines.append(f"An underwriting override was recorded on Proposal {proposal_number} ({insured_name}) "
                      f"and is provided here for management visibility.")
        lines.append(f"Reason: {reason}")

    else:
        lines.append(reason or "Please see the attached case details.")

    if required_action:
        lines.append("")
        lines.append(f"Required Action: {required_action}")
    if deadline:
        lines.append(f"Deadline: {deadline}")

    lines.append("")
    lines.append("Regards,")
    lines.append(signatory)
    return "\n".join(lines)


def _next_email_index(emails_dir: str) -> int:
    if not os.path.isdir(emails_dir):
        return 1
    existing = [f for f in os.listdir(emails_dir) if re.match(r"email_\d+\.json$", f)]
    if not existing:
        return 1
    return max(int(re.search(r"\d+", f).group()) for f in existing) + 1


def draft_email(
    trigger: str,
    proposal_number: str,
    insured_name: str,
    broker_name: str,
    reason: str = "",
    required_action: str = "",
    deadline: Optional[str] = None,
    recipient_role: Optional[str] = None,
    recipient_name: Optional[str] = None,
    recipient_email: Optional[str] = None,
    signatory: str = "Underwriting Team, Commercial Property Division",
    context: Optional[Dict[str, Any]] = None,
    workflow_phase: Optional[str] = None,
    output_dir: str = "output",
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Draft (never send) one professional email for a workflow event, and
    persist it to output/emails/email_NNN.json + .txt.

    Args:
        trigger: one of _TRIGGER_DEFAULTS' keys -- determines the subject
            template, default recipient_role, and workflow_phase unless
            explicitly overridden.
        proposal_number, insured_name, broker_name: case identifiers,
            always included in the body regardless of trigger.
        reason: short reason line (escalation/rejection/override triggers).
        required_action, deadline: optional, appended if provided.
        recipient_role/name/email: who the draft is addressed to. If
            recipient_email is omitted, a placeholder role-based address
            is synthesized (this is an offline demo; nothing is sent).
        context: trigger-specific extra data, e.g.
            {"missing_fields": [...]}            for incomplete_submission
            {"mismatches": [...]}                for disclosure_mismatch
            {"requested_items": [...]}           for information_request
            {"conditions": [...]}                for conditional_approval
        output_dir: base output directory (default "output").
        progress_callback: optional before/after event sink.

    Returns:
        {
          "success": bool,
          "email": {...full email dict, matches the required schema...},
          "reference": {"email_id", "status", "reason", "recipient_role", "file"},
          "json_path": str, "txt_path": str,
        }
    """
    emit(progress_callback, "before", TOOL_NAME, trigger=trigger, proposal_number=proposal_number)

    defaults = _TRIGGER_DEFAULTS.get(trigger, {
        "subject": "Update on Proposal {proposal_number}",
        "recipient_role": "Broker",
        "workflow_phase": "UNKNOWN",
    })
    context = context or {}

    role = recipient_role or defaults["recipient_role"]
    phase = workflow_phase or defaults["workflow_phase"]
    subject = defaults["subject"].format(proposal_number=proposal_number or "UNKNOWN")
    name = recipient_name or (broker_name if role == "Broker" else role)
    email_addr = recipient_email or _synth_email(role, name, broker_name)

    body = _build_body(
        trigger, proposal_number or "UNKNOWN", insured_name or "the applicant",
        broker_name or "the broker", reason, required_action, deadline, context, signatory,
    )

    emails_dir = os.path.join(output_dir, "emails")
    os.makedirs(emails_dir, exist_ok=True)
    idx = _next_email_index(emails_dir)
    email_id = f"email_{idx:03d}"

    email = {
        "email_id": email_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "DRAFT_NOT_SENT",
        "recipient_role": role,
        "recipient_name": name,
        "recipient_email": email_addr,
        "subject": subject,
        "body": body,
        "reason": reason or trigger.replace("_", " ").title(),
        "related_application": proposal_number,
        "workflow_phase": phase,
    }

    json_path = os.path.join(emails_dir, f"{email_id}.json")
    txt_path = os.path.join(emails_dir, f"{email_id}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(email, f, indent=2)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Subject: {subject}\nTo: {name} <{email_addr}> ({role})\n"
                f"Status: DRAFT_NOT_SENT\n\n{body}\n")

    reference = {
        "email_id": email_id,
        "status": "DRAFT_NOT_SENT",
        "reason": email["reason"],
        "recipient_role": role,
        "subject": subject,
        "file": json_path,
    }

    result = {"success": True, "email": email, "reference": reference,
              "json_path": json_path, "txt_path": txt_path}
    emit(progress_callback, "after", TOOL_NAME, email_id=email_id, recipient_role=role)
    return result
