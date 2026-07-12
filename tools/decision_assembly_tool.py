"""
DecisionAssemblyTool (ADK tool)

Phase 8 -- Final Decision.

Deterministic assembly of the final decision.json artifact. This tool
never decides an outcome -- it only serializes whatever the controller
accumulated in ctx.state across all 8 phases, into a schema that leads
with the flat, exec-readable fields a CIO/CTO/CUO/CRO would scan first
(status, decision_mode, risk_category, recommendation...), then carries
full audit depth (workflow timing, applicant/document context, a
detailed execution_timeline) as additive keys alongside it -- so the
same file works as both a one-glance decision summary and a complete
audit record.

Writes two copies:
    output/decision_{application_id}.json   -- this case, permanent
    output/decision.json                     -- "most recent run" convenience copy
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools._common import ProgressCallback, emit

TOOL_NAME = "decision_assembly_tool"

WORKFLOW_VERSION = "1.0"

# decision_mode -> decision_maker is a fixed mapping, not a per-call choice,
# so a caller can never accidentally pair e.g. mode="AUTONOMOUS" with
# decision_maker="Senior Underwriter". Callers pass `decision_mode`; this
# tool derives `decision_maker` unless one is explicitly overridden.
_DECISION_MAKER_BY_MODE = {
    "AUTONOMOUS": "AI",
    "HUMAN_REVIEW": "Human Underwriter",
    "SENIOR_UNDERWRITER": "Senior Underwriter",
    "OVERRIDE": "Human Underwriter",
}


def _duration_seconds(started_at: Optional[str], completed_at: Optional[str]) -> Optional[float]:
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        return round((end - start).total_seconds(), 3)
    except ValueError:
        return None


def assemble_final_decision(
    application_id: Optional[str],
    status: str,
    scenario: Optional[str] = None,
    current_phase: Optional[str] = None,
    decision_mode: Optional[str] = None,
    decision_maker: Optional[str] = None,
    risk_category: Optional[str] = None,
    risk_score: Optional[int] = None,
    confidence: Optional[float] = None,
    cat_exposure: Optional[Dict[str, Any]] = None,
    pricing: Optional[Dict[str, Any]] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    decision_evidence: Optional[List[str]] = None,
    audit_trail: Optional[List[str]] = None,
    approval_lineage: Optional[List[Dict[str, str]]] = None,
    governance_history: Optional[List[Dict[str, str]]] = None,
    workflow_metrics: Optional[Dict[str, int]] = None,
    ai_summary: Optional[str] = None,
    email_references: Optional[List[Dict[str, str]]] = None,
    workflow_id: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    applicant: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, str]]] = None,
    execution_timeline: Optional[List[Dict[str, Any]]] = None,
    output_dir: str = "output",
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Assembles the final decision dict and writes it to
    output/decision_{application_id}.json (+ output/decision.json).

    Core (flat, exec-facing) fields:
        application_id, scenario, status, current_phase,
        decision_mode, decision_maker, risk_category, risk_score, confidence,
        cat_exposure, pricing, recommendation, decision_evidence, audit_trail,
        approval_lineage, governance_history, workflow_metrics, ai_summary,
        communication (built here from email_references).

    `recommendation` is expected shaped as:
        {"action": "APPROVE"|"DECLINE"|"ESCALATE"|"OVERRIDE",
         "basis": str, "confidence": float,
         "conditions": [str, ...], "reason": str}

    `email_references` is the list of `draft_email(...)["reference"]` dicts
    produced across the run (each already has email_id/status/reason/
    recipient_role/subject/file) -- wrapped here into the
    {"emails_generated": N, "drafts": [...]} shape decision.json expects.

    Additive audit-depth fields (not in the flat spec, but not
    contradicting it -- extra top-level keys on the same document):
        workflow_id, started_at/completed_at/duration, applicant,
        documents, execution_timeline.

    Returns the assembled decision dict.
    """
    emit(progress_callback, "before", TOOL_NAME, application_id=application_id, status=status)

    if decision_mode and not decision_maker:
        decision_maker = _DECISION_MAKER_BY_MODE.get(decision_mode)

    completed_at = completed_at or datetime.now(timezone.utc).isoformat()

    metrics = dict(workflow_metrics or {})
    metrics.setdefault("agents_executed", 0)
    metrics.setdefault("decision_gates", 10)
    metrics.setdefault("human_reviews", 0)
    metrics.setdefault("governance_checks", 0)

    email_references = email_references or []
    communication = {
        "emails_generated": len(email_references),
        "drafts": email_references,
    }

    decision_out = {
        "application_id": application_id,
        "scenario": scenario,
        "status": status,
        "current_phase": current_phase or "PHASE_8_FINAL_DECISION",

        "decision_mode": decision_mode,
        "decision_maker": decision_maker,

        "risk_category": risk_category,
        "risk_score": risk_score,
        "confidence": confidence,

        "cat_exposure": cat_exposure or {},
        "pricing": pricing or {},
        "recommendation": recommendation or {
            "action": None, "basis": None, "confidence": confidence,
            "conditions": [], "reason": None,
        },

        "decision_evidence": decision_evidence or [],
        "audit_trail": audit_trail or [],
        "approval_lineage": approval_lineage or [],
        "governance_history": governance_history or [],

        "workflow_metrics": metrics,
        "ai_summary": ai_summary,
        "communication": communication,

        # -- additive audit-depth block, same document, extra keys only --
        "workflow": {
            "workflow_id": workflow_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": _duration_seconds(started_at, completed_at),
            "workflow_version": WORKFLOW_VERSION,
        },
        "applicant": applicant or {},
        "documents": documents or [],
        "execution_timeline": execution_timeline or [],
    }

    os.makedirs(output_dir, exist_ok=True)
    safe_id = (application_id or "UNKNOWN").replace("/", "_")

    case_path = os.path.join(output_dir, f"decision_{safe_id}.json")
    latest_path = os.path.join(output_dir, "decision.json")
    for path in (case_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(decision_out, f, indent=2)

    emit(progress_callback, "after", TOOL_NAME, status=status, written_to=case_path)
    return decision_out
