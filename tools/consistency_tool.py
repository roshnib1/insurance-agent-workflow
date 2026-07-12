"""
ConsistencyValidationTool (ADK tool)

New tool. Codifies the three comparison rules that previously existed
only as prose inside document_agent.py's instruction:
  - Smoking status: declared vs. medical report finding
  - Previous claims filed: declared "No" vs. a claim history extract
    that actually lists claims
  - Declared annual income vs. salary proof / Form 16 (flagged if the
    variance exceeds ~15%)

The Document Intelligence Agent is still expected to use judgment for
anything outside these well-defined rules; this tool covers the
deterministic part so it isn't left purely to LLM pattern-matching.
"""

import re
from typing import Any, Dict, List, Optional

from tools._common import log_tool_io

INCOME_VARIANCE_THRESHOLD = 0.15


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


@log_tool_io
def validate_consistency(
    declared_smoking_status: Optional[str] = None,
    declared_previous_claims_filed: Optional[str] = None,
    declared_annual_income: Optional[float] = None,
    extracted_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compare declared proposal answers against extracted supporting-document data.

    Args:
        declared_smoking_status: Applicant's self-declared smoking status.
        declared_previous_claims_filed: Applicant's self-declared "Yes"/"No"
            answer for previous insurance claims filed.
        declared_annual_income: Applicant's self-declared annual income.
        extracted_data: Flattened supporting-document data, as produced by
            extract_supporting_document_data (keys like
            "<document title> - <label>").

    Returns:
        {"consistent": bool, "issues": [{"field": str, "declared": str, "found": str}, ...]}
    """
    issues: List[Dict[str, str]] = []
    extracted_data = extracted_data or {}

    # --- Smoking status vs medical report ---
    smoking_keys = [k for k in extracted_data if "smok" in k.lower()]
    declared_smoking = str(declared_smoking_status or "").strip().lower()
    for key in smoking_keys:
        found = str(extracted_data[key]).strip()
        found_lower = found.lower()
        if declared_smoking and found_lower and declared_smoking not in found_lower and found_lower not in declared_smoking:
            issues.append({"field": "Smoking Status", "declared": str(declared_smoking_status), "found": found})

    # --- Previous claims vs claim history extract ---
    claim_keys = [k for k in extracted_data if "claim" in k.lower()]
    declared_claims = str(declared_previous_claims_filed or "").strip().lower()
    if claim_keys and declared_claims in ("no", "none", ""):
        for key in claim_keys:
            found = str(extracted_data[key]).strip()
            if found and found.lower() not in ("no", "none", "nil", ""):
                issues.append({
                    "field": "Previous Insurance Claims Filed",
                    "declared": str(declared_previous_claims_filed or "No"),
                    "found": found,
                })
                break

    # --- Declared income vs salary proof / Form 16 ---
    income_keys = [k for k in extracted_data if "income" in k.lower() or "salary" in k.lower()]
    declared_income = _to_number(declared_annual_income)
    if declared_income:
        for key in income_keys:
            found_income = _to_number(extracted_data[key])
            if found_income and found_income > 0:
                variance = abs(declared_income - found_income) / found_income
                if variance > INCOME_VARIANCE_THRESHOLD:
                    issues.append({
                        "field": "Declared Annual Income",
                        "declared": str(declared_income),
                        "found": str(found_income),
                    })

    return {"consistent": len(issues) == 0, "issues": issues}
