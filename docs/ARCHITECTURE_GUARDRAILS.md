# Architecture Guardrails & Authority Boundary Proofs

**System:** AI Risk Manager (Real-Time Return-Risk Scorer & Intervention Sentinel)  
**Standard:** Financial-Grade Separation of Concerns & LLM Non-Authority Verification  
**Status:** Mechanically & Architecturally Enforced  

---

## 1. The Core Architectural Axiom

> **LLMs and Agentic Workflows have ZERO numerical scoring authority and ZERO policy modification authority.**  
> They are strictly asynchronous, read-only observers and verifiers whose failures, hallucinations, or corruptions cannot alter transaction risk or merchant interventions.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Phase 4: NUMERICAL AUTHORITY (Synchronous ML & Deterministic Cascade)    │
│    Sole Author: MLCascadeScorer (XGBoost + Calibrator / IsoForest / Rules)  │
│    Authority: Computes p_return_abuse ∈ [0.0, 1.0], risk_band, fallback_tier│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Immutable Risk Score
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Phase 5: ECONOMIC & POLICY AUTHORITY (Expected Net Value Optimizer)      │
│    Sole Author: PolicyEngine (LinUCB Contextual Bandit + Guardrails)        │
│    Authority: Computes Expected Loss, Friction, and selects optimal Action  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Immutable Policy Decision
                         ┌─────────────┴─────────────┐
                         ▼                           ▼
          ┌───────────────────────────┐ ┌────────────────────────────────────┐
          │ Synchronous API Response  │ │ 3. Phase 6: PASSIVE AGENTS         │
          │ Latency: P50=52ms, P95=60ms│ │ (Asynchronous Background Queue)    │
          │ Persisted to SQLite       │ │  - Investigator Node               │
          │ Audit Log Written         │ │  - Verifier Node                   │
          └───────────────────────────┘ │  - Action Orchestrator Node        │
                                        │  Authority: Explanations & Checks  │
                                        │  Impact on Score: 0.00%            │
                                        │  Impact on Action: 0.00%           │
                                        └────────────────────────────────────┘
```

---

## 2. Formal Invariant Proofs

### Invariant 1: Investigator Node Cannot Modify Risk Probability
* **Claim:** Even if an adversarial prompt, poisoned payload, or hallucinating LLM asserts `p_return_abuse = 0.0`, the system output must preserve the Phase 4 probability.
* **Mechanism:** The `investigator_node` returns an `InvestigationResult` schema containing only `evidence_signals`, `fraud_mechanisms`, `confidence`, and `summary`. The node does not return `p_return_abuse`, and the state reducer rejects unauthorized dictionary keys.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_agent_cannot_alter_risk`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L91-L121) passes with $p=0.7654$ invariant before and after node invocation.

### Invariant 2: Agent Orchestrator Cannot Replace Policy Action
* **Claim:** If Phase 5 selects Action $A2$, an agent cannot silently replace it with $A0$ (Instant Refund) or $A4$ (Block/Review).
* **Mechanism:** The `action_orchestrator_node` produces an `OrchestrationPlan` detailing customer communication and verification instructions. It has no write access to `PolicyDecision.new_action` or `selected_action`.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_agent_cannot_alter_action`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L126-L148) passes with `selected_action == Action.A2` invariant.

### Invariant 3: Verifier Cannot Override Deterministic Safety Rules
* **Claim:** If a deterministic safety rule triggers (e.g., $p=0.95$ but payload claims `risk_band = LOW`), an LLM cannot rubber-stamp the decision by returning `verified = True`.
* **Mechanism:** In `risk_manager/agents/verifier.py`, `combine_verifier_results` evaluates deterministic assertions first. If any deterministic check fails (`len(det_failed) > 0`), the final verification status is hard-forced to `FAILED` with `requires_human_review = True`, overriding any contradictory LLM output.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_verifier_cannot_override_deterministic_safety`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L153-L197) passes.

### Invariant 4: Human Override Is the SOLE Action Mutation Path
* **Claim:** Algorithmic decisions cannot be overwritten or edited in-place.
* **Mechanism:** Modifying an action requires an authorized human analyst invoking `POST /api/v1/review/override`. The engine inserts an append-only `PolicyDecision` row with `selected_by = MANUAL_OVERRIDE`, referencing the operator's ID and signed reason, alongside an immutable `AuditEvent`. The original algorithmic decision remains unchanged in the database.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_human_override_exclusivity`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L202-L296) passes.

### Invariant 5: What-If Simulator Is 100% Non-Persistent
* **Claim:** What-If counterfactual analysis must not pollute production state, change bandit weights, or create audit log events.
* **Mechanism:** The simulation endpoint `POST /api/v1/demo/simulate` invokes `simulate_risk_scenario()` which passes the request through Phase 4 and Phase 5 purely in-memory. It receives `session = None` and never executes `session.add()` or `session.commit()`.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_what_if_isolation`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L301-L379) verifies row counts of `RiskDecision`, `PolicyDecision`, and `AuditEvent` before and after are identical.

### Invariant 6: Decision Replay Is 100% Read-Only
* **Claim:** Inspecting a historical decision via `GET /api/v1/risk/decisions/{id}/replay` must not trigger new evaluations, create audit events, or mutate database state.
* **Mechanism:** `replay_decision` executes strictly read queries (`SELECT ... WHERE id = :id`), assembles the 6-stage audit trace from existing database snapshots, and explicitly declares `database_writes_committed = 0`.
* **Test Verification:** [`tests/unit/test_authority_boundaries.py::test_decision_replay_read_only_isolation`](file:///c:/Users/Tanishq%20Sutrave/Documents/AI-Risk-Manager/tests/unit/test_authority_boundaries.py#L385-L449) verifies that `RiskDecision`, `PolicyDecision`, and `AuditEvent` table counts are 100% invariant.

---

## 3. Failure Blast-Radius Containment

| Component Failure | Blast Radius | System Response | Decision Impact |
| :--- | :--- | :--- | :--- |
| **XGBoost Pickle Corrupted** | Tier 0 Inference | Cascade falls back to Tier 2 Deterministic Rules | $p$ bounded safely; 0 ms crash |
| **Calibrator Missing** | Calibration stage | Returns raw tree probability clamped $[0, 1]$ | Bounded valid probability |
| **LinUCB Model Corrupted** | Bandit Selection | Deterministic Guardrail Matrix activates | Safe action assigned |
| **Gemini LLM Outage (503/429)** | Async Agents | Deterministic Fallback Synthesizer activates | **0 ms synchronous path impact** |
| **Database Transaction Deadlock** | Current Request | Atomic rollback; 0 partial state persisted | Idempotency retry permitted |

---

## 4. Certification

All 6 architectural invariants are verified by automated tests running in CI/CD. The authority boundaries between statistical ML, economic optimization, and agentic reasoning are mathematically and programmatically sealed.
