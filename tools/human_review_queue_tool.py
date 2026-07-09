"""
HumanReviewQueueTool (ADK tool, MOCKED)

Represents handing a case to a human-review queue, so the Human Review
Agent's simulated judgment is routed through a tool call instead of just
being another inline LLM response with no queue concept at all. Real
queue infrastructure (a ticketing system, a task queue, a pause/resume
mechanism) doesn't exist yet -- this is a stub that generates a ticket id
and returns a queued acknowledgment, deliberately kept simple so it can
be swapped for a real integration later without changing the agent or
orchestrator code that calls it.
"""

import uuid
from typing import Any, Dict, Optional


def enqueue_for_human_review(
    application_id: Optional[str],
    trigger: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    (Mocked) Enqueue a case for human underwriter review.

    Args:
        application_id: The proposal/application identifier.
        trigger: Why the case is being queued -- one of
            "disclosure_mismatch", "material_risk", "low_confidence".
        reason: Optional additional context for the reviewer.

    Returns:
        {"queued": True, "queue_ticket_id": "<id>", "application_id": str,
         "trigger": str, "reason": str | None, "status": "PENDING_HUMAN_REVIEW"}
    """
    ticket_id = f"HR-{uuid.uuid4().hex[:8].upper()}"
    return {
        "queued": True,
        "queue_ticket_id": ticket_id,
        "application_id": application_id,
        "trigger": trigger,
        "reason": reason,
        "status": "PENDING_HUMAN_REVIEW",
    }
