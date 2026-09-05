> Relocated from repo root to docs/spec/ on 2026-09-05 for repository organization; content unchanged. Cited throughout the codebase as "TRD.md §X" etc. — see docstrings.

# TRD.md — Technical Requirements

**Document status:** Target technical specification for a system with no current implementation. Every schema, contract, and default value below is the intended design and must be treated as the source of truth that implementation code is written *against* — not descriptions of existing code.

---

## A. System Components

| Component | Responsibility |
|---|---|
| FastAPI service | Synchronous HTTP API: validation, cache orchestration, scoring-cascade invocation, economic estimation, policy selection, persistence, audit publish |
| Feature pipeline | Builds `FeatureVector` from `orders`/`return_requests` at decision time, with leakage prevention |
| ML cascade (Tier 0/1/2) | XGBoost+Isotonic primary scoring, Isolation Forest fallback, Rules Engine final fallback |
| Reward model | Random Forest Regressor estimating economic impact |
| Policy engine (LinUCB) | Constrained intervention selection |
| Agent runtime (LangGraph + Gemini) | Asynchronous investigation, verification, and action-orchestration/enrichment |
| Streaming layer (Redpanda) | Event ingestion and audit/decision fan-out |
| Cache layer (Redis + LRU) | Decision-lookup caching with automatic degraded-mode fallback |
| Persistence layer (PostgreSQL) | System of record for all entities |
| MLOps layer (MLflow) | Model artifact tracking, versioning, promotion |
| Observability layer (Prometheus/Grafana, LangSmith) | Non-critical-path metrics and agent tracing |
| Frontend (HTML5/CSS3/vanilla JS) | Risk dashboard, risk inspector, manual override portal |

## B. Python Package Structure

```
risk_manager/
  api/
    routers/
      risk.py
      health.py
      models.py
  core/
    config.py
    logging.py
    errors.py
  domain/
    schemas/
      events.py
      requests.py
      responses.py
      agents.py
      override.py
  db/
    session.py
    models/
      customer.py
      order.py
      return_request.py
      risk_decision.py
      risk_features.py
      intervention.py
      agent_run.py
      model_version.py
      policy_decision.py
      audit_event.py
  features/
    schema.py
    pipeline.py
    completeness.py
  ml/
    xgboost_model/
    calibration/
    isolation_forest/
    rules_engine/
    reward_model/
    bandit/
    cascade.py
  agents/
    graph.py
    investigator.py
    verifier.py
    orchestrator.py
    security.py
  streaming/
    topics.py
    producers.py
    consumers.py
  cache/
    redis_client.py
    lru_fallback.py
    interface.py
  observability/
    metrics.py
    langsmith.py
  alembic/
    versions/
  frontend/
    index.html
    inspector.html
    override.html
  demo/
    run_scenarios.py
  tests/
    unit/
    integration/
    contract/
    e2e/
```

## C. SQLAlchemy Models (representative definitions)

```python
# db/models/risk_decision.py
class RiskDecision(Base):
    __tablename__ = "risk_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    return_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("return_requests.id"), index=True)
    p_return_abuse: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    risk_band: Mapped[RiskBand] = mapped_column(Enum(RiskBand))
    scoring_source: Mapped[ScoringSource] = mapped_column(Enum(ScoringSource))
    fallback_tier: Mapped[int] = mapped_column(SmallInteger)          # 0, 1, or 2
    fallback_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# db/models/policy_decision.py — append-only state-transition log
class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_decisions.id"), index=True)
    previous_action: Mapped[Action | None] = mapped_column(Enum(Action), nullable=True)
    new_action: Mapped[Action] = mapped_column(Enum(Action))
    selected_by: Mapped[Selector] = mapped_column(Enum(Selector))     # LINUCB / RULES / MANUAL_OVERRIDE
    operator_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # No update()/delete() path exposed at the application-role level — enforced via DB grants.
```

## D. PostgreSQL Schema (entity summary)

| Table | Purpose | Key columns |
|---|---|---|
| `customers` | Pseudonymous customer identity | `customer_id_hash` (PK), `created_at`, `first_seen_at` |
| `orders` | Order records | `id` (PK), `customer_id_hash` (FK), `order_value` numeric(12,2), `payment_method` enum, `cod_flag` bool |
| `return_requests` | Return requests | `id` (PK), `order_id` (FK), `return_reason` text, `requested_at`, `status` enum |
| `risk_decisions` | Scored decisions | `id` (PK), `return_request_id` (FK), `p_return_abuse` numeric(5,4), `risk_band` enum, `scoring_source` enum, `fallback_tier` smallint, `model_version_id` (FK) |
| `risk_features` | Feature snapshot at decision time | `id` (PK), `risk_decision_id` (FK), `features` JSONB, `feature_schema_version` |
| `interventions` | Selected action per decision | `id` (PK), `risk_decision_id` (FK), `action` enum (A0-A4), `expected_net_value` numeric(12,2) |
| `agent_runs` | Async agent execution log | `id` (PK), `risk_decision_id` (FK), `agent_name` enum, `output` JSONB, `status` enum |
| `model_versions` | Model registry mirror | `id` (PK), `mlflow_run_id`, `model_type` enum, `approval_status` enum, `promoted_at` |
| `policy_decisions` | Append-only decision/override history | `id` (PK), `risk_decision_id` (FK), `previous_action`, `new_action`, `selected_by` enum, `operator_id` nullable, `reason` nullable |
| `audit_events` | Full audit-event log (mirror of `risk.audit.v1`) | `id` (PK), `event_id` unique, `event_type`, `payload` JSONB, `occurred_at` |

Indexes: FK columns and `created_at`/`occurred_at`/`requested_at` on every table with time-range dashboard queries. Unique constraint: `audit_events.event_id`. Numeric precision: all monetary fields `numeric(12,2)` (INR, paise-safe); probabilities `numeric(5,4)`. No raw PII columns anywhere — `customer_id_hash` is the only customer identifier stored.

## E. Pydantic v2 DTOs

```python
class CheckoutEvent(BaseModel):
    order_id: UUID
    customer_id_hash: str
    order_value: float = Field(gt=0)
    payment_method: Literal["PREPAID", "COD"]
    cod_flag: bool
    occurred_at: datetime

class ReturnRequestEvent(BaseModel):
    return_request_id: UUID
    order_id: UUID
    return_reason: str
    requested_at: datetime

class RiskScoreRequest(BaseModel):
    return_request_id: UUID
    order_id: UUID
    customer_id_hash: str
    idempotency_key: str

class RiskScoreResponse(BaseModel):
    decision_id: UUID
    p_return_abuse: float = Field(ge=0, le=1)
    risk_band: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    model_metadata: ModelMetadata
    fallback_metadata: FallbackMetadata
    economic_prediction: EconomicPrediction
    intervention: InterventionCandidate
    evidence: RiskEvidence
    latency_ms: float
    persistence_status: Literal["PERSISTED", "DEFERRED"]

class RiskEvidence(BaseModel):
    top_signals: list[str]           # e.g. ["elevated customer_return_rate", "high-value item"]
    feature_completeness: float = Field(ge=0, le=1)

class ModelMetadata(BaseModel):
    model_version: str
    model_type: Literal["XGBOOST", "ISOLATION_FOREST", "RULES"]
    trained_at: datetime | None

class FallbackMetadata(BaseModel):
    fallback_tier: Literal[0, 1, 2]
    fallback_reason: str | None      # null when Tier 0 succeeded

class EconomicPrediction(BaseModel):
    expected_loss_no_action: float
    expected_loss_with_action: float
    expected_net_value: float

class InterventionCandidate(BaseModel):
    action: Literal["A0", "A1", "A2", "A3", "A4"]
    selected_by: Literal["LINUCB", "RULES", "MANUAL_OVERRIDE"]
    rationale: str

class PolicyDecision(BaseModel):
    previous_action: str | None
    new_action: str
    selected_by: str
    operator_id: str | None
    reason: str | None
    created_at: datetime

class AgentVerificationResult(BaseModel):
    case_id: UUID
    verified: bool
    contradictions: list[str]
    missing_evidence: list[str]
    verifier_confidence: float = Field(ge=0, le=1)
    recommendation: Literal["CONFIRM", "MANUAL_REVIEW"]

class ManualOverrideRequest(BaseModel):
    operator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    new_action: Literal["A0", "A1", "A2", "A3", "A4"]

class ManualOverrideResponse(BaseModel):
    decision_id: UUID
    previous_action: str
    new_action: str
    overridden_at: datetime
    audit_event_id: UUID
```

## F. Redpanda Event Schemas

Common envelope, shared by all topics:

```json
{
  "event_id": "8f14e45f-ceea-467e-b73c-3e9c8f9d1a2b",
  "event_type": "RETURN_REQUEST_CREATED",
  "event_version": "v1",
  "occurred_at": "2026-09-04T10:15:00Z",
  "producer": "returns-service",
  "correlation_id": "corr-9c1e",
  "entity_id": "return_request_id:5b2f...",
  "payload": { "...": "..." }
}
```

| Topic | Key | Producer | Consumer(s) | Partitions | Ordering | Notes |
|---|---|---|---|---|---|---|
| `checkout.events.v1` | `entity_id` = order_id | Merchant checkout system | Feature pipeline | 3 | Per-`entity_id` order preserved | Feeds behavioral aggregates, not scored directly |
| `return.events.v1` | `entity_id` = return_request_id | Merchant returns system | FastAPI ingestion | 3 | Per-`entity_id` order preserved | Triggers synchronous scoring |
| `risk.decisions.v1` | `entity_id` = return_request_id | FastAPI service | Dashboard, downstream analytics | 3 | Per-`entity_id` order preserved | One event per decision (including override transitions) |
| `interventions.decisions.v1` | `entity_id` = risk_decision_id | FastAPI service | Ops tooling, dashboard | 3 | Per-`entity_id` order preserved | Emitted whenever an intervention is selected or overridden |
| `risk.audit.v1` | `entity_id` = risk_decision_id | FastAPI service, agent runtime | Audit store consumer (`audit_events` table) | 3 | Per-`entity_id` order preserved | Superset audit stream; every state transition lands here |
| `model.events.v1` | `entity_id` = model_version_id | MLOps pipeline | FastAPI service (cache-bust active model) | 3 | Per-`entity_id` order preserved | Promotion/rollback notifications |

Idempotency: consumers deduplicate on `event_id` using a bounded seen-set (Redis-backed with local fallback, same pattern as the decision cache). Retry: consumer-side processing failures use bounded exponential backoff (max 5 attempts) before routing to `<topic>.dlq`. Schema versioning: `event_version` is part of the envelope; a consumer encountering an unrecognized `event_version` routes the message to the DLQ rather than attempting best-effort parsing.

## G. Redis Key Contracts

| Key pattern | Value | TTL | Notes |
|---|---|---|---|
| `risk_decision:{return_request_id}` | Serialized `RiskScoreResponse` (JSON) | `REDIS_TTL_SECONDS` (300s) | Deleted (not just expired) on manual override for the same `return_request_id` |
| `event_seen:{event_id}` | `1` | 3600s | Idempotency dedup set for stream consumers |
| `active_model:{model_type}` | Model version string | No TTL, invalidated on `model.events.v1` promotion event | Read on every Tier 0/1 scoring call to confirm the loaded artifact is current |

Serialization: JSON (UTF-8). Cache stampede protection: a short-lived per-key lock (`SET NX PX 50`) around cache-miss recomputation to avoid thundering-herd re-scoring on a hot `return_request_id`. Negative caching: not used — a cache miss always triggers a full scoring pass rather than caching "no decision yet," since decisions are cheap to recompute and staleness risk outweighs the marginal latency saving.

## H. ML Feature Schema

`FeatureVector` (available at decision time):

| Field | Type | Description |
|---|---|---|
| `customer_id_hash` | str | Pseudonymous identifier |
| `order_value` | float | Value of the order being returned |
| `product_category` | str | Category enum |
| `payment_method` | enum | PREPAID / COD |
| `cod_flag` | bool | |
| `customer_order_count` | int | Total historical orders, strictly before this request |
| `customer_return_count` | int | Total historical returns, strictly before this request |
| `customer_return_rate` | float | `customer_return_count / customer_order_count`, guarded against divide-by-zero |
| `days_since_purchase` | int | Days between order and return request |
| `prior_return_value` | float | Sum of prior returned-order value |
| `prior_return_frequency` | float | Returns per unit time over the customer's history |
| `item_category_return_rate` | float | Category-level historical return rate (aggregate, not customer-specific) |
| `return_reason` | str | Free text — passed to agents as data only, never used as a raw model feature without prior structured encoding |
| `delivery_distance_bucket` | enum | Bucketed courier-zone distance |
| `reverse_logistics_cost` | float | Estimated cost to process this specific return |
| `estimated_item_recovery_value` | float | Expected resale/restock value if returned item is undamaged |
| `historical_abuse_signal` | float | Aggregate prior-flag signal for this customer, strictly pre-decision |
| `feature_schema_version` | str | Versioning field |

`OutcomeLabel` (available only after outcome, used for training — never for inference):

| Field | Type | Description |
|---|---|---|
| `confirmed_abuse` | bool | Ground-truth label, determined post-inspection/post-refund-cycle |
| `actual_loss` | float | Realized financial loss, if any |
| `refund_completed_at` | datetime | Post-decision timestamp |

`FeatureVector` and `OutcomeLabel` share zero field names by construction (enforced by PLAN.md task `T-FEAT-01`).

## I. Model Artifact Contract (MLflow)

| Artifact | Description |
|---|---|
| `xgboost_model` | Trained booster |
| `isotonic_calibrator` | Fitted `IsotonicRegression` |
| `feature_schema` | Serialized `FeatureVector` JSON schema, used to validate compatibility at load time |
| `feature_metadata` | Feature statistics from training (for drift comparison) |
| `training_metadata` | Training-run parameters, data window, git commit (once implemented) |
| `metrics.json` | PR-AUC, ROC-AUC, precision, recall, F1, confusion matrix, Brier score, ECE, FPR, FNR — the single artifact where actual benchmark numbers live once computed |
| `threshold_config.json` | Risk-band thresholds active at training time |
| `model_signature` | Input/output schema signature for load-time validation |
| environment spec | Pinned dependency versions for reproducible inference |

**Loading behavior:** on service startup and on `model.events.v1` promotion events, the service attempts to load the artifact whose `feature_schema` is compatible with the current runtime `FeatureVector` schema version. If incompatible or missing, the load fails closed for Tier 0 only (falls to Tier 1), never silently serves a stale or mismatched model. **Version pinning:** the currently-active `model_version_id` is cached in Redis (`active_model:{model_type}`) and re-validated on every N-th request (configurable) to catch drift between cache and registry. **Promotion criteria:** per §L below (Model Governance), never a single-metric gate.

## J. Model Thresholds

| Threshold | Value | Type |
|---|---|---|
| Risk band LOW upper bound | 0.25 | Policy threshold |
| Risk band MEDIUM upper bound | 0.60 | Policy threshold |
| Risk band HIGH upper bound | 0.85 | Policy threshold |
| PR-AUC promotion gate (initial) | ≥ 0.65 | Model (offline evaluation) threshold — target, not achieved value |
| Brier score promotion gate | ≤ 0.15 | Model threshold — target |
| High-risk-band precision gate | ≥ 0.75 | Model threshold — target |
| High-risk-band recall gate | ≥ 0.60 | Model threshold — target |

## K. Fallback Configuration

| Trigger | Detected via | Action |
|---|---|---|
| Model artifact load failure | Exception on MLflow artifact fetch/deserialize | Tier 0 → Tier 1 |
| Feature schema mismatch | `feature_schema` signature check at load time | Tier 0 → Tier 1 |
| Unsupported model version | `model_version` not in supported-version allowlist | Tier 0 → Tier 1 |
| Inference timeout | Call exceeds `MODEL_INFERENCE_TIMEOUT_MS` (100ms) | Tier 0 → Tier 1 |
| Insufficient feature completeness | `feature_completeness_ratio` below `FEATURE_COMPLETENESS_MIN_RATIO` (0.85) | Tier 0 → Tier 1, or Tier 1 → Tier 2 if the same condition affects Isolation Forest's required fields |
| Circuit breaker open | `CIRCUIT_BREAKER_FAILURE_THRESHOLD` (5) consecutive failures within `CIRCUIT_BREAKER_OPEN_SECONDS` (30s) window | Tier 0 bypassed entirely until breaker half-opens |
| Cold start | No model artifact loaded yet at service startup | Serve Tier 1/Tier 2 until first successful Tier 0 load |

Every decision records `scoring_source`, `model_version`, `fallback_tier`, `fallback_reason` (null if Tier 0 succeeded), satisfying the "never silently fail" requirement.

## L. API Contracts

| Method | Path | Request | Response | Status codes |
|---|---|---|---|---|
| POST | `/v1/risk/score` | `RiskScoreRequest` | `RiskScoreResponse` | 200, 400 (validation), 409 (duplicate idempotency key with conflicting payload), 500 |
| POST | `/v1/returns/score` | `ReturnRequestEvent` (alias entrypoint for return-flow-native callers) | `RiskScoreResponse` | 200, 400, 500 |
| GET | `/v1/risk/decisions/{decision_id}` | — | Current-effective `RiskScoreResponse` + `PolicyDecision` chain | 200, 404 |
| POST | `/v1/risk/decisions/{decision_id}/override` | `ManualOverrideRequest` | `ManualOverrideResponse` | 200, 400, 404, 403 (unauthorized role) |
| GET | `/v1/risk/health` | — | Per-dependency health payload | 200 (always, even degraded) |
| GET | `/v1/models/active` | — | `ModelMetadata` per model type | 200 |

**Idempotency:** `POST /v1/risk/score` requires `idempotency_key`; a repeated key with an identical payload returns the original cached response; a repeated key with a *different* payload returns 409. **Authentication:** bearer-token auth assumed, role claims (`RISK_OFFICER`, `OPERATIONS_LEAD`, `ADMIN`) checked per-endpoint (override requires `RISK_OFFICER` or `ADMIN`). **Failure behavior:** `/v1/risk/score` degrades through the fallback cascade rather than returning 5xx for ML-layer failures; only genuine request-validation or total-infrastructure failures return non-200.

## M. Agent State Schema

```python
class InvestigationResult(BaseModel):
    case_id: UUID
    evidence: list[str]
    evidence_quality: Literal["HIGH", "MEDIUM", "LOW"]
    anomalies: list[str]
    investigator_confidence: float = Field(ge=0, le=1)

class VerificationResult(BaseModel):
    case_id: UUID
    verified: bool
    contradictions: list[str]
    missing_evidence: list[str]
    verifier_confidence: float = Field(ge=0, le=1)
    recommendation: Literal["CONFIRM", "MANUAL_REVIEW"]

class ActionDecision(BaseModel):
    action: Literal["A0", "A1", "A2", "A3", "A4"]
    rationale: str
    expected_net_value: float
    policy_constraints_satisfied: bool
    requires_manual_review: bool
```

All three are bound as Gemini structured outputs (`response_schema`); agents never return free-form text as an authoritative object. `expected_net_value` in `ActionDecision` must equal the value already computed by the Reward Model/LinUCB path — the Action Orchestrator confirms or escalates, it does not recompute or invent this number.

## N. LinUCB Context Vector

| Feature | Source |
|---|---|
| `p_return_abuse` | Tier 0/1/2 scoring output |
| `order_value_normalized` | From `FeatureVector.order_value`, normalized |
| `customer_return_rate` | From `FeatureVector` |
| `expected_loss_no_action` | From Reward Model |
| `reverse_logistics_cost_normalized` | From `FeatureVector` |
| `category_one_hot` | Bounded, pre-defined category set from `FeatureVector.product_category` |
| `fallback_tier` | 0/1/2, included so the policy can learn to be more conservative under degraded scoring |

Action space: `{A0, A1, A2, A3, A4}`, filtered to `allowed_actions` (merchant policy config) before scoring. `LINUCB_ALPHA = 0.25` (exploration parameter, configuration variable).

## O. Reward Model Contract

- **Input:** `FeatureVector` fields + `p_return_abuse` + candidate `action`.
- **Output:** `expected_loss`, `expected_margin_saved`, `expected_net_value` (derived per the SPEC.md §14 formula, with the Random Forest predicting the loss/margin components rather than short-circuiting the formula — see ADR-006).
- **Training labels:** `actual_loss` from `OutcomeLabel`, joined only for rows where `refund_completed_at` is populated (i.e., outcome is known), with a temporal split identical in structure to the XGBoost training split.

## P. Prometheus Metrics

```
risk_inference_requests_total{model_type}
risk_inference_latency_seconds{model_type}
risk_model_errors_total{model_type, error_type}
risk_fallback_total{from_tier, to_tier, reason}
risk_cache_hits_total
risk_cache_misses_total
risk_decisions_total{risk_band}
risk_decisions_by_band_total{risk_band}
intervention_decisions_total{action}
manual_review_total{trigger_reason}
agent_execution_total{agent_name, status}
agent_execution_latency_seconds{agent_name}
policy_decision_latency_seconds
event_processing_lag{topic}
model_drift_psi{feature_name}
feature_missingness_ratio{feature_name}
calibration_brier_score{model_version}
false_positive_estimate_total{risk_band}
```

All labels are bounded-cardinality (enum values, model/version identifiers, topic names) — never raw customer or order identifiers.

## Q. Configuration Variables

```
RISK_MEDIUM_THRESHOLD=0.25
RISK_HIGH_THRESHOLD=0.60
RISK_CRITICAL_THRESHOLD=0.85
MODEL_INFERENCE_TIMEOUT_MS=100
REDIS_TTL_SECONDS=300
LINUCB_ALPHA=0.25
MIN_INTERVENTION_EXPECTED_VALUE_INR=100
MIN_INTERVENTION_VALUE_MULTIPLIER=2.0
FEATURE_COMPLETENESS_MIN_RATIO=0.85
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_OPEN_SECONDS=30
AGENT_ASYNC_TARGET_LATENCY_MS=5000
P95_SYNC_LATENCY_TARGET_MS=150
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
REDPANDA_BROKERS=localhost:19092
GEMINI_API_KEY=<required in production>
LANGSMITH_API_KEY=<optional — tracing disabled cleanly if unset>
ENVIRONMENT=development
```

These are engineering defaults, not claims that a repository implementing them currently exists; they must remain identical across every document that references them (SPEC.md, ARCHITECTURE.md, TRD.md).

## R. Error Taxonomy

| Error class | Example | HTTP mapping (API layer) | Internal handling |
|---|---|---|---|
| `ValidationError` | Malformed request payload | 400 | Rejected before any scoring occurs |
| `ModelUnavailableError` | Artifact load/inference failure | N/A (caught internally) | Triggers fallback cascade, never surfaces as 5xx to the caller |
| `PolicyViolationError` | LinUCB/manual override attempts an action outside `allowed_actions` | N/A internally / 400 if surfaced from override endpoint | Blocked before persistence |
| `DependencyUnavailableError` | Redis/Redpanda/Postgres connection failure | Varies — see ARCHITECTURE.md §13 per-dependency behavior | Retried with backoff, degrades per documented behavior |
| `IdempotencyConflictError` | Same key, different payload | 409 | Original request wins; conflicting request rejected |
| `AuthorizationError` | Role lacks permission for the endpoint | 403 | Rejected before any business logic runs |

## S. Retry Semantics

- Stream consumer processing: bounded exponential backoff, max 5 attempts, then DLQ.
- Downstream dependency calls (Postgres, Redis) within the synchronous path: at most one retry with a short fixed delay (bounded by the overall latency budget), then fall back per ARCHITECTURE.md §13 rather than retrying indefinitely.
- MLflow artifact load: single attempt within the synchronous path (no retry — a slow retry would blow the latency budget); background/async re-attempt on a fixed interval to recover Tier 0 availability.

## T. Idempotency

- `POST /v1/risk/score`: idempotency key required (§L).
- Stream consumers: `event_id`-based dedup (§F/§G).
- Manual override: not idempotent by design — each override call creates a new, distinct `policy_decisions` row, since two overrides with the same reason are still two distinct auditable operator actions.

## U. Security Requirements

- **Authentication:** bearer-token based; token issuance is out of scope for this track and assumed to be handled by the merchant's existing identity provider.
- **Authorization:** role-based (`RISK_OFFICER`, `OPERATIONS_LEAD`, `ADMIN`), enforced per-endpoint per §L.
- **Secrets management:** all secrets (`GEMINI_API_KEY`, `DATABASE_URL` credentials, `LANGSMITH_API_KEY`) loaded from environment variables / a secrets manager, never committed to source control.
- **PII minimization:** only `customer_id_hash` is stored for customer identity; no name/email/phone/address fields exist in this system's schema.
- **Encryption:** TLS in transit for all external calls (API, MLflow, Gemini, LangSmith); encryption at rest assumed to be provided by the underlying managed database/object-storage layer.
- **Structured logging:** all logs are structured (JSON), with `return_reason` and any other free-text field redacted or truncated in logs by default (full text remains queryable in the database, not in log aggregation).
- **Audit logging:** every state transition (`policy_decisions`) and every published event (`audit_events`) is retained; these tables are append-only at the application-role database-grant level.
- **Model/data access controls:** MLflow registry write access (promotion) restricted to the MLOps role; read access to raw customer-level feature data restricted to the Risk Officer role via the API layer, never exposed directly at the database layer to the frontend.

## V. Testing Requirements

Test categories: unit, integration, contract, model, calibration, fallback, policy, agent, API, streaming, database, cache, end-to-end, failure-injection.

**Mandatory tests (all must exist and pass in CI before the system is considered demo-ready):**

1. Primary model (Tier 0) unavailable → Isolation Forest (Tier 1) activates.
2. Primary + Isolation Forest unavailable → Rules Engine (Tier 2) activates.
3. Redis unavailable → LRU fallback activates, no request failure.
4. Gemini unavailable → deterministic synchronous flow continues unaffected.
5. LangSmith unavailable → agent execution continues without tracing.
6. PostgreSQL unavailable → clearly defined degraded behavior (deferred persistence, not silent data loss).
7. Invalid event schema → rejected, routed to DLQ.
8. Stale/incompatible model artifact → rejected, falls back.
9. Policy-disallowed intervention → blocked before persistence.
10. Manual override → original decision preserved, new state transition recorded.
11. Duplicate event → processed idempotently (no double-decision).
12. Calibration artifact mismatch → falls back to Tier 1.
