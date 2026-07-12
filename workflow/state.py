"""
Shared workflow state.

A single mutable object threaded through property_controller.py (mirrored
into ADK's own ctx.state at each node -- see workflow/property_controller.py
for why both exist: ctx.state is ADK's per-run store, this dataclass is
the strongly-typed shape we read/write it as). Every phase reads what it
needs and writes its result back, so there is always one source of truth
for "what has happened so far", independent of which agent or tool
produced a given piece of it.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from schemas.models import CommercialPropertyApplicant


@dataclass
class WorkflowState:
    file_path: str
    workflow_id: str = ""
    started_at: str = ""

    submission: Optional[CommercialPropertyApplicant] = None
    parsed_documents: Dict[str, Any] = field(default_factory=dict)
    linked_documents: List[Dict[str, Any]] = field(default_factory=list)

    hazards: List[Dict[str, str]] = field(default_factory=list)
    disclosure_mismatches: List[Dict[str, Any]] = field(default_factory=list)

    cat_results: Optional[Dict[str, Any]] = None
    risk_summary: Optional[Dict[str, Any]] = None
    pricing: Optional[Dict[str, Any]] = None

    governance_history: List[Dict[str, str]] = field(default_factory=list)
    audit_trail: List[str] = field(default_factory=list)
    approval_lineage: List[Dict[str, str]] = field(default_factory=list)
    decision_history: List[Dict[str, Any]] = field(default_factory=list)
    human_actions: List[Dict[str, Any]] = field(default_factory=list)

    email_references: List[Dict[str, str]] = field(default_factory=list)

    workflow_status: str = "RUNNING"
    current_phase: str = "PHASE_1_SUBMISSION_INTAKE"

    final_decision: Optional[Dict[str, Any]] = None
    evidence_package: Optional[Dict[str, Any]] = None

    agents_executed: int = 0
    human_reviews: int = 0
    governance_checks: int = 0

    def log(self, message: str) -> None:
        self.audit_trail.append(message)

    def record_lineage(self, actor: str, action: str) -> None:
        self.approval_lineage.append({"actor": actor, "action": action})

    def record_governance(self, check: str, trigger: str, result: str) -> None:
        self.governance_history.append({"check": check, "trigger": trigger, "result": result})
        self.governance_checks += 1
