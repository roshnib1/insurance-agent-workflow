"""
agents/ -- Google ADK LlmAgents, reasoning-only, one responsibility each.

Every deterministic tool call in this workflow (parsing, hazard/mismatch
detection, vendor/PII/CAT checks, risk scoring, pricing, delegated
authority, communication drafting, decision assembly) happens as a
FunctionNode step in workflow/property_controller.py, not inside an
agent. That keeps every agent free to use `output_schema` (Google ADK
does not allow `output_schema` and `tools=[...]` on the same LlmAgent)
for guaranteed structured JSON output, and keeps "business logic belongs
in deterministic Python code" (per spec) unambiguous: an agent only ever
sees already-computed deterministic results in its payload and adds
judgment/explanation on top.
"""
