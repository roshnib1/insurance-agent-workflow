# Insurance Underwriting Workflow — Google ADK Version

This is the Google Agent Development Kit (ADK) version of the underwriting
workflow, rebuilt from the working rule-based prototype using the same
folder structure, schemas, parsers, and governance-hook design — but with
the five business agents now implemented as real ADK `LlmAgent`s that
reason over the data instead of pure if/else scoring.

## What stayed the same as the non-ADK version

- `services/html_parser.py`, `services/pdf_parser.py`, `services/normalizer.py` —
  unchanged. Turning a PDF/HTML proposal into the common `ApplicantData`
  shape is a deterministic parsing job, not something that benefits from
  an LLM call.
- `services/communication_service.py` — unchanged. Drafting the (unsent)
  broker/applicant emails is templating, kept deterministic and auditable.
- The 5-agent business workflow and its decision gates (complete? →
  consistent? → material risk? → confidence above threshold?).

## What's new (ADK-specific)

- **`agents/*.py`** — each of the 5 business agents is now a
  `google.adk.agents.LlmAgent` with an `output_schema` (Pydantic model in
  `schemas/models.py`) so every response is structured JSON, not free text.
- **`workflow/model_config.py`** — swappable model backend. Defaults to
  Groq via `LiteLlm` (matches your existing quota workaround); Gemini is
  a one-line env var away.
- **`workflow/adk_runtime.py`** — a small synchronous wrapper around ADK's
  async `Runner`/session API, so each agent module can expose a plain
  `run(...)` function.
- **`workflow/adk_controller.py`** — v2 workflow as a real `google.adk.workflow.Workflow`
  graph with conditional gates; integrates the Assurance SDK for observability.
- **`workflow/assurance.py`** — Operational Assurance SDK wiring (`AssuranceADKPlugin`
  + domain events at underwriting gates). Opt-in via `ASSURANCE_*` env vars.

## Folder structure

```
insurance-agent-workflow/
├── app.py
├── streamlit_app.py
├── agents/
│   ├── submission_agent.py
│   ├── document_agent.py
│   ├── risk_agent.py
│   ├── recommendation_agent.py
│   └── human_review_agent.py
├── workflow/
│   ├── controller.py          # v1 — hand-rolled Python orchestration
│   ├── adk_controller.py        # v2 — ADK Workflow graph
│   ├── assurance.py             # Assurance SDK integration (v2)
│   ├── state.py
│   ├── model_config.py
│   └── adk_runtime.py
├── services/
│   ├── pdf_parser.py
│   ├── html_parser.py
│   ├── normalizer.py
│   └── communication_service.py
├── schemas/
│   └── models.py
├── data/                  (your 4 sample proposal forms)
├── output/                (decision.json + email_draft_*.json land here)
└── requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your API key
export $(cat .env | xargs)  # or use python-dotenv / your shell's env loading
```

## Run

```bash
python app.py data/proposal.html               # v1 — low risk, straight-through
python app.py data/proposal.html --v2          # v2 — ADK Workflow graph (+ Assurance if configured)
python app.py data/proposal_incomplete.html     # missing mandatory fields
python app.py data/proposal_high_risk.html      # material risk -> human review
python app.py data/proposal_mismatch.html       # disclosure mismatch -> human review
```

Each run prints the final decision JSON and writes it to
`output/decision.json` (plus `output/email_draft_<proposal_number>.json`
whenever a communication was drafted).

## Operational Assurance (v2 only)

The v2 workflow (`--v2` or Streamlit "ADK Workflow graph") can emit
observability events to the [Assurance SDK gateway](../Governance/sdk-gateway)
when `ASSURANCE_*` env vars are set. See [`how-to-use-sdk.md`](how-to-use-sdk.md)
for full SDK documentation.

### Setup

1. Install dependencies (includes `assurance-sdk[adk]` from the local sdk-gateway repo):

   ```bash
   pip install -r requirements.txt
   ```

2. Start the gateway (from `../Governance/sdk-gateway`):

   ```bash
   export GATEWAY_SIGNING_SECRET=local-dev-signing-secret
   export GATEWAY_ADMIN_TOKEN=local-dev-admin-token
   uvicorn gateway.app:app --app-dir gateway --host 0.0.0.0 --port 8000
   ```

3. Register a producer with all required event types:

   ```bash
   curl -X POST http://127.0.0.1:8000/v1/producers/register \
     -H 'Content-Type: application/json' \
     -H 'X-Admin-Token: local-dev-admin-token' \
     -d '{
       "producer_id": "insurance-underwriting",
       "tenant_id": "default-tenant",
       "api_key": "your-producer-api-key",
       "producer_type": "SDK",
       "allowed_event_types": [
         "WORKFLOW_RUN_STARTED", "WORKFLOW_RUN_COMPLETED", "WORKFLOW_RUN_FAILED",
         "AGENT_RUN_STARTED", "AGENT_RUN_COMPLETED", "AGENT_RUN_FAILED",
         "MODEL_INVOCATION_STARTED", "MODEL_INVOCATION_COMPLETED", "MODEL_INVOCATION_FAILED",
         "TOOL_CALL_STARTED", "TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED",
         "UNDERWRITING_GATE_EVALUATED", "UNDERWRITING_DECISION_FINALIZED", "HUMAN_APPROVAL"
       ]
     }'
   ```

4. Copy assurance vars into `.env` (see `.env.example`):

   ```bash
   ASSURANCE_GATEWAY_URL=http://127.0.0.1:8000
   ASSURANCE_API_KEY=your-producer-api-key
   ASSURANCE_PRODUCER_ID=insurance-underwriting
   ASSURANCE_TENANT_ID=default-tenant
   ```

5. Run v2 and check events at `http://127.0.0.1:8000/dashboard`.

Instrumentation is non-blocking: if the gateway is down or env vars are
missing, the workflow still completes normally.

## Notes

- `MODEL_PROVIDER=groq` is the default in `.env.example` since that's what
  resolved your earlier Gemini free-tier quota issue. Switch to
  `MODEL_PROVIDER=gemini` any time by uncommenting Option B.
- The Risk Assessment Agent's instruction embeds the same scoring weights
  and material-risk threshold (45) as the original rule-based scorer, so
  its output stays anchored to the same underwriting logic even though an
  LLM is now doing the reasoning.
