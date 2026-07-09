"""
DecisionEvidenceTool (ADK tool)

Wraps the FinalDecision assembly logic that currently lives inline in
workflow/controller.py's _finalize(), so assembling the final decision
object is callable and testable independently of the orchestrator, and
reusable from workflow/adk_controller.py later without duplicating the
dataclass-construction code.
"""

from typing import Any, Dict, List, Optional

from schemas.models import FinalDecision, to_dict


def assemble_final_decision(
    application_id: Optional[str],
    status: str,
    audit_trail: List[str],
    risk_category: Optional[str] = None,
    risk_score: Optional[int] = None,
    recommendation: Optional[str] = None,
    premium: Optional[str] = None,
    confidence: Optional[float] = None,
    decision_evidence: Optional[List[str]] = None,
    communication: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Assemble the final underwriting decision object.

    Args:
        application_id: The proposal/application identifier.
        status: One of COMPLETED, STOPPED_INCOMPLETE, STOPPED_MISMATCH,
            STOPPED_HUMAN_REVIEW.
        audit_trail: Ordered list of log messages describing what happened
            during this run.
        risk_category, risk_score: From the Risk Assessment Agent, if reached.
        recommendation: Final recommendation or human-review action.
        premium: Premium guidance, if reached.
        confidence: Recommendation confidence, if reached.
        decision_evidence: Bullet-point evidence supporting the decision.
        communication: Drafted communication object, if one was prepared
            (as returned by draft_communication).

    Returns:
        The final decision as a plain dict, matching schemas.models.FinalDecision.
    """
    decision = FinalDecision(
        application_id=application_id,
        status=status,
        risk_category=risk_category,
        risk_score=risk_score,
        recommendation=recommendation,
        premium=premium,
        confidence=confidence,
        decision_evidence=decision_evidence or [],
        audit_trail=audit_trail or [],
        communication=communication,
    )
    return to_dict(decision)
