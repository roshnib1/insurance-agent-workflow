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
- `hooks/sdk_hooks.py` — unchanged. Same `PolicyHook` / `NoOpPolicyHook`
  interface for the external Governance SDK to hook into later.
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
- **`workflow/controller.py`** — the custom workflow controller (explicitly
  **not** a `SequentialAgent`). It owns the shared `UnderwritingState`,
  calls each agent in order, evaluates every decision gate itself in plain
  Python, wraps every agent call with `hook.before_agent`/`after_agent`,
  and assembles `output/decision.json`.

## Folder structure

```
insurance_agent_adk/
├── app.py
├── agents/
│   ├── submission_agent.py
│   ├── document_agent.py
│   ├── risk_agent.py
│   ├── recommendation_agent.py
│   └── human_review_agent.py
├── workflow/
│   ├── controller.py
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
├── hooks/
│   └── sdk_hooks.py
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
python app.py data/proposal.html               # low risk, straight-through
python app.py data/proposal_incomplete.html     # missing mandatory fields
python app.py data/proposal_high_risk.html      # material risk -> human review
python app.py data/proposal_mismatch.html       # disclosure mismatch -> human review
```

Each run prints the final decision JSON and writes it to
`output/decision.json` (plus `output/email_draft_<proposal_number>.json`
whenever a communication was drafted).

## Notes

- `MODEL_PROVIDER=groq` is the default in `.env.example` since that's what
  resolved your earlier Gemini free-tier quota issue. Switch to
  `MODEL_PROVIDER=gemini` any time by uncommenting Option B.
- The Risk Assessment Agent's instruction embeds the same scoring weights
  and material-risk threshold (45) as the original rule-based scorer, so
  its output stays anchored to the same underwriting logic even though an
  LLM is now doing the reasoning.
- Governance SDK integration is still just the hook interface — no policy
  logic is implemented here, per the original scope.
