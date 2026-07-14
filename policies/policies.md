# Commercial Property Underwriting — Governance Policies

This document describes every Operational Assurance policy defined under
[`policies/`](.). Policies are evaluated by the Assurance gateway against
immutable workflow events emitted by the v2 graph
([`workflow/property_controller.py`](../workflow/property_controller.py)) via
`AssuranceADKPlugin` and FunctionNode `TOOL_CALL_*` instrumentation.

For how to author, assign, and soak policies, see
[`policy-guidelines.md`](../policy-guidelines.md).

---

## 1. Shared context

| Setting | Value |
| ------- | ----- |
| Tenant | `default-tenant` |
| Producer | `commercial-property-underwriting` |
| Workflow type (assignment) | `commercial_property_underwriting:proposal` |
| Business object type | `proposal` |
| Environment | `test` |
| Primary subject | tool `finalize_decision` |
| Trigger (all policies below) | `TOOL_CALL_COMPLETED` |
| Enforcement (all current versions) | `observe` / `record_finding` |
| Rule language | `structured_assertions` |
| Reference known-good run | `wf_c64141aa870240b3ad35bde967a031e5` (`proposal_low_risk.html`) |

### How evaluation works here

1. The v2 workflow emits framework and FunctionNode events (`WORKFLOW_RUN_*`,
   `AGENT_RUN_*`, `MODEL_INVOCATION_*`, `TOOL_CALL_*`).
2. When a matching `TOOL_CALL_COMPLETED` for `finalize_decision` is accepted,
   assigned policies evaluate their assertions against the **workflow evidence
   window**.
3. Assertions can match top-level columns (`tool_name`, `status`) and **nested
   payload paths** (`result.route`, `tool_args.complete`,
   `payload.result.pricing.rationale`, …) via dotted `where` / `attribute_match`
   / `aggregate` (`len`).
4. Overall result: any `fail` → FAIL; else any `indeterminate` → INDETERMINATE;
   else PASS.

### Priority cheat sheet

Lower assignment `priority` = higher precedence when multiple policies match.

| Priority | Policy ID |
| -------: | --------- |
| 70 | `POL-CPUW-CAT3-DATA-001` |
| 75 | `POL-CPUW-CAT4-EXPLAINABILITY-001` |
| 80 | `POL-CPUW-CAT1-AUTONOMOUS-001` |
| 85 | `POL-CPUW-CAT2-PRICING-001` |
| 90 | `POL-CPUW-DECISION-PAYLOAD-001` |
| 100 | `POL-CPUW-DECISION-CONTROLS-001` |

### Policy catalog map

```text
Foundation (control gates + payload truth)
  POL-CPUW-DECISION-CONTROLS-001   — required gates exist & succeed
  POL-CPUW-DECISION-PAYLOAD-001    — same gates, with nested payload checks

Eight-category library (Categories 1–4 implemented)
  POL-CPUW-CAT1-AUTONOMOUS-001     — who may decide autonomously
  POL-CPUW-CAT2-PRICING-001        — pricing completeness / sanity
  POL-CPUW-CAT3-DATA-001           — PII, vendor, submission data controls
  POL-CPUW-CAT4-EXPLAINABILITY-001 — evidence, rationale, confidence, reason
```

Categories 5–8 (human oversight, audit, ops SLA, advanced AI/fairness) are
designed but not yet encoded as active gateway policies.

---

## 2. Foundation policies

### 2.1 `POL-CPUW-DECISION-CONTROLS-001`

**File:** [`POL-CPUW-DECISION-CONTROLS-001.json`](POL-CPUW-DECISION-CONTROLS-001.json)

| Field | Value |
| ----- | ----- |
| Name | Underwriting decision finalization requires mandatory control gates |
| Category | `underwriting` |
| Priority | 100 |
| Intent layer | Level 1 evidence controls (event presence / absence) |

**Business sentence**

> Before `finalize_decision` completes successfully, `submission_gate`,
> `cat_vendor_gate`, `pii_and_cat_call`, `human_underwriter_gate`, and
> `handle_approve` must already have completed successfully in the same
> workflow.

**Why it exists**

Encodes the mandatory commercial-property underwriting path for an approve-style
final: intake must be complete, CAT vendor must clear governance, the external
CAT call must run, a human underwriter gate must fire, and the approve handler
must finish — then the workflow itself must complete. This is **structural**:
it checks that tools ran successfully, not the business content of their
payloads.

**Subject & trigger**

- Subject: `tool` / `finalize_decision` (`underwriting_decision`, risk `high`)
- Trigger: `TOOL_CALL_COMPLETED`

**Assertions**

| ID | Type | Meaning |
| -- | ---- | ------- |
| `finalize-completed-success` | `event_exists` | `finalize_decision` completed with `status=success` |
| `submission-gate-completed` | `event_exists` | `submission_gate` completed successfully |
| `cat-vendor-gate-completed` | `event_exists` | `cat_vendor_gate` completed successfully |
| `cat-vendor-call-completed` | `event_exists` | `pii_and_cat_call` completed successfully |
| `human-underwriter-gate-completed` | `event_exists` | `human_underwriter_gate` completed successfully |
| `handle-approve-completed` | `event_exists` | `handle_approve` completed successfully |
| `no-finalize-failure` | `event_absence` | No `TOOL_CALL_FAILED` for `finalize_decision` |
| `workflow-completed` | `event_exists` | `WORKFLOW_RUN_COMPLETED` present |

**Registered tools (capability catalog)**

`finalize_decision`, `pii_and_cat_call`, `cat_vendor_gate`,
`human_underwriter_gate`, `submission_gate`, `handle_approve` — used so subject
selectors with capability / risk class resolve correctly.

**Limits / soak notes**

- Approve-path oriented (`handle_approve`). Decline / escalate terminals will
  not satisfy every gate as written.
- Does not inspect routes or decision fields — use payload / Cat1–4 policies
  for that.

---

### 2.2 `POL-CPUW-DECISION-PAYLOAD-001`

**File:** [`POL-CPUW-DECISION-PAYLOAD-001.json`](POL-CPUW-DECISION-PAYLOAD-001.json)

| Field | Value |
| ----- | ----- |
| Name | Approve-path decision must match underwriting payload controls |
| Category | `underwriting` |
| Priority | 90 |
| Intent layer | Level 1 evidence + nested payload attributes |

**Business sentence**

> When `finalize_decision` completes, the workflow must already show
> submission complete (`tool_args.complete=true`, `result.route=complete`),
> CAT vendor approved (`result.route=approved`), a successful CAT call with
> category/score evidence, underwriter Approve (`tool_args.action=Approve`,
> `result.route=approve`), and finalize status / AUTONOMOUS decision mode.

**Why it exists**

Tightens the foundation policy by reading **FunctionNode payloads**: route
markers, PII redaction flags, CAT score, and autonomy fields. Requires gateway
dotted-path matching on `tool_args.*` and `result.*`.

**Assertions**

| ID | Type | What is matched |
| -- | ---- | --------------- |
| `finalize-status-completed` | `event_exists` | `finalize_decision` success + `tool_args.status` / `result.status` = `COMPLETED` |
| `submission-payload-complete` | `event_exists` | `tool_args.complete=true`, `result.route=complete` |
| `cat-vendor-route-approved` | `event_exists` | `result.route=approved` |
| `cat-call-low-or-scored` | `event_exists` | `result.cat_result.cat_category=LOW`, `cat_score=20` |
| `pii-redacted-before-vendor` | `event_exists` | `result.pii_redaction.pii_found=true` |
| `underwriter-action-approve` | `event_exists` | `tool_args.action=Approve`, `result.route=approve` |
| `finalize-decision-mode-present` | `event_exists` | `decision_mode=AUTONOMOUS`, `decision_maker=AI` |
| `no-finalize-failure` | `event_absence` | No failed finalize |

**Limits / soak notes**

- `cat_category=LOW` / `cat_score=20` and AUTONOMOUS mode are **tight to the
  low-risk reference run**. Loosen or split before `warn` / `block` on
  medium/high or mismatch fixtures.
- `pii_found=true` fails scenarios where no PII was present (redaction ran but
  found nothing) — revisit if those paths must pass.

---

## 3. Category library (1–4)

These policies implement the first four buckets of the eight-category
governance model (Autonomous, Pricing, Data, Explainability).

### 3.1 Category 1 — `POL-CPUW-CAT1-AUTONOMOUS-001`

**File:** [`POL-CPUW-CAT1-AUTONOMOUS-001.json`](POL-CPUW-CAT1-AUTONOMOUS-001.json)

| Field | Value |
| ----- | ----- |
| Name | Autonomous Decision Governance — low-risk approval threshold |
| Category | `autonomous_decision_governance` |
| Priority | 80 |

**Business sentence**

> IF `decision_mode == AUTONOMOUS` THEN `risk_category == LOW` AND
> `confidence >= 0.90` on `finalize_decision`.

**Maps to framework ideas**

- Autonomous approval threshold  
- High risk never autonomous  
- Confidence gate for auto-approve  

**Assertions**

| ID | Type | Rule |
| -- | ---- | ---- |
| `autonomous-finalize-present` | `event_exists` | Finalize success with `AUTONOMOUS` + `decision_maker=AI` |
| `autonomous-only-low-risk` | `event_exists` | Same event also has `risk_category=LOW` |
| `autonomous-confidence-threshold` | `attribute_match` | `payload.result.confidence >= 0.9` |
| `autonomous-not-high-risk` | `event_absence` | No finalize with AUTONOMOUS + HIGH |
| `recommendation-is-approve` | `event_exists` | `result.recommendation.action=APPROVE` |

**Limits**

- Scoped to **AUTONOMOUS approve** finals. Pure human-review / decline paths will
  not satisfy `autonomous-finalize-present` as written (by design for this
  soak policy; later versions can branch by `decision_mode`).
- Confidence uses `attribute_match` on the latest matching
  `TOOL_CALL_COMPLETED` decision payload (typically finalize /
  `handle_approve` result).

---

### 3.2 Category 2 — `POL-CPUW-CAT2-PRICING-001`

**File:** [`POL-CPUW-CAT2-PRICING-001.json`](POL-CPUW-CAT2-PRICING-001.json)

| Field | Value |
| ----- | ----- |
| Name | Pricing Governance — premium, deductible, and CAT consistency |
| Category | `pricing_governance` |
| Priority | 85 |

**Business sentence**

> Finalize must include `indicative_premium > 0`, a deductible string,
> pricing rationale, and CAT exposure flags (`vendor_approved`,
> `pii_redacted`) when CAT was used.

**Maps to framework ideas**

- Premium floor (positive premium)  
- Deductible disclosed  
- Pricing explanation required  
- CAT-related pricing consistency (flags on the decision, not full loading math)  

**Assertions**

| ID | Type | Rule |
| -- | ---- | ---- |
| `premium-floor-positive` | `attribute_match` | `pricing.indicative_premium > 0` |
| `deductible-disclosed` | `attribute_match` | `pricing.deductible != null` |
| `pricing-recommendation-present` | `attribute_match` | `pricing.recommendation != null` |
| `pricing-rationale-count` | `aggregate` `len` | `len(pricing.rationale) >= 1` |
| `cat-exposure-on-decision` | `event_exists` | `cat_exposure.vendor_approved` / `pii_redacted` true |
| `low-risk-no-loading-language` | `attribute_match` | recommendation `contains` `"standard"` |

**Limits**

- Does **not** yet enforce numeric loading ≥ 20% for HIGH risk or TIV-based
  minimum deductible tables — those need richer Level-2 facts / decision
  tables.
- `"standard"` language check is aimed at low-risk standard-rate wording.

---

### 3.3 Category 3 — `POL-CPUW-CAT3-DATA-001`

**File:** [`POL-CPUW-CAT3-DATA-001.json`](POL-CPUW-CAT3-DATA-001.json)

| Field | Value |
| ----- | ----- |
| Name | Data Governance — PII redaction, approved vendor, submission completeness |
| Category | `data_governance` |
| Priority | 70 (highest precedence among Cat1–4) |

**Business sentence**

> Submission must be complete; CAT vendor must be approved; `pii_and_cat_call`
> must succeed with redaction evidence; finalize must record
> `vendor_approved` and `pii_redacted`.

**Maps to framework ideas**

- Mandatory document / submission completeness  
- Approved vendor only  
- PII redaction before / around external vendor call  

**Assertions**

| ID | Type | Rule |
| -- | ---- | ---- |
| `submission-complete-before-decision` | `event_exists` | `submission_gate` complete + `tool_args.complete=true` |
| `approved-vendor-only` | `event_exists` | `cat_vendor_gate` → `result.route=approved` |
| `external-cat-call-succeeded` | `event_exists` | `pii_and_cat_call` success |
| `pii-redaction-executed` | `event_exists` | `result.pii_redaction.pii_found=true` |
| `decision-records-vendor-and-pii-flags` | `event_exists` | Finalize carries `vendor_approved` + `pii_redacted` |
| `no-cat-call-failure` | `event_absence` | No `TOOL_CALL_FAILED` for `pii_and_cat_call` |

**Limits**

- Data-freshness (CAT report age) is **not** implemented — no dated CAT
  artifact field yet.
- `pii_found=true` is evidence that the redaction step ran and detected PII;
  a stricter “must strip before send” control may need explicit
  `redacted_fields` length or a dedicated domain event.

---

### 3.4 Category 4 — `POL-CPUW-CAT4-EXPLAINABILITY-001`

**File:** [`POL-CPUW-CAT4-EXPLAINABILITY-001.json`](POL-CPUW-CAT4-EXPLAINABILITY-001.json)

| Field | Value |
| ----- | ----- |
| Name | Explainability — evidence, rationale, confidence, and reason required |
| Category | `explainability` |
| Priority | 75 |

**Business sentence**

> Every completed decision must store confidence, a non-empty
> `recommendation.reason`, ≥3 `decision_evidence` items, and ≥1
> `pricing.rationale` item.

**Maps to framework ideas**

- Evidence required (≥3 items)  
- Pricing explanation required  
- Confidence disclosure  
- Decision basis / reason  

**Assertions**

| ID | Type | Rule |
| -- | ---- | ---- |
| `evidence-min-three` | `aggregate` `len` | `len(decision_evidence) >= 3` |
| `pricing-rationale-required` | `aggregate` `len` | `len(pricing.rationale) >= 1` |
| `confidence-disclosed` | `attribute_match` | `confidence != null` |
| `decision-reason-present` | `attribute_match` | `recommendation.reason != null` |
| `decision-basis-present` | `attribute_match` | `recommendation.basis != null` |
| `ai-summary-present` | `attribute_match` | `ai_summary != null` |

**Limits**

- Does not yet verify that evidence **supports** the decision (hallucination /
  contradiction guards). That needs Category 8-style consistency rules
  (e.g. RISK=HIGH + APPROVE = fail).

---

## 4. Assertion types used

| Type | Used for |
| ---- | -------- |
| `event_exists` | Required tools / fields present in evidence |
| `event_absence` | Prohibited outcomes (failed CAT/finalize, AUTONOMOUS+HIGH) |
| `attribute_match` | Numeric thresholds, non-null checks, `contains` |
| `aggregate` (`len`) | List length on `decision_evidence` / `pricing.rationale` |

Nested business fields are reached with dotted paths such as:

- `result.route`
- `tool_args.complete`
- `result.cat_exposure.vendor_approved`
- `payload.result.pricing.indicative_premium` (attribute / aggregate fields)

---

## 5. Simulate & verify

Against a known workflow:

```bash
curl -sS -X POST "http://127.0.0.1:8000/v1/policies/POL-CPUW-CAT1-AUTONOMOUS-001/simulate" \
  -H "X-Admin-Token: local-dev-admin-token" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default-tenant",
    "workflow_id": "wf_c64141aa870240b3ad35bde967a031e5"
  }'
```

Console:

- Policy detail: `http://127.0.0.1:8000/console/policies/<POLICY_ID>`
- Workflow explorer: `http://127.0.0.1:8000/console/explorer/workflows/<workflow_id>`

All six policies above were simulated **PASS** on the reference low-risk
autonomous run during authoring.

---

## 6. Promotion guidance

1. Keep **`observe`** until mismatch / incomplete / high-risk fixtures behave
   as expected (false-positive rate acceptable).
2. Prefer promoting **Cat3 (data)** and **foundation controls** first — hard
   safety boundaries.
3. Then Cat1 (autonomy) and Cat4 (explainability); then Cat2 pricing math
   once loading / deductible tables exist as facts.
4. Maker-checker: `approved_by` ≠ `created_by` when moving
   `draft` → `active`.
5. Rebuild the gateway image so runtime includes dotted `where` matching and
   aggregate `len` (not only container hot-patches).

---

## 7. Not yet encoded (Categories 5–8)

Documented here so the backlog stays explicit:

| Category | Example rules still to encode |
| -------- | ----------------------------- |
| 5 Human oversight | Material hazard ⇒ mandatory review; override justification / authority |
| 6 Audit | Audit trail non-empty; approval lineage; timeline includes all gates; immutability |
| 7 Operational | SLA `duration_seconds < 300`; agent success; CAT max retries; workflow version |
| 8 AI governance | Hallucination/evidence grounding; HIGH risk ⇏ APPROVE; fairness; model version |

When adding them, prefer new JSON files beside this folder, assign to
`commercial_property_underwriting:proposal`, start in `observe`, and extend
this document.
