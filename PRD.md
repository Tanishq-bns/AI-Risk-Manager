# PRD.md — Product Requirements

**Document status:** Target product requirements for a system with no current implementation.

---

## 1. Personas

### Persona 1: Risk Officer

- **Goals:** Understand why a return was scored the way it was; trust that high-friction interventions are economically justified, not arbitrary; catch systemic model or policy problems early.
- **Pain points:** Black-box scores with no rationale; inability to distinguish a genuine model decision from a fallback-tier decision; no way to see whether a customer was treated fairly relative to their actual history.
- **Workflows:** Reviews the risk dashboard daily; drills into individual HIGH/CRITICAL decisions via the risk inspector; periodically reviews fallback-activation rate and calibration diagnostics.
- **Required information:** `p_return_abuse`, risk band, model version, fallback tier and reason, top contributing signals, selected intervention and its expected net value, full audit trail.
- **Permissions:** Read access to all decisions and evidence; can initiate a manual override (with logged reason).
- **Success criteria:** Can answer "why was this return treated this way?" for any decision within seconds, without engineering involvement.

### Persona 2: Operations Lead

- **Goals:** Understand operational load (manual review volume) and quantified merchant savings; make sure interventions aren't overwhelming the review queue or alienating customers at scale.
- **Pain points:** No visibility into aggregate friction rate; no way to see whether return-abuse prevention is actually saving money net of operational cost.
- **Workflows:** Reviews aggregate dashboard metrics (intervention distribution, manual-review rate, estimated margin saved) weekly; escalates to Risk Officer when volumes look anomalous.
- **Required information:** Aggregate intervention/manual-review/zero-friction rates, estimated merchant margin saved, fallback-activation trend.
- **Permissions:** Read access to aggregate dashboards; no override permission (override is Risk-Officer/Admin scoped).
- **Success criteria:** Can report operational impact to merchant stakeholders using dashboard numbers directly, without manual data pulls.

### Persona 3: Legitimate Buyer

- **Goals:** Return a genuinely unwanted item with minimal friction; not be penalized for someone else's abuse pattern.
- **Pain points:** Being blocked, delayed, or charged a fee for a return that has nothing to do with abuse; opaque "your return was flagged" messages with no path to resolution.
- **Workflows:** Initiates a return through the merchant's normal return flow; is not directly exposed to this system's internals — experiences only the resulting friction level (or lack thereof) and, if escalated, a request for additional verification.
- **Required information (indirectly, via the merchant's customer-facing flow, not this system's dashboard):** Clear reason if friction is applied, and a path to manual review/resolution.
- **Permissions:** None within this system directly — this persona is protected *by* the system's design (economic guardrails, fairness monitoring), not a user *of* it.
- **Success criteria:** Low-risk, legitimate returns resolve via A0 (ZERO_FRICTION_APPROVAL) with no perceptible delay or friction.

## 2. User Stories

- As a Risk Officer, I want to inspect why a return was scored as high risk so that I can validate the decision.
- As a Risk Officer, I want to see whether a decision came from the primary model or a fallback tier so that I can judge how much confidence to place in it.
- As a Risk Officer, I want to override a decision and have the original preserved so that I can correct mistakes without destroying the audit trail.
- As an Operations Lead, I want to see intervention volume and merchant savings so that I can understand operational impact.
- As an Operations Lead, I want to see the manual-review queue size trend so that I can staff appropriately.
- As a legitimate buyer, I want low-risk returns to remain low-friction.
- As a legitimate buyer whose return was flagged, I want a defined path to resolution (manual review) rather than an unexplained block.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | The system must produce a calibrated `p_return_abuse` for every return request that reaches `POST /v1/risk/score`. |
| FR-2 | The system must map `p_return_abuse` to a risk band (LOW/MEDIUM/HIGH/CRITICAL) per SPEC.md §18. |
| FR-3 | The system must estimate `expected_loss`, `expected_margin_saved`, and `expected_net_value` per candidate intervention. |
| FR-4 | The system must select an intervention only from the subset of actions a merchant has enabled (policy-constrained). |
| FR-5 | The system must never select a friction-inducing action unless the economic guardrail (SPEC.md §14 / TRD.md §Economic Guardrails) is satisfied. |
| FR-6 | The system must produce a decision even when the primary model, Isolation Forest, Redis, Redpanda audit publish, Gemini, or LangSmith are unavailable (per ARCHITECTURE.md §13). |
| FR-7 | The system must support manual override without deleting or mutating the original automated decision. |
| FR-8 | The system must expose a risk inspector view showing evidence, model version, fallback tier, and rationale for any decision. |
| FR-9 | The system must never use protected/sensitive attributes as model features. |
| FR-10 | Agent-generated content must never be the numeric source of truth for risk or economic value in a persisted decision. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Synchronous decision path p95 latency ≤ 150 ms, excluding asynchronous agent processing (SPEC.md §12). |
| NFR-2 | Decision availability ≥ 99.9% (demo/service objective) via the fallback cascade (SPEC.md §13). |
| NFR-3 | Observability-system outages (Prometheus, LangSmith) must never affect decisioning (ARCHITECTURE.md §13). |
| NFR-4 | All decisions must be persisted with a complete, immutable audit trail. |
| NFR-5 | The system must not store unnecessary PII; customer identity is represented via `customer_id_hash`. |
| NFR-6 | All inbound event payload text must be treated as untrusted data, never as instruction, by any LLM-backed component (§50 of the master prompt). |

## 5. Intervention Policy (Action Set)

| Action | Purpose | Eligibility | Expected benefit | Customer friction | Operational cost | Safety constraints | Escalation rules | Audit requirements |
|---|---|---|---|---|---|---|---|---|
| **A0 — ZERO_FRICTION_APPROVAL** | Approve the return with no additional friction | Default for LOW band, or any band where the economic guardrail rules out a friction action | Fast resolution, best customer experience, no unnecessary operational cost | None | None | None (always merchant-eligible) | None | Decision logged with `action=A0`, `expected_net_value` recorded even though no intervention was applied |
| **A1 — DYNAMIC_RETURN_FEE** | Apply a variable reverse-pickup fee sized to estimated risk/cost | Merchant must have enabled fee-based interventions in policy config; not eligible for CRITICAL-band cases where fee alone is judged insufficient | Recovers part of expected reverse-logistics/loss cost while allowing the return to proceed | Moderate — customer pays a fee | Low — automated | Fee amount must be computed via the documented economic formula, never an arbitrary constant | If customer disputes the fee, routes to A4 (manual review) | Fee amount, computation basis, and triggering `p_return_abuse`/band logged |
| **A2 — OTP_DOORSTEP_INSPECTION** | Require OTP verification / doorstep inspection at pickup | Merchant must support doorstep inspection logistics; requires `reverse_logistics_cost` data availability | Deters switch-and-return and wardrobing by adding a verification step at the point of highest information value | Moderate-high — added step, possible delay | Moderate — logistics partner involvement | Cannot be applied if the merchant policy config marks doorstep inspection unsupported for the item category | Failed/refused inspection routes to A4 | Inspection outcome (once available) must be logged back to `interventions` for future model training |
| **A3 — STORE_CREDIT** | Offer store credit instead of a cash/original-method refund, where policy permits | Merchant must explicitly allow store-credit-only paths for the product category/order value bracket | Retains revenue within the merchant ecosystem while still resolving the return | Moderate — customer receives credit, not cash | Low | Never applied where store credit is not a policy-permitted resolution for that category (e.g., where consumer-protection rules require cash refund) | Customer objection routes to A4 | Credit issuance amount and policy basis logged |
| **A4 — MANUAL_REVIEW** | Escalate to a human operator | Always eligible; mandatory when the Verifier agent flags contradictory evidence, when policy constraints cannot be satisfied by any automated action, or when confidence is low | Human judgment on ambiguous or high-value cases | Highest — delay while under review | Highest — human review time | None (this is itself the safety valve) | N/A — this is the escalation target | Full case context, including agent enrichment output, must be visible to the reviewing operator |

**Explicit non-assumption:** the system must not assume every merchant supports every intervention. `A1`–`A3` are individually toggleable per merchant in policy configuration (TRD.md §Configuration Variables / policy tooling); LinUCB's `allowed_actions` set is derived from that configuration on every request, not hardcoded.

## 6. Manual Override

- **Authorized role:** Risk Officer or Admin (Operations Lead is read-only per §1 above).
- **Required fields:** `override_reason` (non-empty), `operator_id`, `previous_decision_id`, `new_action`.
- **Behavior:** Creates a new `policy_decisions` row referencing the original `risk_decisions.id`; the original row is never updated or deleted (ADR-012). The dashboard and API always resolve the "current effective decision" as the latest state transition, while the full chain remains queryable for audit.
- **Audit trail:** Every override produces an `audit_events` entry with `event_type=MANUAL_OVERRIDE`, including `operator_id`, `timestamp`, `previous_decision`, `new_decision`, and `override_reason`.

## 7. Fairness and Customer Friction

The system must monitor, on a rolling basis: false-positive rate, intervention rate, manual-review rate, approval rate, and return-approval latency. Where cohort-level aggregate monitoring is operationally and legally appropriate, it is done using privacy-safe aggregates only (no individual-level profiling by protected characteristics, and no protected characteristics as features at all — SPEC.md §7). The design rationale: return-abuse risk should be predicted from transaction and behavioral evidence directly relevant to the abuse taxonomy (SPEC.md §4), not from demographic proxies, both because protected-attribute profiling is prohibited outright and because behavioral evidence is more directly causal to the outcome being predicted.

## 8. Demo Scenarios (Product View)

See ROADMAP.md's demo-scenario table for the technical sequencing. From a product perspective, each scenario demonstrates a specific promise made to a specific persona:

| Scenario | Persona promise demonstrated |
|---|---|
| A — legitimate low-risk customer | To the Legitimate Buyer: no unnecessary friction |
| B — suspicious repeated-return customer | To the Risk Officer: risk is caught and priced, not just flagged |
| C — Tier 0 unavailable | To the Operations Lead: the system never simply stops working |
| D — Tier 0+1 unavailable | To the Operations Lead: even total ML outage degrades safely, not silently |
| E — Verifier flags inconsistent evidence | To the Risk Officer: the system self-checks rather than blindly trusting one signal |
| F — manual override | To the Risk Officer: human judgment always has the final word, and it's fully auditable |
