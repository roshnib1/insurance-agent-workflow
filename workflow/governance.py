"""
workflow/governance.py

Per the spec: no governance SDK, no hooks, no plugins. Exactly one
function -- input, log, pass-through. Nothing more.
"""

from typing import Any, Dict


def governance_policy_check(trigger: str, context: Dict[str, Any]) -> Dict[str, str]:
    """
    Logs that a governance-relevant event occurred and passes the case
    through to mandatory human review. Does not itself approve, deny, or
    modify anything -- it exists purely as the auditable record that a
    governance checkpoint was triggered and observed.

    Args:
        trigger: what triggered the check, e.g. "disclosure_mismatch",
                 "override_contradicts_material_hazard".
        context: whatever the caller wants logged alongside it
                 (e.g. proposal_number, issue count).

    Returns:
        {"check": "GovernancePolicyCheck", "trigger": trigger, "result": "logged, routed to mandatory human review"}
    """
    return {
        "check": "GovernancePolicyCheck",
        "trigger": trigger,
        "result": "logged, routed to mandatory human review",
    }
