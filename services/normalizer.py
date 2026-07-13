"""
Maps the raw {"fields": {...}} dict (from html_parser or pdf_parser) into
the common CommercialPropertyApplicant schema, so every downstream agent
and tool works off one shape regardless of input format.
"""

import re
from typing import Any, Dict, List, Optional

from schemas.models import CommercialPropertyApplicant

# Mandatory fields required before the submission can proceed past intake.
MANDATORY_LABELS = {
    "proposal_number": "Proposal Number",
    "business_name": "Business Name",
    "primary_property_address": "Primary Property Address",
    "total_insured_value": "Total Insured Value (TIV)",
    "building_type": "Building Type",
    "construction_material": "Construction Material",
    "occupancy_type": "Occupancy Type",
    "requested_sum_insured": "Requested Sum Insured",
    "flood_zone": "Flood Zone",
    "earthquake_zone": "Earthquake Zone",
}


def _to_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    digits = re.sub(r"[^\d.]", "", value)
    return float(digits) if digits else None


def _to_int(value: Optional[str]) -> int:
    number = _to_number(value)
    return int(number) if number is not None else 0


def normalize(raw: Dict[str, Any]) -> CommercialPropertyApplicant:
    f = raw.get("fields", {})

    applicant = CommercialPropertyApplicant(
        proposal_number=f.get("Proposal Number"),
        application_date=f.get("Application Date"),
        underwriting_office=f.get("Underwriting Office"),
        broker_name=f.get("Broker Name"),
        business_name=f.get("Business Name"),
        contact_person=f.get("Contact Person"),
        email=f.get("Email"),
        phone=f.get("Phone"),
        gst_number=f.get("GST Number"),
        pan_number=f.get("PAN Number"),
        registered_address=f.get("Registered Address"),

        primary_property_address=f.get("Primary Property Address"),
        building_type=f.get("Building Type"),
        construction_material=f.get("Construction Material"),
        occupancy_type=f.get("Occupancy Type"),
        year_built=f.get("Year Built"),
        number_of_floors=f.get("Number of Floors"),
        total_floor_area=f.get("Total Floor Area"),

        total_insured_value=_to_number(f.get("Total Insured Value (TIV)")),
        requested_sum_insured=_to_number(f.get("Requested Sum Insured")),
        deductible=f.get("Deductible"),
        previous_claims_count=_to_int(f.get("Previous Claims Count")),

        flood_zone=f.get("Flood Zone"),
        earthquake_zone=f.get("Earthquake Zone"),
        cyclone_zone=f.get("Cyclone Zone"),
        wildfire_zone=f.get("Wildfire Zone"),

        sprinkler_system=f.get("Sprinkler System"),
        fire_protection_system=f.get("Fire Protection System"),
        smoke_detection=f.get("Smoke Detection"),
        cctv_installed=f.get("CCTV Installed"),
        security_guards=f.get("Security Guards"),
        safety_audit_completed=f.get("Safety Audit Completed"),

        electrical_hazards=f.get("Electrical Hazards"),
        chemical_storage=f.get("Chemical Storage"),
        flammable_materials=f.get("Flammable Materials"),
        explosive_materials=f.get("Explosive Materials"),
        high_temperature_equipment=f.get("High Temperature Equipment"),
        heavy_machinery=f.get("Heavy Machinery"),
        hazardous_processes=f.get("Hazardous Processes"),
        warehouse_storage=f.get("Warehouse Storage"),

        cat_vendor=f.get("CAT Vendor") or "GeoRisk CAT Analytics",

        raw_missing_labels=raw.get("missing_labels", []),
        raw_fields=f,
    )
    return applicant


def find_missing_mandatory_fields(applicant: CommercialPropertyApplicant) -> List[str]:
    """Returns human-readable labels of mandatory fields that are missing."""
    missing = []
    field_map = {
        "proposal_number": applicant.proposal_number,
        "business_name": applicant.business_name,
        "primary_property_address": applicant.primary_property_address,
        "total_insured_value": applicant.total_insured_value,
        "building_type": applicant.building_type,
        "construction_material": applicant.construction_material,
        "occupancy_type": applicant.occupancy_type,
        "requested_sum_insured": applicant.requested_sum_insured,
        "flood_zone": applicant.flood_zone,
        "earthquake_zone": applicant.earthquake_zone,
    }
    for key, label in MANDATORY_LABELS.items():
        if field_map.get(key) in (None, "", 0):
            missing.append(label)
    return missing
