"""
Risk Assessment Agent (Google ADK LlmAgent)

Business question: "What is the applicant's risk profile?"

Reasons over normalized applicant data across four dimensions -- medical,
lifestyle, financial, claims -- and produces an overall score, category,
per-dimension ratings, a material-risk flag, and a plain-language summary.

The scoring guidance below mirrors the underwriting desk rules this
workflow was originally built with (see the material-risk threshold and
per-dimension weights), so the LLM's judgment stays anchored to the same
business logic -- it isn't inventing its own risk model from scratch.
"""

from dataclasses import asdict

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, RiskAssessmentOutput
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

MATERIAL_RISK_THRESHOLD = 45

INSTRUCTION = f"""
You are the Risk Assessment Agent in an insurance underwriting workflow.

You receive normalized applicant data. Assess risk across four dimensions
and produce an overall risk_score (0-100):

MEDICAL (up to ~45 pts):
- Existing medical conditions reported -> add weight
- Hospitalization history in the last ~10 years -> add weight
- BMI >= 30 (obesity) -> add weight; BMI 25-30 (overweight) -> smaller weight

LIFESTYLE (up to ~45 pts):
- Current smoker -> add weight
- Hazardous occupation exposure (e.g. aviation) -> add weight
- Genuinely hazardous hobbies (skydiving, scuba, motor racing) -> add weight
  (benign hobbies like badminton, golf, running, trekking do NOT count)

FINANCIAL (up to ~15 pts):
- Sum insured as a multiple of declared annual income: >15x is high,
  10-15x is moderate, <10x is normal

CLAIMS (up to ~15 pts):
- Any previous claim on record -> add weight

Then:
- risk_category: HIGH if risk_score >= {MATERIAL_RISK_THRESHOLD}, MEDIUM if
  risk_score >= 20, else LOW.
- material_risk: true if risk_score >= {MATERIAL_RISK_THRESHOLD}.
- confidence: reflect how complete the underlying data was (more populated
  fields = higher confidence), roughly in the 0.6-0.97 range.
- reasoning: a short bullet per dimension explaining what drove the score.
- summary: one or two plain-language sentences a human underwriter could
  read at a glance.

Respond ONLY with JSON matching the required schema. Do not add commentary
outside the JSON.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="RiskAssessmentAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=RiskAssessmentOutput,
    )


def run(applicant: ApplicantData) -> dict:
    """
    Returns:
        {"risk_score": int, "risk_category": str, "medical_risk": str,
         "financial_risk": str, "lifestyle_risk": str, "claims_risk": str,
         "material_risk": bool, "confidence": float, "summary": str,
         "reasoning": [...]}
    """
    payload = {"applicant_data": asdict(applicant)}

    agent = build_agent()
    result = call_agent(agent, payload)

    # Keep the material-risk flag/category anchored to the stated threshold
    # even if the model's own categorical labels drift slightly.
    score = result.get("risk_score", 0)
    result["material_risk"] = score >= MATERIAL_RISK_THRESHOLD
    if "risk_category" not in result or not result["risk_category"]:
        result["risk_category"] = (
            "HIGH" if score >= MATERIAL_RISK_THRESHOLD else "MEDIUM" if score >= 20 else "LOW"
        )

    return result
