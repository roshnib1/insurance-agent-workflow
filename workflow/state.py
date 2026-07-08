"""
Shared workflow state.

A single mutable object threaded through the custom workflow controller.
Every stage reads what it needs from it and writes its result back, so the
controller (and, later, the Governance SDK via the hook) always has a
single source of truth for "what has happened so far" -- independent of
which ADK agent produced which piece of it.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from schemas.models import ApplicantData


@dataclass
class UnderwritingState:
    file_path: str

    proposal_data: Optional[ApplicantData] = None

    completeness_result: Optional[Dict[str, Any]] = None
    document_result: Optional[Dict[str, Any]] = None
    risk_result: Optional[Dict[str, Any]] = None
    recommendation: Optional[Dict[str, Any]] = None
    human_review_result: Optional[Dict[str, Any]] = None

    communication: Optional[Dict[str, Any]] = None
    communication_artifact_path: Optional[str] = None

    audit_trail: List[str] = field(default_factory=list)

    final_decision: Optional[Dict[str, Any]] = None

    def log(self, message: str) -> None:
        self.audit_trail.append(message)
