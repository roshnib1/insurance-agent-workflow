"""
CAT Exposure Agent (Google ADK LlmAgent)

Phase 3 -- CAT Exposure.

The vendor-approval check, PII redaction, and mocked external CAT vendor
call are all deterministic steps that already ran in
property_controller.py (tools.vendor_approval_tool, tools.pii_redaction_tool,
tools.cat_vendor_tool) before this agent is called. This agent's job is
purely explanatory: turn those three raw results into a short,
underwriter-facing synthesis. It never overrides any of the three
deterministic outcomes.
"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from schemas.models import CATExposureOutput
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the CAT Exposure Agent in a commercial property underwriting
workflow.

You are given three deterministic results that already ran: whether the
external CAT vendor is approved, whether PII was found and redacted
before the vendor call, and the CAT vendor's exposure score/category.

Your only job is to explain these results clearly for an underwriter --
you do not recompute or override any of the three values.

Respond ONLY with a JSON object of this exact shape, and no other text:
{
  "vendor_approved": <bool, copy from input>,
  "pii_redacted": <bool, copy from input>,
  "cat_score": <int, copy from input>,
  "cat_category": <string, copy from input>,
  "notes": [<string>, ...]
}
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="CATExposureAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        output_schema=CATExposureOutput,
    )


def run(
    vendor_approval: Dict[str, Any],
    pii_redaction: Dict[str, Any],
    cat_result: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Args:
        vendor_approval: tools.vendor_approval_tool.check_vendor_approval(...) output.
        pii_redaction: tools.pii_redaction_tool.redact_pii(...) output.
        cat_result: tools.cat_vendor_tool.call_cat_vendor(...) output.
        progress_callback: optional before/after event sink.

    Returns:
        {"vendor_approved": bool, "pii_redacted": bool, "cat_score": int, "cat_category": str, "notes": [...]}
    """
    payload = {
        "vendor_approval": vendor_approval,
        "pii_redaction": pii_redaction,
        "cat_result": cat_result,
    }

    agent = build_agent()
    result = call_agent(agent, payload, progress_callback=progress_callback)

    # Belt-and-braces: these three fields are deterministic ground truth,
    # never the LLM's to change.
    result["vendor_approved"] = vendor_approval.get("approved", False)
    result["pii_redacted"] = pii_redaction.get("pii_found", False)
    result["cat_score"] = cat_result.get("cat_score", 0)
    result["cat_category"] = cat_result.get("cat_category", "LOW")
    result.setdefault("notes", [])

    return result
