"""
agents/ -- Google ADK LlmAgents, one responsibility each.

Most of these agents now call their own deterministic tool(s) directly
via real LLM-directed function calling (`tools=[...]` on the LlmAgent):
SubmissionIntakeAgent, DocumentIntelligenceAgent, CATExposureAgent,
RiskSummaryAgent, PricingAgent, and SeniorUnderwriterAgent all decide
*when* to call their tool(s) themselves, rather than receiving a
precomputed result in their payload. Because Google ADK does not allow
`output_schema` and `tools=[...]` on the same LlmAgent, each of these
agents' final answer is free-form JSON text (parsed manually in that
module's `run()`), and each `run()` re-runs its tool(s) deterministically
one more time as a belt-and-braces guard -- so a routing-critical field
(complete, disclosure_mismatch, vendor_approved, material_risk, ...) is
always correct even if the model skipped or misreported a tool call.

HumanUnderwriterAgent and EvidenceGenerationAgent have no tools to call
(pure judgment / pure narrative-writing) and keep `output_schema` for
guaranteed structured output instead.

Communication drafting and final decision assembly remain plain
deterministic Python (tools/communication_tool.py,
tools/decision_assembly_tool.py) called directly by the workflow
controllers (workflow/controller.py and workflow/property_controller.py)
-- there's no judgment involved in either, so no agent wraps them.
"""
