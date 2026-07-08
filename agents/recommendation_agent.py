"""
Underwriting Recommendation Agent (Google ADK LlmAgent)

Business question: "What underwriting action should be recommended?"

Translates the Risk Assessment Agent's output into an eligibility
recommendation, premium guidance, coverage conditions, rationale, and a
confidence score. Does not re-derive risk -- it reasons on top of the risk
result it's given.
"""

from dataclasses import asdict

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, RiskAssessmentOutput, UnderwritingRecommendationOutput  # noqa: F401
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Underwriting Recommendation Agent in an insurance underwriting
workflow.

You receive normalized applicant data plus a completed risk assessment
(risk_score, risk_category, per-dimension risk labels, reasoning).

Decide:
- recommendation: APPROVE (risk_category LOW), APPROVE_WITH_CONDITIONS
  (risk_category MEDIUM), or REFER (risk_category HIGH -- always require
  senior underwriter sign-off for HIGH, never auto-approve or auto-decline
  a HIGH risk case yourself).
- premium: brief guidance -- LOW: standard rate, no loading. MEDIUM:
  standard + 15-25% risk loading. HIGH: standard + 40%+ loading or refer
  to specialist pricing.
- coverage_conditions: add specific conditions when relevant, e.g. medical
  exclusion/loading for HIGH medical_risk, lifestyle exclusion (e.g.
  smoker loading) for HIGH lifestyle_risk, claims history review for
  MEDIUM/HIGH claims_risk.
- rationale: carry forward the key evidence from the risk assessment plus
  your own reasoning for the recommendation.
- confidence: generally mirror the risk assessment's confidence unless you
  have a specific reason to adjust it.

Respond ONLY with JSON matching the required schema. Do not add commentary
outside the JSON.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="UnderwritingRecommendationAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=UnderwritingRecommendationOutput,
    )


def run(applicant: ApplicantData, risk_result: dict) -> dict:
    """
    Returns:
        {"recommendation": str, "premium": str, "coverage_conditions": [...],
         "rationale": [...], "confidence": float}
    """
    payload = {
        "applicant_data": asdict(applicant),
        "risk_assessment": risk_result,
    }

    agent = build_agent()
    return call_agent(agent, payload)
