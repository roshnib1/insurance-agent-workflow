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

from pydantic import ValidationError

from google.adk.agents import LlmAgent

from schemas.models import ApplicantData, RiskAssessmentOutput
from tools.medical_risk_tool import assess_medical_risk
from tools.lifestyle_risk_tool import assess_lifestyle_risk
from tools.financial_risk_tool import assess_financial_risk
from tools.claims_tool import assess_claims_risk
from tools.scoring_tool import compute_overall_risk_score
from workflow.model_config import get_model
from workflow.adk_runtime import call_agent

MATERIAL_RISK_THRESHOLD = 45

INSTRUCTION = f"""
You are the Risk Assessment Agent in an insurance underwriting workflow.

You receive normalized applicant data. You have five tools -- call the
first four, then the fifth to aggregate their results:

1. assess_medical_risk(medical_conditions, hospitalization_history, bmi)
2. assess_lifestyle_risk(smoking_status, hazardous_occupation, hazardous_hobbies)
3. assess_financial_risk(sum_insured, annual_income)
4. assess_claims_risk(previous_claims_filed, claims_details)
5. compute_overall_risk_score(medical_result, lifestyle_result,
   financial_result, claims_result) -- pass it the exact dicts returned by
   tools 1-4. It returns risk_score, risk_category, material_risk, and the
   four per-dimension risk labels (medical_risk, lifestyle_risk,
   financial_risk, claims_risk). Use its output directly for those fields
   -- do not recompute them yourself.

Your own judgment is only needed for:
- confidence: reflect how complete the underlying data was (more populated
  fields = higher confidence), roughly in the 0.6-0.97 range.
- summary: one or two plain-language sentences a human underwriter could
  read at a glance.
- reasoning: you can use the combined "reasoning" list from
  compute_overall_risk_score's output as-is, or lightly tidy it.

Respond ONLY with a JSON object of this exact shape, and no other text:
{{
  "risk_score": <int 0-100>,
  "risk_category": "LOW"|"MEDIUM"|"HIGH",
  "medical_risk": "LOW"|"MEDIUM"|"HIGH",
  "financial_risk": "LOW"|"MEDIUM"|"HIGH",
  "lifestyle_risk": "LOW"|"MEDIUM"|"HIGH",
  "claims_risk": "LOW"|"MEDIUM"|"HIGH",
  "material_risk": <bool, true if risk_score >= {MATERIAL_RISK_THRESHOLD}>,
  "confidence": <float 0.0-1.0>,
  "summary": <string>,
  "reasoning": [<string>, ...]
}}
"""

JUDGMENT_INSTRUCTION = f"""
You are the Risk Assessment Agent in an insurance underwriting workflow.

You receive a JSON payload that already includes `tool_result` from the
deterministic risk tools (risk_score, risk_category, material_risk,
per-dimension labels, reasoning). Do NOT call tools.

Use tool_result for score/category/material_risk/dimension labels. Add your
own confidence (0.6-0.97) and a short summary. You may lightly tidy reasoning.

Respond ONLY with a JSON object of this exact shape, and no other text:
{{
  "risk_score": <int 0-100>,
  "risk_category": "LOW"|"MEDIUM"|"HIGH",
  "medical_risk": "LOW"|"MEDIUM"|"HIGH",
  "financial_risk": "LOW"|"MEDIUM"|"HIGH",
  "lifestyle_risk": "LOW"|"MEDIUM"|"HIGH",
  "claims_risk": "LOW"|"MEDIUM"|"HIGH",
  "material_risk": <bool, true if risk_score >= {MATERIAL_RISK_THRESHOLD}>,
  "confidence": <float 0.0-1.0>,
  "summary": <string>,
  "reasoning": [<string>, ...]
}}
"""


def build_agent(*, with_tools: bool = True) -> LlmAgent:
    return LlmAgent(
        name="RiskAssessmentAgent",
        model=get_model(),
        instruction=INSTRUCTION if with_tools else JUDGMENT_INSTRUCTION,
        tools=[
            assess_medical_risk,
            assess_lifestyle_risk,
            assess_financial_risk,
            assess_claims_risk,
            compute_overall_risk_score,
        ]
        if with_tools
        else [],
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

    try:
        result = RiskAssessmentOutput(**result).model_dump()
    except ValidationError:
        pass  # fall through with the raw dict; defaults below still apply

    result.setdefault("confidence", 0.7)
    result.setdefault("summary", "")
    result.setdefault("reasoning", [])

    # Keep the material-risk flag/category anchored to the stated threshold
    # even if the model's own categorical labels drift slightly.
    score = result.get("risk_score", 0)
    result["material_risk"] = score >= MATERIAL_RISK_THRESHOLD
    if "risk_category" not in result or not result["risk_category"]:
        result["risk_category"] = (
            "HIGH" if score >= MATERIAL_RISK_THRESHOLD else "MEDIUM" if score >= 20 else "LOW"
        )

    return result
