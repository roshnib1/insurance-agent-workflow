"""
Shared data contracts.

Two families of types live here (same convention as the reference project):

1. Plain dataclasses (CommercialPropertyApplicant, LinkedDocument,
   FinalDecision) -- deterministic, non-LLM data: parsed/normalized
   proposal data and final assembled artifacts. Simple and
   dict-serializable so any downstream consumer can log/replay/diff them
   without custom serializers.

2. Pydantic BaseModels (the *Output classes) -- one per Google ADK
   LlmAgent, used as `output_schema` so each agent's response is
   structured JSON, never free-form prose. NOTE: per ADK's own
   constraint, `output_schema` and `tools=[...]` cannot both be set on
   the same LlmAgent -- agents that call a tool validate/coerce their
   raw JSON against these classes in code instead (see agents/*.py),
   exactly like the reference project's submission_agent.py does.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def to_dict(obj) -> Dict[str, Any]:
    """Convert any dataclass in this module to a plain JSON-serializable dict."""
    return asdict(obj)


# ---------------------------------------------------------------------------
# Deterministic data (parsed/normalized proposal + final artifacts)
# ---------------------------------------------------------------------------

@dataclass
class CommercialPropertyApplicant:
    """Common normalized schema. Every parser (HTML/PDF) must map into this."""

    # Identification
    proposal_number: Optional[str] = None
    application_date: Optional[str] = None
    underwriting_office: Optional[str] = None
    broker_name: Optional[str] = None
    business_name: Optional[str] = None
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    registered_address: Optional[str] = None

    # Property
    primary_property_address: Optional[str] = None
    building_type: Optional[str] = None
    construction_material: Optional[str] = None
    occupancy_type: Optional[str] = None
    year_built: Optional[str] = None
    number_of_floors: Optional[str] = None
    total_floor_area: Optional[str] = None

    # Sums insured / financial
    total_insured_value: Optional[float] = None
    requested_sum_insured: Optional[float] = None
    deductible: Optional[str] = None
    previous_claims_count: int = 0

    # CAT exposure
    flood_zone: Optional[str] = None
    earthquake_zone: Optional[str] = None
    cyclone_zone: Optional[str] = None
    wildfire_zone: Optional[str] = None

    # Safety / fire protection attributes
    sprinkler_system: Optional[str] = None
    fire_protection_system: Optional[str] = None
    smoke_detection: Optional[str] = None
    cctv_installed: Optional[str] = None
    security_guards: Optional[str] = None
    safety_audit_completed: Optional[str] = None

    # Declared operational hazards
    electrical_hazards: Optional[str] = None
    chemical_storage: Optional[str] = None
    flammable_materials: Optional[str] = None
    explosive_materials: Optional[str] = None
    high_temperature_equipment: Optional[str] = None
    heavy_machinery: Optional[str] = None
    hazardous_processes: Optional[str] = None
    warehouse_storage: Optional[str] = None

    # CAT vendor selection
    cat_vendor: Optional[str] = None

    # Any field the parser could not populate is recorded here as its label
    raw_missing_labels: List[str] = field(default_factory=list)

    # The full flat {label: value} dict as parsed, kept for tools that
    # operate on raw proposal-form field labels (e.g. hazard_detection_tool).
    raw_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkedDocument:
    """A supporting document (electrical/engineering report, loss runs)
    identified as belonging to a proposal via its own 'Proposal Reference'
    field matching the proposal's 'Proposal Number'."""

    doc_type: str          # "electrical_report" | "engineering_report" | "loss_runs"
    file_path: str
    proposal_reference: Optional[str] = None
    raw_html: str = ""


@dataclass
class FinalDecision:
    application_id: Optional[str]
    status: str  # COMPLETED / STOPPED_INCOMPLETE / STOPPED_MISMATCH / STOPPED_HUMAN_REVIEW / DECLINED / CONDITIONALLY_APPROVED
    decision_mode: Optional[str]   # AUTONOMOUS / HUMAN_REVIEW / SENIOR_UNDERWRITER / OVERRIDE
    decision_maker: Optional[str]  # AI / Human Underwriter / Senior Underwriter
    risk_category: Optional[str]
    risk_score: Optional[int]
    confidence: Optional[float]
    recommendation: Dict[str, Any]
    decision_evidence: List[str]
    audit_trail: List[str]
    communication: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Pydantic output_schema contracts -- one per Google ADK LlmAgent
# ---------------------------------------------------------------------------

class SubmissionIntakeOutput(BaseModel):
    complete: bool = Field(description="True if the submission has everything needed to start underwriting.")
    missing_fields: List[str] = Field(default_factory=list, description="Human-readable labels of missing mandatory fields.")
    confidence: float = Field(default=0.9, description="0.0-1.0 confidence in the completeness assessment.")
    notes: List[str] = Field(default_factory=list, description="Short reasoning notes.")


class DocumentIntelligenceOutput(BaseModel):
    disclosure_mismatch: bool = Field(description="True if the proposal's declarations conflict with a linked report's findings.")
    issues: List[Dict[str, Any]] = Field(default_factory=list, description="Each item: {field, declared, document, keyword_hits}.")
    extracted_hazards: List[Dict[str, str]] = Field(default_factory=list, description="Hazards declared or discovered across proposal + linked documents.")
    notes: List[str] = Field(default_factory=list)


class CATExposureOutput(BaseModel):
    vendor_approved: bool
    pii_redacted: bool
    cat_score: int = Field(description="0-100, higher = more exposed.")
    cat_category: str = Field(description="LOW, MEDIUM, or HIGH.")
    notes: List[str] = Field(default_factory=list)


class RiskSummaryOutput(BaseModel):
    risk_score: int = Field(description="0-100 overall risk score.")
    risk_category: str = Field(description="LOW, MEDIUM, or HIGH.")
    material_risk: bool = Field(description="True if risk_score >= the material risk threshold.")
    confidence: float = Field(description="0.0-1.0 confidence in this risk assessment.")
    summary: str = Field(description="One or two sentence plain-language risk summary.")
    reasoning: List[str] = Field(default_factory=list, description="Bullet-point evidence for the risk assessment.")


class PricingOutput(BaseModel):
    recommendation: str = Field(description="Human-readable pricing recommendation, e.g. loading applied or standard rate.")
    indicative_premium: Optional[float] = None
    deductible: Optional[str] = None
    rationale: List[str] = Field(default_factory=list)


class HumanUnderwriterOutput(BaseModel):
    action: str = Field(description="Approve, Decline, Escalate, or Override.")
    reason: str = Field(description="Short reason for the action.")
    reviewer_notes: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list, description="Only if action implies conditional approval.")


class SeniorUnderwriterOutput(BaseModel):
    approve: bool = Field(description="True to grant conditional approval, False to reject / request more review.")
    reason: str
    conditions: List[str] = Field(default_factory=list)
    requested_items: List[str] = Field(default_factory=list, description="Only if more review/information is requested.")


class EvidenceSummaryOutput(BaseModel):
    ai_summary: str = Field(description="One-paragraph plain-language summary of the case and outcome, for underwriting leadership.")
