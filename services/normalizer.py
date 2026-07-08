"""
Maps the raw {"fields": {...}} dict (from html_parser or pdf_parser) into the
common ApplicantData schema, so every downstream agent works off one shape
regardless of input format.
"""

import re
from typing import Dict, Any, Optional

from schemas.models import ApplicantData

# Mandatory fields required before the submission can proceed past intake.
# Chosen to match the business examples given (income, sum insured, medical
# history, hospitalization, signature) plus core identity/consent fields.
MANDATORY_LABELS = {
    "proposal_number": "Proposal Number",
    "applicant_name": "Full Name",
    "dob": "Date of Birth",
    "annual_income": "Declared Annual Income",
    "sum_insured": "Requested Sum Insured",
    "medical_conditions": "Existing Medical Conditions",
    "family_medical_history": "Family Medical History",
    "hospitalization_history": "Hospitalization History",
    "smoking_status": "Smoking Status",
    "signature": "Applicant Signature",
}


def _to_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    digits = re.sub(r"[^\d.]", "", value)
    return float(digits) if digits else None


def _extract_age(dob_value: Optional[str]) -> Optional[int]:
    if not dob_value:
        return None
    match = re.search(r"Age\s*(\d+)", dob_value)
    return int(match.group(1)) if match else None


def normalize(raw: Dict[str, Any]) -> ApplicantData:
    f = raw.get("fields", {})

    applicant = ApplicantData(
        proposal_number=f.get("Proposal Number"),
        application_date=f.get("Application Date"),
        product_type=f.get("Insurance Product"),
        broker_name=f.get("Broker / Agent Name"),

        applicant_name=f.get("Full Name"),
        dob=f.get("Date of Birth"),
        age=_extract_age(f.get("Date of Birth")),
        gender=f.get("Gender"),
        address=f.get("Residential Address"),
        mobile=f.get("Mobile Number"),
        email=f.get("Email Address"),

        employer=f.get("Employer Name"),
        occupation=f.get("Designation"),
        nature_of_work=f.get("Nature of Work"),
        annual_income=_to_number(f.get("Declared Annual Income")),
        existing_policies=f.get("Existing Insurance Policies"),

        sum_insured=_to_number(f.get("Requested Sum Insured")),
        policy_term=f.get("Policy Term"),
        premium_frequency=f.get("Premium Payment Frequency"),
        plan_variant=f.get("Plan Variant"),

        height_cm=_to_number(f.get("Height")),
        weight_kg=_to_number(f.get("Weight")),
        bmi=_to_number(f.get("Weight")),  # BMI text lives inside Weight value; risk_agent re-parses if needed
        medical_conditions=f.get("Existing Medical Conditions"),
        medications=f.get("Current Medications"),
        family_medical_history=f.get("Family Medical History"),
        last_checkup=f.get("Last Medical Checkup Date"),
        hospitalization_history=f.get("Hospitalization History"),

        smoking_status=f.get("Smoking Status"),
        alcohol_consumption=f.get("Alcohol Consumption"),
        hazardous_hobbies=f.get("Hazardous Hobbies / Sports"),
        travel_risk=f.get("Frequent Travel to High-Risk Regions"),
        criminal_history=f.get("Criminal History / Litigation"),
        hazardous_occupation=f.get("Aviation / Hazardous Occupation Exposure"),

        previous_claims_filed=f.get("Previous Insurance Claims Filed"),
        claims_details=raw.get("claims_rows", []),

        signature=f.get("Applicant Signature"),
        signature_date=f.get("Date"),

        attached_documents=raw.get("attached_documents", {}),
        raw_missing_labels=raw.get("missing_labels", []),
    )
    return applicant


def find_missing_mandatory_fields(applicant: ApplicantData) -> list:
    """Returns human-readable labels of mandatory fields that are missing."""
    missing = []
    field_map = {
        "proposal_number": applicant.proposal_number,
        "applicant_name": applicant.applicant_name,
        "dob": applicant.dob,
        "annual_income": applicant.annual_income,
        "sum_insured": applicant.sum_insured,
        "medical_conditions": applicant.medical_conditions,
        "family_medical_history": applicant.family_medical_history,
        "hospitalization_history": applicant.hospitalization_history,
        "smoking_status": applicant.smoking_status,
        "signature": applicant.signature,
    }
    for key, label in MANDATORY_LABELS.items():
        if field_map.get(key) in (None, "", 0):
            missing.append(label)
    return missing
