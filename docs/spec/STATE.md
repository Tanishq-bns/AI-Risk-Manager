> Relocated from repo root to docs/spec/ on 2026-09-05 for repository organization; content unchanged. Cited throughout the codebase as "TRD.md §X" etc. — see docstrings.

# STATE.md — Architectural Decision Records

**Document status:** All ADRs below describe planned decisions for a system that does not yet have an implementation. Status field on each ADR is `PROPOSED` throughout this document until Phase 17 (ROADMAP.md) reconciles it against real implementation.

---

## ADR-001: XGBoost as Primary Supervised Model

- **Status:** PROPOSED
- **Context:** The system needs a primary classifier for `p_return_abuse` that handles heterogeneous tabular features (behavioral counts, categorical fields, monetary values), performs well under moderate class imbalance, and supports fast synchronous inference.
- **Decision:** Use XGBoost as the Tier 0 primary model.
- **Alternatives considered:** Logistic regression (too limited for non-linear interactions between return-history and category features); LightGBM (comparable performance, less mature ecosystem tooling for this team); deep tabular models / TabNet (higher complexity, higher latency, not justified at hackathon data volumes).
- **Why selected:** Strong track record on tabular fraud/risk problems, native handling of missing values, fast CPU inference suitable for the ≤150ms p95 budget, mature calibration and explainability tooling ecosystem.
- **Consequences:** Requires a separate calibration step (ADR-002) since raw XGBoost margins are not well-calibrated probabilities.
- **Risks:** Overfitting on a small hackathon-scale synthetic dataset — mitigated by regularization and the temporal validation split (SPEC.md §20).
- **Revisit criteria:** If PR-AUC target (≥0.65) cannot be met after feature-engineering iteration, or if inference latency cannot be kept under budget at production feature-vector size.

## ADR-002: Isotonic Calibration over Platt Scaling

- **Status:** PROPOSED
- **Context:** The economic layer (Reward Model, LinUCB) consumes `p_return_abuse` as a true probability, not a rank score, so calibration quality directly affects downstream economic decisions.
- **Decision:** Use Isotonic Regression to calibrate XGBoost's raw output into `p_return_abuse`.
- **Alternatives considered:** Platt scaling (logistic calibration) — simpler, more stable with small calibration sets, but assumes a sigmoid relationship between raw score and true probability that may not hold for this problem.
- **Why selected:** Isotonic regression is non-parametric and produces a monotonic mapping without assuming a particular functional form, which is preferred when sufficient calibration-set volume is available (expected in a retail return-volume setting).
- **Consequences:** Requires a calibration split disjoint from train/test, and is more prone to overfitting than Platt scaling on small calibration sets.
- **Risks:** If the actual calibration-set size at implementation time is small (e.g., hackathon synthetic data), isotonic calibration may overfit / produce an unstable step function.
- **Revisit criteria:** If the calibration-set size available at implementation time is small or the resulting reliability diagram shows instability, fall back to Platt scaling (documented explicitly as an accepted reconsideration path, not treated as a failure).

## ADR-003: Isolation Forest as Tier-1 Fallback

- **Status:** PROPOSED
- **Context:** When Tier 0 (XGBoost+Isotonic) is unavailable, the system still needs a risk signal without depending on labeled data at inference time.
- **Decision:** Use an Isolation Forest anomaly detector as Tier 1.
- **Alternatives considered:** A simpler statistical outlier detector (z-score on key features) — less able to capture multivariate anomaly patterns; a second supervised model trained on a reduced feature set — adds another labeled-training dependency, which defeats the purpose of a fallback that should degrade gracefully even when the primary training pipeline is unhealthy.
- **Why selected:** Isolation Forest is unsupervised, fast, robust to the exact same feature schema as the primary model (with graceful handling of a reduced feature subset), and produces a usable anomaly score without requiring labels to be current.
- **Consequences:** Tier 1 output is an anomaly-derived risk proxy, not a calibrated probability — this must be clearly labeled as such in every decision record (`scoring_source=ISOLATION_FOREST`) and never presented to a consumer as equivalent to `p_return_abuse`.
- **Risks:** Anomaly ≠ abuse; a legitimately unusual but non-abusive customer could score as anomalous.
- **Revisit criteria:** If Tier 1 false-positive rate (once measurable) is materially worse than an acceptable bound relative to Tier 0, consider adding a lightweight supervised fallback model instead.

## ADR-004: Deterministic Rules as Final Fallback

- **Status:** PROPOSED
- **Context:** If both ML tiers are unavailable, the system must still produce a decision rather than fail open or fail closed unpredictably.
- **Decision:** Use a deterministic, hand-authored Rules Engine as Tier 2.
- **Alternatives considered:** Failing the request entirely (rejected — violates the "always produce a decision" objective in SPEC.md §8); defaulting to always-approve (rejected — removes all defensive value exactly when infrastructure is degraded, which is the highest-risk moment); defaulting to always-manual-review (rejected as a blanket default — would overwhelm operations for high-volume merchants, though it remains an available *rule outcome* for specific high-signal conditions).
- **Why selected:** Deterministic rules require no ML infrastructure, are fully auditable and explainable, and can be tuned to be intentionally conservative (bias toward MEDIUM/HIGH rather than LOW when signal is ambiguous) specifically because this tier only activates during infrastructure degradation.
- **Consequences:** Lower discriminative power than either ML tier; rules must be kept simple enough to reason about without a training pipeline.
- **Risks:** Rules drifting out of sync with actual abuse patterns over time since they are not retrained.
- **Revisit criteria:** Rules should be reviewed whenever Tier 0/Tier 1 feature importance analysis reveals a strong new signal that should be reflected in the deterministic ruleset.

## ADR-005: LinUCB over Pure Heuristics

- **Status:** PROPOSED
- **Context:** Intervention selection among A0–A4 needs to account for context (risk, economic estimate, customer history) and improve over time from outcome feedback, while remaining safely constrained.
- **Decision:** Use LinUCB, a linear contextual bandit, for intervention selection among the policy-allowed action subset.
- **Alternatives considered:** Static heuristic thresholds (e.g., "HIGH band → always OTP inspection") — simple and explainable, but cannot learn from outcome data and hard-codes the "higher risk = more friction" assumption the master prompt explicitly rejects (§12); full reinforcement learning (e.g., deep contextual bandits) — unjustified complexity and data requirements for the available signal.
- **Why selected:** LinUCB provides a principled exploration/exploitation balance, is interpretable (linear in context features), supports off-policy evaluation via rejection sampling before any online use, and can be constrained to a merchant-allowed action subset without architectural changes.
- **Consequences:** Requires careful offline evaluation before any online exploration is permitted (SPEC.md §20); exploration parameter (`LINUCB_ALPHA`) must be conservative in production.
- **Risks:** Unconstrained exploration selecting a poor action live — mitigated by policy-constraint filtering applied *before* action scoring (ARCHITECTURE.md §8/13) and a bounded, auditable exploration budget.
- **Revisit criteria:** If offline rejection-sampling evaluation shows the bandit underperforms the static-heuristic baseline, defer bandit rollout and use heuristics as an interim.

## ADR-006: Random Forest Economic Reward Model

- **Status:** PROPOSED
- **Context:** The system needs to convert risk probability plus transaction context into an economic estimate (`expected_loss`, `expected_margin_saved`, `expected_net_value`) usable by the policy layer.
- **Decision:** Use a Random Forest Regressor.
- **Alternatives considered:** A hand-authored linear cost formula only — simpler and fully transparent, but cannot capture non-linear interactions (e.g., category-specific reverse-logistics cost curves); gradient-boosted regressor — comparable performance, but Random Forest's variance-reduction properties and lower sensitivity to hyperparameter tuning were preferred for a component whose *stability* (not marginal accuracy) matters most, since it directly gates friction decisions.
- **Why selected:** Handles non-linear feature interactions, provides reasonably stable predictions with default hyperparameters (valuable under hackathon time constraints), and integrates cleanly with the same feature pipeline as the primary classifier.
- **Consequences:** Reward is *predicted*, not purely formula-derived; the exact economic formula (SPEC.md §14) remains the ground-truth definition, and the Random Forest is trained to approximate its components (expected merchandise loss, reverse-logistics cost, recovery value) rather than short-circuiting the formula.
- **Risks:** Target leakage if trained on post-outcome fields — explicitly tested against (ROADMAP.md Phase 8).
- **Revisit criteria:** If predicted economic values diverge materially from the formula-derived baseline on validation data.

## ADR-007: LangGraph Multi-Agent Orchestration

- **Status:** PROPOSED
- **Context:** Some cases benefit from evidence investigation, consistency verification, and human-readable rationale generation beyond what the deterministic pipeline produces — but this must not compromise the safety guarantee that the LLM is never the source of numeric truth.
- **Decision:** Use LangGraph to orchestrate three agents (Investigator, Verifier, Action Orchestrator) that run asynchronously after the synchronous decision is made.
- **Alternatives considered:** A single monolithic LLM call — harder to constrain, harder to verify, conflates investigation with verification with action selection in one unauditable step; no agentic layer at all — loses explainability and the verifier's ability to catch evidence inconsistency (Demo Scenario E).
- **Why selected:** Separation of concerns across three agents makes each step's output independently auditable and testable, and keeps the graph's conditional-edge logic explicit (low confidence, missing data, model fallback, verifier disagreement, policy violation route to defined states — ARCHITECTURE.md §8).
- **Consequences:** Adds asynchronous infrastructure complexity (background task execution, eventual audit-trail consistency).
- **Risks:** Prompt injection via customer-supplied return-reason text — mitigated per §50 of the master prompt (data, never instructions; allowlisted tools).
- **Revisit criteria:** If asynchronous enrichment latency consistently exceeds the 5s target (SPEC.md §12) at expected case volume.

## ADR-008: Redis + In-Process LRU Fallback

- **Status:** PROPOSED
- **Context:** Risk-decision caching should reduce redundant scoring for repeated lookups of the same return request without introducing a hard dependency that could break scoring.
- **Decision:** Redis as primary cache, automatic in-process LRU fallback on Redis unavailability.
- **Alternatives considered:** No cache — simpler, but wastes compute on legitimate repeated lookups (e.g., dashboard re-fetching the same decision); Redis-only with no fallback — creates a hard dependency the system explicitly must not have (ARCHITECTURE.md §13).
- **Why selected:** Two-tier caching keeps the common case fast (Redis, shared across instances) while guaranteeing availability during Redis outages (LRU, process-local, accepted consistency tradeoff).
- **Consequences:** During an LRU-fallback period, different service instances may briefly disagree on cached state — acceptable because the cache is read-through and never the source of truth (PostgreSQL is).
- **Risks:** LRU fallback masking a persistent Redis outage from being noticed — mitigated by a dedicated Prometheus metric (`risk_cache_misses_total` combined with a Redis-health gauge).
- **Revisit criteria:** None anticipated; this is a low-risk, well-understood pattern.

## ADR-009: Redpanda Event-Driven Architecture

- **Status:** PROPOSED
- **Context:** Checkout and return events need a durable, ordered, replayable ingestion path decoupled from the synchronous scoring API, plus an audit/decision event stream for downstream consumers.
- **Decision:** Use Redpanda (Kafka-compatible API) for all event topics defined in TRD.md §Streaming Event Contracts.
- **Alternatives considered:** Direct synchronous HTTP-only integration with no event bus — simpler, but loses replayability, audit-stream fan-out, and decoupling between the ingestion producers and the scoring service; a different message broker (RabbitMQ) — Redpanda's Kafka compatibility was preferred for ecosystem tooling and the log-based replay semantics needed for feature-pipeline backfills.
- **Why selected:** Kafka-compatible durable log semantics support both real-time consumption and replay-based recovery (referenced in ARCHITECTURE.md §13 for Redpanda-outage recovery), and a single technology serves both ingestion and audit/decision fan-out.
- **Consequences:** Adds operational complexity (partitioning, consumer-group management) relative to a pure request/response design.
- **Risks:** Partition-ordering violations if keying strategy is inconsistent — mitigated by keying every topic on `entity_id`.
- **Revisit criteria:** None anticipated for hackathon scope; a production deployment would additionally need schema-registry-enforced compatibility checks.

## ADR-010: PostgreSQL as System of Record

- **Status:** PROPOSED
- **Context:** The system needs a durable, relational, transactionally consistent store for decisions, features, interventions, and audit history, with the strong consistency needed for override semantics (original decision must never be lost).
- **Decision:** PostgreSQL via async SQLAlchemy + Alembic migrations.
- **Alternatives considered:** A NoSQL document store — more flexible schema, but weaker support for the relational integrity (foreign keys across customers/orders/returns/decisions) and transactional guarantees the audit trail requires; using Redpanda's log as the sole source of record — rejected because point-in-time queries (e.g., "get decision by ID" for the dashboard) are a poor fit for a pure log without a materialized, queryable store.
- **Why selected:** Mature relational guarantees, strong tooling for migrations (Alembic) and async access patterns compatible with FastAPI, and straightforward support for the immutable-audit-append pattern required by manual override (ADR-012).
- **Consequences:** Requires careful indexing for the dashboard's query patterns (by customer, by band, by time range) — addressed in TRD.md §PostgreSQL Schema.
- **Risks:** Write contention at high volume — out of scope for hackathon volume, flagged as a production consideration (read replica noted in ARCHITECTURE.md §2).
- **Revisit criteria:** None anticipated for hackathon scope.

## ADR-011: Asynchronous Agentic Enrichment Instead of Blocking the Critical Path

- **Status:** PROPOSED
- **Context:** See ARCHITECTURE.md §9 for the full critical evaluation.
- **Decision:** LangGraph/Gemini agent processing runs asynchronously, after the synchronous decision is persisted; it never gates the customer-facing response.
- **Alternatives considered:** Synchronous agent verification before returning a decision — rejected because LLM latency is incompatible with the ≤150ms p95 budget and is not required for correctness (the synchronous pipeline is already fully deterministic and safety-constrained).
- **Why selected:** Keeps latency predictable and keeps the LLM structurally incapable of being the source of numeric truth, satisfying the defensive-only guarantee (SPEC.md §7) by construction rather than by policy alone.
- **Consequences:** Agent-driven manual-review escalation (Demo Scenario E) happens slightly after the initial decision is visible, which is an accepted and clearly-labeled eventual-consistency window in the dashboard.
- **Risks:** None beyond those already covered in ADR-007.
- **Revisit criteria:** If a future track requirement mandates synchronous LLM-verified decisions, this ADR would need to be revisited alongside the latency budget in SPEC.md §12.

## ADR-012: Manual Override with Immutable Audit History

- **Status:** PROPOSED
- **Context:** Human operators must be able to correct or override any automated decision, but the original decision must remain permanently visible for audit and model-evaluation purposes.
- **Decision:** An override creates a new `policy_decisions`/`audit_events` record referencing the original `risk_decisions` row; it never updates or deletes the original decision in place.
- **Alternatives considered:** In-place mutation of the original decision record — rejected outright; it would destroy the audit trail and make it impossible to later evaluate original-model accuracy against ground truth.
- **Why selected:** Append-only state transitions are the only pattern that satisfies both "an operator can change the outcome" and "the system remains fully auditable" simultaneously.
- **Consequences:** The API and dashboard must always resolve "current effective decision" as the latest state transition in the chain, not simply the first `risk_decisions` row — this is made explicit in TRD.md §API Contracts and PRD.md §Manual Override.
- **Risks:** None beyond standard append-only-log query complexity, which is handled by an explicit `current_decision` view/query.
- **Revisit criteria:** None anticipated.
