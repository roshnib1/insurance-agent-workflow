"""
Underwriting Recommendation Agent (Google ADK LlmAgent)

Business question: "What underwriting action should be recommended?"

Translates the Risk Assessment Agent's output into an eligibility
recommendation, premium guidance, coverage conditions, rationale, and a
confidence score. Does not re-derive risk -- it reasons on top of the risk
result it's given.
"""

from dataclasses import asdict

from pydantic import ValidationError

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, RiskAssessmentOutput, UnderwritingRecommendationOutput  # noqa: F401
from tools.premium_tool import recommend_premium
from tools.coverage_condition_tool import determine_coverage_conditions
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

INSTRUCTION = """
You are the Underwriting Recommendation Agent in an insurance underwriting
workflow.

You receive normalized applicant data plus a completed risk assessment
(risk_score, risk_category, per-dimension risk labels, reasoning).

You have two tools:
1. recommend_premium(risk_category) -- call this with the risk assessment's
   risk_category to get premium guidance. Use its "premium" value directly.
2. determine_coverage_conditions(medical_risk, lifestyle_risk, claims_risk)
   -- call this with the risk assessment's per-dimension labels to get
   coverage_conditions. Use its output as your starting point; you may add
   further conditions if you judge them relevant.

Decide for yourself:
- recommendation: APPROVE (risk_category LOW), APPROVE_WITH_CONDITIONS
  (risk_category MEDIUM), or REFER (risk_category HIGH -- always require
  senior underwriter sign-off for HIGH, never auto-approve or auto-decline
  a HIGH risk case yourself).
- rationale: carry forward the key evidence from the risk assessment plus
  your own reasoning for the recommendation.
- confidence: generally mirror the risk assessment's confidence unless you
  have a specific reason to adjust it.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "recommendation": "APPROVE"|"APPROVE_WITH_CONDITIONS"|"DECLINE"|"REFER",
  "premium": <string>,
  "coverage_conditions": [<string>, ...],
  "rationale": [<string>, ...],
  "confidence": <float 0.0-1.0>
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="UnderwritingRecommendationAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[recommend_premium, determine_coverage_conditions],
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
    result = call_agent(agent, payload)

    try:
        result = UnderwritingRecommendationOutput(**result).model_dump()
    except ValidationError:
        pass  # fall through with the raw dict

    result.setdefault("coverage_conditions", [])
    result.setdefault("rationale", [])
    result.setdefault("confidence", 0.5)

    return result
