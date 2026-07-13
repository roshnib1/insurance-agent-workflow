# Commercial Property Underwriting Workflow (Google ADK)

An enterprise-style, offline AI underwriting workflow demonstration:
8 phases, 10 explicit decision gates, 8 Google ADK `LlmAgent`s, and
fully deterministic (never-LLM) business logic for anything compliance-
sensitive -- vendor approval, PII redaction, delegated authority,
disclosure-mismatch keyword scanning, and communication drafting.

**Never sends anything.** Every email is a JSON+TXT draft under
`output/emails/`, permanently `"status": "DRAFT_NOT_SENT"`.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your provider's API key
python app.py data/proposal_low_risk.html
# or
streamlit run streamlit_app.py
```

## Two controllers, same output shape

- **`workflow/controller.py` (v1)** -- hand-rolled Python orchestration.
  Every routing decision is a plain `if`/`elif` in one readable function.
  Start here.
- **`workflow/property_controller.py` (v2)** -- the same 8-phase/10-gate
  workflow expressed as a real `google.adk.workflow.Workflow` graph
  (`LlmAgent` nodes + `FunctionNode` gates + `Event(route=...)` + `ctx.state`).
  This is the ADK-native version ("adk_controller" equivalent).

Both call the exact same `agents/*.py` and `tools/*.py`, and both produce
an identical `output/decision.json` shape.

## Folder structure

```
agents/       8 LlmAgents, reasoning only (output_schema, no tools --
              every deterministic tool call happens in the controller)
workflow/     model_config, adk_runtime, state, progress (callbacks),
              governance (one stub), controller.py (v1), property_controller.py (v2)
schemas/      dataclasses + pydantic output_schema contracts
services/     html_parser, pdf_parser, normalizer, document_linker
tools/        12 deterministic, unit-testable functions -- no LLM prompts
data/         9 sample proposals + linked electrical/engineering/loss-run reports
output/       decision_*.json + emails/ (generated at runtime)
```

## Live progress (callbacks)

Every tool and agent call fires a `before`/`after` event through
`workflow/progress.py::ProgressTracker`. `app.py --controller v1` prints
these live; `streamlit_app.py`'s "Run Case" view renders them in a
scrolling panel while the workflow runs.

## Decision modes

| Path | `decision_mode` | `decision_maker` |
|---|---|---|
| Clean case, no mismatch, no material hazard, confidence ≥ 0.75 | `AUTONOMOUS` | `AI` |
| Disclosure mismatch / material hazard resolved by underwriter | `HUMAN_REVIEW` | `Human Underwriter` |
| Escalated, or override exceeds delegated authority | `SENIOR_UNDERWRITER` | `Senior Underwriter` |
| Override accepted within delegated authority | `OVERRIDE` | `Human Underwriter` |

## A note on this sandbox's testing

`google-adk` and `pydantic` aren't installable in this build sandbox (no
network access), so the full LLM call path (`workflow/adk_runtime.py`,
`Runner`, `Workflow` graph execution) could not be executed live here.
Everything else was verified against your real `data/` files:

- `services/`, `tools/`, and `workflow/controller.py`'s full routing
  logic were run end-to-end (with the actual LLM calls mocked) against
  `proposal_low_risk.html` (→ `COMPLETED` / `AUTONOMOUS`) and
  `proposal_disclosure_mismatch.html` (→ governance check fires, mandatory
  human review runs, a real email draft is written, decision.json assembles
  correctly).
- `document_linker.py` correctly found the electrical report + loss runs
  for the mismatch case purely by `Proposal Reference` matching.
- Both `workflow/controller.py` and `workflow/property_controller.py`
  import cleanly and (for v2) the `Workflow` graph builds with all 18
  edges, using local stub packages standing in for `google.adk`/`pydantic`.

Once you `pip install -r requirements.txt` in an environment with network
access and set a real API key, both controllers should run as-is --
but do a first real run per controller before relying on it, since the
live `Runner`/`Workflow` execution path itself couldn't be exercised here.
