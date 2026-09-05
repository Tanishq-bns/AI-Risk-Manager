# ROADMAP.md — Execution Plan

**Document status:** Planned execution roadmap. No repository exists yet — Phase 0 below reflects that starting state explicitly rather than assuming a prior codebase. See SUMMARY.md for live status tracking once implementation begins.

---

## Phase 0 — Repository Audit / Project Bootstrap Decision

- **Objective:** Confirm there is no pre-existing codebase to reconcile against, and establish the repository as a greenfield project against this documentation set.
- **Prerequisites:** None.
- **Concrete outputs:** Empty repository initialized with the package layout defined in TRD.md §Python Package Structure; this documentation set (`SPEC.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `STATE.md`, `PLAN.md`, `SUMMARY.md`, `PRD.md`, `TRD.md`) committed at the repository root under `/docs`.
- **Files/subsystems affected:** Repository root, `/docs`.
- **Verification criteria:** Repository exists with the documented directory skeleton; `README.md` links to all eight documents.
- **Demo impact:** None directly; unblocks all subsequent phases.
- **Failure risks:** None specific to this phase.

## Phase 1 — Environment / Bootstrap

- **Objective:** Establish a reproducible local/dev environment for FastAPI, PostgreSQL, Redis, and Redpanda.
- **Prerequisites:** Phase 0.
- **Concrete outputs:** `docker-compose.yml` (or equivalent) bringing up PostgreSQL, Redis, Redpanda locally; `pyproject.toml`/`requirements.txt` pinning FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, XGBoost, scikit-learn (Isotonic + Isolation Forest + Random Forest), LangGraph, LangChain, MLflow client, Prometheus client, LangSmith client; `.env.example` covering configuration keys from TRD.md §Configuration Variables.
- **Files/subsystems affected:** Repo root, `infra/`, `pyproject.toml`.
- **Verification criteria:** `docker compose up` brings up all four services and a health-check script confirms each is reachable.
- **Demo impact:** Enables local development; no user-visible demo impact.
- **Failure risks:** Version incompatibilities between async SQLAlchemy, Pydantic v2, and LangChain/LangGraph pinned versions.

## Phase 2 — Database and Schemas

- **Objective:** Implement the SQLAlchemy models and initial Alembic migration for all entities in TRD.md §PostgreSQL Schema.
- **Prerequisites:** Phase 1.
- **Concrete outputs:** `db/models.py` (or per-entity modules), initial Alembic migration creating `customers`, `orders`, `return_requests`, `risk_decisions`, `risk_features`, `interventions`, `agent_runs`, `model_versions`, `policy_decisions`, `audit_events`.
- **Files/subsystems affected:** `db/`, `alembic/versions/`.
- **Verification criteria:** `alembic upgrade head` succeeds against a clean database; all foreign keys, indexes, and enums from TRD.md are present and verified via a schema-introspection test.
- **Demo impact:** Foundational; no direct demo impact yet.
- **Failure risks:** Schema drift against TRD.md if not kept in lockstep — mitigated by treating TRD.md as source of truth and generating models from it, not vice versa.

## Phase 3 — Event Streaming

- **Objective:** Implement Redpanda producers/consumers for the six topics in TRD.md §Streaming Event Contracts.
- **Prerequisites:** Phase 1.
- **Concrete outputs:** `streaming/producers.py`, `streaming/consumers.py`, topic-provisioning script, common event-envelope Pydantic model shared across all topics.
- **Files/subsystems affected:** `streaming/`.
- **Verification criteria:** A test producer publishes a `return.events.v1` event and a test consumer receives and schema-validates it; malformed payloads are rejected and routed to a dead-letter mechanism.
- **Demo impact:** Enables the event-driven demo path (Scenario A–F feed via events).
- **Failure risks:** Partition-key/ordering assumptions not holding under concurrent producers — mitigated by keying on `entity_id` (return_request_id) to guarantee per-entity ordering.

## Phase 4 — Feature Pipeline

- **Objective:** Implement feature retrieval producing the `FeatureVector` defined in TRD.md §ML Feature Schema, using the dataset fields in TRD.md §Dataset Design.
- **Prerequisites:** Phase 2, Phase 3.
- **Concrete outputs:** `features/pipeline.py` computing behavioral aggregates (`customer_return_rate`, `customer_return_count`, `item_category_return_rate`, etc.) from `orders`/`return_requests`, with an explicit "available at decision time" vs. "post-outcome label" separation enforced by a schema-level split (`FeatureVector` vs. `OutcomeLabel`).
- **Files/subsystems affected:** `features/`.
- **Verification criteria:** A leakage-detection unit test asserts that no field present in `OutcomeLabel` is reachable from `FeatureVector` construction code.
- **Demo impact:** Required for any risk scoring to function.
- **Failure risks:** Accidental leakage via joins that pull post-decision state (e.g., refund-completion timestamp) — explicitly tested against in Phase 4 verification.

## Phase 5 — XGBoost Model

- **Objective:** Train the primary XGBoost classifier on the temporal train split.
- **Prerequisites:** Phase 4 (feature pipeline and a labeled/synthetic dataset).
- **Concrete outputs:** `ml/xgboost_model/train.py`, MLflow-logged experiment run with `xgboost_model` artifact, `feature_schema`, `training_metadata`.
- **Files/subsystems affected:** `ml/xgboost_model/`.
- **Verification criteria:** Model trains end-to-end on the synthetic dataset (TRD.md §Dataset Design) and produces a raw score for a held-out example without error.
- **Demo impact:** Core scoring capability.
- **Failure risks:** Class imbalance causing degenerate predictions — mitigated with class weighting / scale_pos_weight tuning, verified against PR-AUC on validation.

## Phase 6 — Calibration

- **Objective:** Fit Isotonic Regression on a calibration split disjoint from train/test; wrap the XGBoost model + calibrator into a single inference artifact.
- **Prerequisites:** Phase 5.
- **Concrete outputs:** `ml/calibration/isotonic.py`, `isotonic_calibrator` MLflow artifact, reliability-diagram generation script, Brier-score computation in the evaluation report.
- **Files/subsystems affected:** `ml/calibration/`.
- **Verification criteria:** Brier score computed on held-out test set is reported (not asserted against a fixed pass/fail bar pre-labels — see SPEC.md §44/NO_HALLUCINATED_METRICS equivalent); reliability diagram is generated as an artifact.
- **Demo impact:** Required for `p_return_abuse` to be interpretable as a true probability by the economic layer.
- **Failure risks:** Insufficient calibration-set volume producing an unstable isotonic map — documented reconsideration path to Platt scaling if calibration-set size is small.

## Phase 7 — Fallback Cascade

- **Objective:** Implement Tier 1 (Isolation Forest) and Tier 2 (Rules Engine), and the orchestration logic that selects a tier based on the trigger conditions in TRD.md §Fallback Configuration.
- **Prerequisites:** Phase 5, Phase 6.
- **Concrete outputs:** `ml/isolation_forest/model.py`, `ml/rules_engine/rules.py`, `ml/cascade.py` (tier-selection orchestrator with circuit breaker).
- **Files/subsystems affected:** `ml/isolation_forest/`, `ml/rules_engine/`, `ml/cascade.py`.
- **Verification criteria:** Mandatory fallback tests from TRD.md §Testing (Tier 0 unavailable → Tier 1; Tier 0+1 unavailable → Tier 2) pass under fault injection.
- **Demo impact:** Powers Demo Scenarios C and D (ROADMAP §17 below).
- **Failure risks:** Rules Engine (Tier 2) being *less* conservative than intended — mitigated by an explicit design rule that Tier 2 thresholds are set to bias toward MEDIUM/HIGH rather than LOW when uncertain (ARCHITECTURE.md §Fallback Flow).

## Phase 8 — Reward Model

- **Objective:** Train the Random Forest Regressor predicting economic outcome per TRD.md §Reward Model Contract.
- **Prerequisites:** Phase 4, Phase 5.
- **Concrete outputs:** `ml/reward_model/train.py`, MLflow-logged `rf_reward_model` artifact.
- **Files/subsystems affected:** `ml/reward_model/`.
- **Verification criteria:** Given a synthetic feature vector, the model returns `expected_loss`, `expected_margin_saved`, `expected_net_value` fields with no leakage from post-decision outcome fields (same leakage-test pattern as Phase 4).
- **Demo impact:** Powers the economic-impact display in the demo.
- **Failure risks:** Reward mis-specification (predicting a quantity that doesn't match the `ExpectedNetValue` formula in SPEC.md §14) — mitigated by unit-testing the formula against the model's component outputs.

## Phase 9 — LinUCB Policy

- **Objective:** Implement LinUCB contextual bandit for intervention selection, constrained to merchant-allowed actions.
- **Prerequisites:** Phase 8.
- **Concrete outputs:** `ml/bandit/linucb.py`, offline policy-evaluation script using rejection sampling.
- **Files/subsystems affected:** `ml/bandit/`.
- **Verification criteria:** Given a context vector and an allowed-action subset, LinUCB never returns an action outside that subset (policy-constraint test); offline evaluation report generated (not claimed as a production result).
- **Demo impact:** Determines which of A0–A4 is selected in each demo scenario.
- **Failure risks:** Unconstrained exploration in a live setting — mitigated by `LINUCB_ALPHA` bound and hard policy-constraint filtering applied before, not after, action selection.

## Phase 10 — LangGraph Agents

- **Objective:** Implement the Investigator → Verifier → Action Orchestrator graph with Gemini structured outputs.
- **Prerequisites:** Phase 2 (for persistence), Phase 9 (for action context).
- **Concrete outputs:** `agents/graph.py`, `agents/investigator.py`, `agents/verifier.py`, `agents/orchestrator.py`, Pydantic output contracts (`InvestigationResult`, `VerificationResult`, `ActionDecision`) per TRD.md §Agent State Schema.
- **Files/subsystems affected:** `agents/`.
- **Verification criteria:** Given a HIGH-band decision, the graph runs asynchronously, produces structured (not free-text) output, and never overrides the already-persisted synchronous decision's numeric fields.
- **Demo impact:** Powers Demo Scenario E (verifier detects inconsistent evidence → manual review).
- **Failure risks:** Prompt-injection via return-reason free text — mitigated per §50 of the master prompt (all customer text treated as data, never as instruction; tool access allowlisted).

## Phase 11 — FastAPI Integration

- **Objective:** Wire the full synchronous decision path behind the API endpoints in TRD.md §API Contracts.
- **Prerequisites:** Phases 2–9.
- **Concrete outputs:** `api/routers/risk.py`, `api/routers/health.py`, `api/routers/models.py`, request/response wired to DTOs.
- **Files/subsystems affected:** `api/`.
- **Verification criteria:** `POST /v1/risk/score` returns a schema-valid `RiskScoreResponse` within the latency budget (SPEC.md §12) for a representative synthetic payload.
- **Demo impact:** This is the core demo-facing surface.
- **Failure risks:** Accidentally placing agent invocation on the synchronous path — mitigated by an integration test asserting the endpoint returns before the agent task completes (background-task pattern).

## Phase 12 — Redis / Cache

- **Objective:** Implement the Redis cache layer with in-process LRU fallback per ARCHITECTURE.md §Cache Flow.
- **Prerequisites:** Phase 11.
- **Concrete outputs:** `cache/redis_client.py`, `cache/lru_fallback.py`, unified `cache/interface.py`.
- **Files/subsystems affected:** `cache/`.
- **Verification criteria:** Fault-injection test (Redis connection refused) confirms automatic fallback to LRU with no request failure.
- **Demo impact:** Powers response-time improvement in the demo; cache-bypass-on-override is directly testable.
- **Failure risks:** Stale cached decisions after a manual override — mitigated by explicit cache invalidation on override (TRD.md §Redis Key Contracts).

## Phase 13 — Frontend Dashboard

- **Objective:** Build the HTML5/CSS3/vanilla JS risk dashboard, risk inspector, and manual-override portal.
- **Prerequisites:** Phase 11.
- **Concrete outputs:** `frontend/index.html` (dashboard), `frontend/inspector.html` (decision detail + evidence + explanation), `frontend/override.html` (override portal), calling the documented API only.
- **Files/subsystems affected:** `frontend/`.
- **Verification criteria:** Dashboard renders live decisions from `/v1/risk/decisions/{decision_id}`; override portal successfully calls `POST /v1/risk/decisions/{decision_id}/override` and reflects the new state without deleting the original decision.
- **Demo impact:** Primary visual surface for all six demo scenarios.
- **Failure risks:** None ML-specific; standard frontend integration risk.

## Phase 14 — Observability

- **Objective:** Instrument Prometheus metrics (TRD.md §Prometheus Metrics) and Grafana dashboards; wire LangSmith tracing for the agent graph.
- **Prerequisites:** Phases 5–11.
- **Concrete outputs:** `observability/metrics.py`, Grafana dashboard JSON exports (system health, inference performance, model performance, risk distribution, intervention distribution, fallback behavior, economic impact, customer-friction indicators).
- **Files/subsystems affected:** `observability/`.
- **Verification criteria:** All metric names in TRD.md §Prometheus Metrics are emitted and visible on `/metrics`; a Prometheus-down fault-injection test confirms no impact on `/v1/risk/score`.
- **Demo impact:** Supports the "show latency and audit trail" requirement of the demo.
- **Failure risks:** Metric cardinality explosion from unbounded labels (e.g., raw customer ID as a label) — mitigated by using only bounded-cardinality labels (band, fallback_tier, action, model_version).

## Phase 15 — Testing

- **Objective:** Implement the full test suite in TRD.md §Testing Requirements, including all 12 mandatory failure-injection tests.
- **Prerequisites:** All prior phases.
- **Concrete outputs:** `tests/unit/`, `tests/integration/`, `tests/contract/`, `tests/e2e/`.
- **Files/subsystems affected:** `tests/`.
- **Verification criteria:** All 12 mandatory tests (TRD.md §39) pass in CI.
- **Demo impact:** Confidence for live demo; reduces risk of an on-stage failure.
- **Failure risks:** Flaky fault-injection tests against real external services — mitigated by using local containers/mocks for Redis, Redpanda, Postgres, and a Gemini mock/stub for deterministic agent tests.

## Phase 16 — End-to-End Demo

- **Objective:** Wire and rehearse the six demo scenarios (§Demo Design below).
- **Prerequisites:** Phases 1–15.
- **Concrete outputs:** `demo/run_scenarios.py` seeding events for Scenarios A–F and a demo script.
- **Files/subsystems affected:** `demo/`.
- **Verification criteria:** All six scenarios run end-to-end against the live stack and are visible on the dashboard with correct band, fallback tier, economic estimate, intervention, and audit trail.
- **Demo impact:** This *is* the demo.
- **Failure risks:** Timing/latency variance live — mitigated by rehearsing with the same synthetic dataset used in testing.

## Phase 17 — Documentation / Final Hardening

- **Objective:** Reconcile this documentation set against the actual implemented repository, updating SUMMARY.md and STATE.md to reflect true implemented-vs-planned status, and hardening error handling/config validation.
- **Prerequisites:** Phase 16.
- **Concrete outputs:** Updated SUMMARY.md, final README, config validation on startup (fail fast on missing required env vars).
- **Files/subsystems affected:** `/docs`, `README.md`, `core/config.py`.
- **Verification criteria:** SUMMARY.md accurately reflects implemented vs. planned status per component, with no remaining "planned" items that are actually implemented or vice versa.
- **Demo impact:** Ensures the submitted documentation is truthful, which is an explicit requirement of the master prompt (§44–45).
- **Failure risks:** Documentation drift under time pressure — mitigated by treating Phase 17 as a mandatory, non-optional gate before submission.

---

## Hackathon Demo Scenarios (referenced by Phase 16)

| Scenario | Setup | Expected outcome |
|---|---|---|
| A | Legitimate, low-risk customer | LOW band → A0 ZERO_FRICTION_APPROVAL, fast synchronous decision |
| B | Suspicious repeated-return customer | HIGH/CRITICAL band → economic-loss estimate shown → defensive intervention (A1–A4) |
| C | Tier 0 model unavailable | Isolation Forest (Tier 1) fallback activates; decision still produced |
| D | Tier 0 + Tier 1 unavailable | Deterministic Rules Engine (Tier 2) fallback; safe, conservative decision |
| E | Agent Verifier detects inconsistent evidence | Case routed to A4 MANUAL_REVIEW |
| F | Manual operator overrides an intervention | Original decision retained in history; override recorded as a new, audited state transition |

Every scenario must visibly show: incoming event, risk score, calibrated probability, risk band, model version, fallback tier, economic impact, selected intervention, explanation, latency, and audit event (master prompt §29).
