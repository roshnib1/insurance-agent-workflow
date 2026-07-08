"""
Shared data contracts.

Two families of types live here:

1. Plain dataclasses (ApplicantData, FinalDecision, CommunicationDraft) --
   used for deterministic, non-LLM data (parsed/normalized proposal data,
   the final assembled decision). Simple and dict-serializable so the
   Governance SDK can log/replay/diff them without custom serializers.

2. Pydantic BaseModels (the *Output classes) -- used as the `output_schema`
   for each Google ADK LlmAgent. Setting output_schema forces the model to
   return JSON matching the schema, so every agent's response is
   structured and directly parseable, never free-form prose.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


def to_dict(obj) -> Dict[str, Any]:
    """Convert any dataclass in this module to a plain JSON-serializable dict."""
    return asdict(obj)


# ---------------------------------------------------------------------------
# Deterministic data (parsed/normalized proposal + final artifacts)
# ---------------------------------------------------------------------------

@dataclass
class ApplicantData:
    """Common normalized schema. Every parser (HTML/PDF) must map into this."""

    proposal_number: Optional[str] = None
    application_date: Optional[str] = None
    product_type: Optional[str] = None
    broker_name: Optional[str] = None

    applicant_name: Optional[str] = None
    dob: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None

    employer: Optional[str] = None
    occupation: Optional[str] = None
    nature_of_work: Optional[str] = None
    annual_income: Optional[float] = None
    existing_policies: Optional[str] = None

    sum_insured: Optional[float] = None
    policy_term: Optional[str] = None
    premium_frequency: Optional[str] = None
    plan_variant: Optional[str] = None

    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    bmi: Optional[float] = None
    medical_conditions: Optional[str] = None
    medications: Optional[str] = None
    family_medical_history: Optional[str] = None
    last_checkup: Optional[str] = None
    hospitalization_history: Optional[str] = None

    smoking_status: Optional[str] = None
    alcohol_consumption: Optional[str] = None
    hazardous_hobbies: Optional[str] = None
    travel_risk: Optional[str] = None
    criminal_history: Optional[str] = None
    hazardous_occupation: Optional[str] = None

    previous_claims_filed: Optional[str] = None
    claims_details: List[Dict[str, str]] = field(default_factory=list)

    signature: Optional[str] = None
    signature_date: Optional[str] = None

    # Attached supporting documents, if any (used for disclosure-mismatch checks)
    attached_documents: Dict[str, Any] = field(default_factory=dict)

    # Any field the parser could not populate is recorded here as raw label -> None
    raw_missing_labels: List[str] = field(default_factory=list)


@dataclass
class CommunicationDraft:
    """
    Represents a *drafted, unsent* communication. The workflow only ever
    prepares this artifact -- nothing in this codebase sends email/SMS/etc.
    """

    action: str
    trigger: str
    recipient: str
    missing_fields: List[str]
    subject: str
    body: str
    status: str = "DRAFT_NOT_SENT"


@dataclass
class FinalDecision:
    application_id: Optional[str]
    status: str  # COMPLETED / STOPPED_INCOMPLETE / STOPPED_MISMATCH / STOPPED_HUMAN_REVIEW
    risk_category: Optional[str]
    risk_score: Optional[int]
    recommendation: Optional[str]
    premium: Optional[str]
    confidence: Optional[float]
    decision_evidence: List[str]
    audit_trail: List[str]
    communication: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Pydantic output_schema contracts -- one per Google ADK LlmAgent
# ---------------------------------------------------------------------------

class SubmissionIntakeOutput(BaseModel):
    complete: bool = Field(description="True if the submission has everything needed to start underwriting.")
    missing_fields: List[str] = Field(default_factory=list, description="Human-readable labels of missing mandatory fields.")
    confidence: float = Field(description="0.0-1.0 confidence in the completeness assessment.")
    notes: List[str] = Field(default_factory=list, description="Short reasoning notes.")


class DocumentIntelligenceOutput(BaseModel):
    consistent: bool = Field(description="True if the proposal data is consistent with attached supporting documents.")
    issues: List[Dict[str, str]] = Field(default_factory=list, description="Each item: {field, declared, found}.")
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="Any additional structured facts extracted from attached documents.")
    notes: List[str] = Field(default_factory=list)


class RiskAssessmentOutput(BaseModel):
    risk_score: int = Field(description="0-100 overall risk score.")
    risk_category: str = Field(description="LOW, MEDIUM, or HIGH.")
    medical_risk: str = Field(description="LOW, MEDIUM, or HIGH.")
    financial_risk: str = Field(description="LOW, MEDIUM, or HIGH.")
    lifestyle_risk: str = Field(description="LOW, MEDIUM, or HIGH.")
    claims_risk: str = Field(description="LOW, MEDIUM, or HIGH.")
    material_risk: bool = Field(description="True if risk_score >= 45 (material risk threshold).")
    confidence: float = Field(description="0.0-1.0 confidence in this risk assessment.")
    summary: str = Field(description="One or two sentence plain-language risk summary.")
    reasoning: List[str] = Field(default_factory=list, description="Bullet-point evidence for each risk dimension.")


class UnderwritingRecommendationOutput(BaseModel):
    recommendation: str = Field(description="APPROVE, APPROVE_WITH_CONDITIONS, DECLINE, or REFER.")
    premium: str = Field(description="Premium guidance, e.g. loading percentage or rate description.")
    coverage_conditions: List[str] = Field(default_factory=list)
    rationale: List[str] = Field(default_factory=list)
    confidence: float = Field(description="0.0-1.0 confidence in this recommendation.")


class HumanReviewOutput(BaseModel):
    action: str = Field(description="APPROVE, DECLINE, REQUEST_MORE_INFORMATION, or ESCALATE.")
    reason: str = Field(description="Short reason for the action.")
    reviewer_notes: List[str] = Field(default_factory=list)
    requested_items: List[str] = Field(default_factory=list, description="Only if action is REQUEST_MORE_INFORMATION.")
