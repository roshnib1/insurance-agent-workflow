# Commercial Property Underwriting Workflow (Google ADK)

An enterprise-style AI underwriting workflow demonstration, built on Google's Agent
Development Kit (ADK). Eight real ADK `LlmAgent`s reason over a proposal — but every
compliance-sensitive check (vendor approval, PII redaction, delegated authority,
disclosure-mismatch scanning) is fully deterministic and never left to the model.
**Nothing is ever sent** — every communication is a JSON+TXT draft written locally,
permanently marked `"status": "DRAFT_NOT_SENT"`.

Three ways to run it: a terminal CLI, a Streamlit app, or a FastAPI backend + Next.js
frontend.

---

## Contents

- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running it — CLI](#running-it--cli)
- [Running it — Streamlit](#running-it--streamlit)
- [Running it — Web UI](#running-it--web-ui)
- [Running it — Docker](#running-it--docker)
- [Scenarios](#scenarios)
- [Decision modes](#decision-modes)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Architecture notes](#architecture-notes)

---

## How it works

A proposal document moves through **8 phases and 10 explicit decision gates**. Eight
ADK `LlmAgent`s handle reasoning — document understanding, hazard assessment, pricing
rationale, communication drafting — but every gate that actually decides something
compliance-sensitive is plain, unit-testable Python:

```
Vendor approval        -> tools/, never the LLM
PII redaction            -> tools/, never the LLM
Delegated authority        -> tools/, never the LLM
Disclosure-mismatch scan     -> tools/, never the LLM
Communication drafting          -> LlmAgent drafts the text, but it's written to
                                     output/emails/ as DRAFT_NOT_SENT, never dispatched
```

Agents in `agents/` are reasoning-only — they take an `output_schema` and produce
structured output, they hold no tools themselves. Every deterministic tool call happens
in the controller, one layer up, so a gate's business logic is never something buried
inside a prompt.

---

## Project structure

```
workflow_agent/
├── app.py                     # CLI entry point
├── server.py                    # FastAPI backend (wraps property_controller for the web UI)
├── streamlit_app.py               # Streamlit UI (single-process, no separate frontend needed)
├── agents/                          # 8 LlmAgents, reasoning only (output_schema, no tools)
├── workflow/
│   ├── controller.py                  # v1 -- hand-rolled Python orchestration, plain if/elif
│   ├── property_controller.py          # v2 -- real google.adk.workflow.Workflow graph
│   ├── model_config.py                   # provider selection (gemini/groq/openrouter)
│   ├── adk_runtime.py                      # sync wrapper around the ADK Runner
│   ├── state.py                              # shared workflow state object
│   ├── progress.py                             # ProgressTracker -- before/after callbacks
│   └── governance.py                             # the one governance stub
├── schemas/                    # dataclasses + pydantic output_schema contracts
├── services/                     # html_parser, pdf_parser, normalizer, document_linker
├── tools/                          # 12 deterministic, unit-testable functions — no prompts
├── data/                             # 5 sample proposals + linked electrical/loss-run reports
├── output/                             # decision_*.json + emails/ (generated at runtime)
├── frontend/                    # Next.js 15 + React 19 + reactflow + zustand
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

---

## Prerequisites

- **Python 3.10+** — check with `python --version` (Windows: if that fails or opens
  the Microsoft Store, try `py --version` instead and use `py` in place of `python`
  everywhere below)
- **Node.js 20+** and npm — only needed for the web UI, check with `node --version`
- **Docker Desktop** — only needed for the Docker option, and it must actually be
  *running* (open the app, wait for the whale icon to go steady) before `docker
  compose` commands will work

---

## Setup

```bash
cd workflow_agent
pip install -r requirements.txt
```

Copy the example env file if you don't already have one, then add your key:

```bash
cp .env.example .env
```

```dotenv
MODEL_PROVIDER=gemini

# --- gemini (default) ---
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- groq ---
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# --- openrouter ---
# MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemini-2.5-flash
```

Set `MODEL_PROVIDER` to one of `gemini` / `groq` / `openrouter` and fill in the
matching key — this project's 8 `LlmAgent`s need a real key to reason; there is no
zero-config deterministic fallback for the reasoning layer here (unlike the sibling
underwriting/claims projects), only for the compliance-sensitive gates, which are
deterministic by design regardless of config.

---

## Running it — CLI

```bash
python app.py data/proposal_low_risk.html                        # v1 controller (default)
python app.py data/proposal_disclosure_mismatch.html --controller v2   # real ADK Workflow graph
```

Prints live progress as each agent/tool fires (`workflow/progress.py`'s
before/after callbacks), then writes `output/decision_<id>.json` and, if a
communication was drafted, `output/emails/`.

---

## Running it — Streamlit

```bash
streamlit run streamlit_app.py
```

Single-process UI — no separate frontend/backend split needed. The "Run Case" view
renders the same live progress callbacks as the CLI, in a scrolling panel, plus the
final decision and any drafted communications.

---

## Running it — Web UI

Two processes, two terminals:

```bash
# Terminal 1 — backend
uvicorn server:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. The backend's interactive API docs are at
**http://localhost:8000/docs**.

The frontend drives `workflow/property_controller.py` (the real ADK `Workflow` graph)
through `server.py`, and streams live progress via Server-Sent Events
(`GET /events/{run_id}`) — the same underlying callbacks the CLI and Streamlit apps
render, just pushed to the browser in real time instead of printed/rendered locally.

---

## Running it — Docker

Requires Docker Desktop running.

```bash
docker build -t workflow-backend .
docker run -p 8000:8000 --env-file .env -v workflow_output:/app/output workflow-backend
```

```bash
cd frontend
docker build -t workflow-frontend --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 .
docker run -p 3000:3000 workflow-frontend
```

`output/` is where every generated `decision.json`, audit trail, and email draft
lives — mount it as a volume (as above) or every run's artifacts vanish when the
container is removed. The frontend image uses Next's `standalone` output (see
`next.config.ts`) — a self-contained server bundle instead of the full `node_modules`
tree, so the production image stays small.

**`NEXT_PUBLIC_API_BASE_URL` is baked in at build time, not runtime** — same as Vite's
`VITE_` vars in the sibling projects. If the backend's address ever changes, rebuild
the frontend image, don't just restart the container.

---

## Scenarios

| File | What to expect |
|---|---|
| `data/proposal_low_risk.html` | Clean submission, no mismatch, no material hazard, high confidence — `AUTONOMOUS` / `AI` |
| `data/proposal_high_risk.html` | Material hazard present — routes to human/senior review |
| `data/proposal_disclosure_mismatch.html` | Deterministic keyword scan catches a mismatch between the proposal and its linked electrical/loss-run reports — mandatory human review, a real email draft written |
| `data/proposal_incomplete.html` | Missing required fields/documents |
| `data/proposal_override_case.html` | Exercises the delegated-authority override path |

`data/proposal_disclosure_mismatch.html` is the best one to try if you want to see the
deterministic governance layer actually do something: `services/document_linker.py`
finds the linked electrical report and loss runs purely by `Proposal Reference`
matching, the mismatch is caught by a keyword scan — not an LLM judgment call — and a
real (unsent) communication draft gets written to `output/emails/`.

---

## Decision modes

| Path | `decision_mode` | `decision_maker` |
|---|---|---|
| Clean case, no mismatch, no material hazard, confidence ≥ 0.75 | `AUTONOMOUS` | `AI` |
| Disclosure mismatch / material hazard resolved by underwriter | `HUMAN_REVIEW` | `Human Underwriter` |
| Escalated, or override exceeds delegated authority | `SENIOR_UNDERWRITER` | `Senior Underwriter` |
| Override accepted within delegated authority | `OVERRIDE` | `Human Underwriter` |

---

## Tests

```bash
pytest tests/ -v
```

Covers `workflow/adk_runtime.py`'s ADK Runner wrapper directly. Broader coverage
(both controllers' full routing logic, `document_linker.py`'s matching, both
scenarios' end-to-end output shape) has been exercised manually against the real
`data/` files — see [Architecture notes](#architecture-notes) for exactly what's been
verified versus what still needs a first live-key run on your machine.

---

## Troubleshooting

**`python` runs but does nothing / opens the Microsoft Store (Windows)** — you likely
have the Windows Store stub instead of a real Python install. Use `py` instead of
`python` for every command in this README, or reinstall Python from
[python.org](https://python.org) and make sure "Add to PATH" is checked.

**`npm error Missing script: "dev"`** — you're not in the `frontend/` folder. Run `dir`
(Windows) / `ls` (Mac/Linux) and confirm you see `package.json`, `app/`, `components/`
directly in your current directory before running `npm run dev`.

**`No module named 'google.adk'`** — `pip install -r requirements.txt` didn't
actually install it (often a wrong/inactive virtual environment). Confirm with:
```bash
python -c "import google.adk; print(google.adk.__version__)"
```
If that errors, run `pip install google-adk litellm` directly, then retry.

**A run fails immediately with a provider/auth error** — unlike the sibling
underwriting/claims projects, this one has no deterministic fallback for the
reasoning agents themselves — a working `MODEL_PROVIDER` + API key in `.env` is
required for any run to complete, CLI, Streamlit, or web UI.

**`docker compose up` / `docker build` fails with a pipe/daemon connection error** —
Docker Desktop isn't running. Open the app and wait for it to fully start (whale icon
steady in the system tray) before retrying.

---

## Architecture notes

- **Two controllers, identical output shape.** `workflow/controller.py` (v1) is
  hand-rolled Python orchestration — every routing decision is a plain `if`/`elif` in
  one readable function, and it's the one to start with. `workflow/property_controller.py`
  (v2) expresses the same 8-phase/10-gate workflow as a real `google.adk.workflow.Workflow`
  graph — `LlmAgent` nodes, `FunctionNode` gates, `Event(route=...)` edges, `ctx.state` —
  the ADK-native equivalent of the sibling projects' `adk_controller.py`. Both call the
  exact same `agents/*.py` and `tools/*.py`, and both produce an identical
  `output/decision.json` shape.
- **Agents hold no tools.** Every `agents/*.py` module is reasoning-only — it takes an
  `output_schema` and returns structured output. Every deterministic tool call (vendor
  approval, PII redaction, delegated authority, disclosure-mismatch scanning) happens
  one layer up, in the controller — so a compliance-sensitive check is never something
  an LLM could be prompted around, it's ordinary Python sitting outside the agent
  entirely.
- **Live progress via callbacks, not polling.** `workflow/progress.py`'s
  `ProgressTracker` fires a `before`/`after` event around every tool and agent call.
  The CLI prints these directly; Streamlit renders them in a scrolling panel; the web
  UI pushes them to the browser over Server-Sent Events (`GET /events/{run_id}`) — one
  event stream, three different renderers.
- **What's been verified versus what hasn't.** `services/`, `tools/`, and
  `workflow/controller.py`'s full routing logic have been run end-to-end (LLM calls
  mocked) against `proposal_low_risk.html` (→ `COMPLETED`/`AUTONOMOUS`) and
  `proposal_disclosure_mismatch.html` (→ governance fires, human review runs, a real
  email draft writes, `decision.json` assembles correctly). `document_linker.py`
  correctly finds the electrical report + loss runs for the mismatch case by
  `Proposal Reference` matching alone. Both controllers import cleanly, and v2's
  `Workflow` graph builds with all 18 edges. **The live `Runner`/`Workflow` execution
  path itself — an actual LLM call through either controller — has not been exercised
  end-to-end with a real key.** Do a first real run per controller before relying on
  either one, same caution as the sibling projects' own ADK reasoning layers.s