"""
Governance SDK integration surface.

This workflow does not implement any governance logic itself. It only
guarantees that every agent invocation is bracketed by before_agent /
after_agent calls, so the Governance SDK can:
  - validate policies
  - apply rules
  - check confidence thresholds
  - log decisions
  - maintain audit trails
  - trigger human review

The default NoOpPolicyHook below is a pass-through implementation used when
no SDK is wired in, so this workflow runs standalone during development.
"""

from typing import Any, Dict


class PolicyHook:
    """Interface the Governance SDK implements and injects into the orchestrator."""

    def before_agent(self, agent_name: str, data: Dict[str, Any]) -> None:
        """Called immediately before an agent runs, with its structured input."""
        raise NotImplementedError

    def after_agent(self, agent_name: str, result: Dict[str, Any]) -> None:
        """Called immediately after an agent runs, with its structured output."""
        raise NotImplementedError


class NoOpPolicyHook(PolicyHook):
    """Default hook used when no Governance SDK is attached. Does nothing."""

    def before_agent(self, agent_name: str, data: Dict[str, Any]) -> None:
        pass

    def after_agent(self, agent_name: str, result: Dict[str, Any]) -> None:
        pass
