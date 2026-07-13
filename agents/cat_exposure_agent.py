"""
CAT Exposure Agent (Google ADK LlmAgent)

Phase 3 -- CAT Exposure.

"""

from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent

from tools.cat_vendor_tool import call_cat_vendor as _call_cat_vendor_impl
from tools.pii_redaction_tool import redact_pii as _redact_pii_impl
from tools.vendor_approval_tool import check_vendor_approval as _check_vendor_approval_impl
from workflow.adk_runtime import call_agent
from workflow.model_config import get_model

INSTRUCTION = """
You are the CAT Exposure Agent in a commercial property underwriting
workflow.

Call your tools in this order:
1. `check_vendor_approval` -- confirms the CAT vendor is on the approved
   list. If it is NOT approved, stop here -- do not call the remaining
   tools, and report cat_score/cat_category as 0/"LOW" with a note that
   the vendor was not approved.
2. `redact_pii` -- strips PII from the payload before any external call.
3. `call_cat_vendor` -- gets the CAT exposure score/category. Only call
   this after redact_pii.

After calling the tools, your ENTIRE response must be the JSON object below
and nothing else.
Do NOT write any explanation, reasoning, restatement of the tool's result,
or commentary before or after it -- not even one sentence. Do NOT use
markdown code fences. The very first character you output must be '{' and
the very last character must be '}'. This exact shape:
{
  "vendor_approved": <bool>,
  "pii_redacted": <bool>,
  "cat_score": <int>,
  "cat_category": <string>,
  "notes": [<string>, ...]
}
"""


def build_agent(
    vendor_name: str,
    applicant_fields: Dict[str, Any],
    flood_zone: Optional[str],
    earthquake_zone: Optional[str],
    cyclone_zone: Optional[str],
    wildfire_zone: Optional[str],
    progress_callback: Optional[Any] = None,
) -> LlmAgent:
    shared: Dict[str, Any] = {}

    def check_vendor_approval() -> Dict[str, Any]:
        """Checks whether the CAT vendor is on the approved-vendor list."""
        result = _check_vendor_approval_impl(vendor_name, progress_callback=progress_callback)
        shared["vendor_approval"] = result
        return result

    def redact_pii() -> Dict[str, Any]:
        """Redacts PII fields from the applicant payload before it is sent externally."""
        result = _redact_pii_impl(applicant_fields, progress_callback=progress_callback)
        shared["pii_redaction"] = result
        return result

    def call_cat_vendor() -> Dict[str, Any]:
        """Calls the (mocked) external CAT vendor with the PII-redacted payload."""
        redacted_payload = shared.get("pii_redaction", {}).get("redacted_payload", applicant_fields)
        result = _call_cat_vendor_impl(
            vendor_name, redacted_payload, flood_zone, earthquake_zone, cyclone_zone, wildfire_zone,
            progress_callback=progress_callback,
        )
        shared["cat_result"] = result
        return result

    agent = LlmAgent(
        name="CATExposureAgent",
        model=get_model(),
        instruction=INSTRUCTION,
        tools=[check_vendor_approval, redact_pii, call_cat_vendor],
    )
    agent._shared_state = shared  # exposed for run()'s belt-and-braces fallback below
    return agent


def run(
    vendor_name: str,
    applicant_fields: Dict[str, Any],
    flood_zone: Optional[str],
    earthquake_zone: Optional[str],
    cyclone_zone: Optional[str],
    wildfire_zone: Optional[str],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {"vendor_approved": bool, "pii_redacted": bool, "cat_score": int, "cat_category": str, "notes": [...]}
    """
    agent = build_agent(vendor_name, applicant_fields, flood_zone, earthquake_zone, cyclone_zone, wildfire_zone,
                         progress_callback=progress_callback)
    payload = {"vendor_name": vendor_name, "applicant_fields": applicant_fields,
               "flood_zone": flood_zone, "earthquake_zone": earthquake_zone,
               "cyclone_zone": cyclone_zone, "wildfire_zone": wildfire_zone}
    result = call_agent(agent, payload, progress_callback=progress_callback)
    result.setdefault("notes", [])

    # Belt-and-braces: if the model skipped a tool call (or misreported
    # its result), fall back to running the deterministic chain ourselves
    # -- these three fields are ground truth, never the LLM's to invent.
    shared = getattr(agent, "_shared_state", {})
    vendor_approval = shared.get("vendor_approval") or _check_vendor_approval_impl(vendor_name)
    if not vendor_approval["approved"]:
        result["vendor_approved"] = False
        result["cat_score"] = 0
        result["cat_category"] = "LOW"
        result["pii_redacted"] = shared.get("pii_redaction", {}).get("pii_found", False)
        return result

    pii_redaction = shared.get("pii_redaction") or _redact_pii_impl(applicant_fields)
    cat_result = shared.get("cat_result") or _call_cat_vendor_impl(
        vendor_name, pii_redaction["redacted_payload"], flood_zone, earthquake_zone, cyclone_zone, wildfire_zone,
    )

    result["vendor_approved"] = True
    result["pii_redacted"] = pii_redaction.get("pii_found", False)
    result["cat_score"] = cat_result.get("cat_score", 0)
    result["cat_category"] = cat_result.get("cat_category", "LOW")

    return result
