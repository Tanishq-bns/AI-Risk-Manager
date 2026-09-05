> Relocated from repo root to docs/spec/ on 2026-09-05 for repository organization; content unchanged. Cited throughout the codebase as "TRD.md §X" etc. — see docstrings.

# SPEC.md — AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel

**Buildathon Track:** Track 02 — AI Risk Manager (Razorpay Buildathon)
**Document status:** Target specification. No repository currently exists for this project — every claim below describes the *intended* system, not an implemented one. Nothing in this document should be read as a benchmark result.

---

## 1. Executive Summary

AI Risk Manager is a real-time, economically-aware, defense-only decisioning system for Indian e-commerce and D2C merchants. At the moment a return is initiated, it estimates the probability that the return is abusive (`p_return_abuse`), converts that probability into an expected economic impact for the merchant, and selects the least-harmful intervention that maximizes expected net merchant value while minimizing friction imposed on legitimate customers. Every decision is calibrated, auditable, reversible by a human operator, and produced by a system that degrades safely rather than silently when any dependency fails.

The system is explicitly **not** "an AI that blocks suspicious customers." It is a decision-support system that quantifies both the cost of undetected abuse and the cost of unnecessarily inconveniencing a legitimate buyer, and picks the action with the best expected outcome for the merchant.

## 2. Problem Statement

Return abuse — wardrobing, switch-and-return, serial excessive returns, coordinated abuse rings, and reverse-logistics exploitation — erodes merchant margin directly (refund leakage, restocking loss, reverse-shipping cost) and indirectly (operational review load, fulfillment friction). Static, rule-based return policies cannot distinguish a legitimate first-time returner from a repeat offender without either being too lenient (losses continue) or too strict (legitimate customers are alienated, hurting retention and conversion). The absence of a calibrated, economically grounded decision layer means merchants either accept the loss or apply blanket friction that punishes good customers.

## 3. Indian E-Commerce / D2C Context

Return-abuse dynamics in the Indian market have characteristics that shape the design:

- High COD (cash-on-delivery) penetration, which correlates with a distinct abuse surface (failed fulfillment cycles, refusal-at-doorstep, COD-return loops) not present in pre-paid-only markets.
- Generous, marketing-driven return windows (7–30 days) common among D2C brands competing on customer experience, which widens the abuse window.
- High reverse-logistics cost relative to order value for many categories (apparel, footwear, small electronics), making the *economic* return-vs-no-return decision highly category- and geography-sensitive (delivery distance, courier zone).
- Fragmented merchant tooling — most mid-market D2C merchants do not have in-house risk teams, so the system must be usable by a small operations team via a dashboard rather than requiring a dedicated fraud-ops function.

## 4. Return-Abuse Taxonomy

| Category | Description | Primary signal family |
|---|---|---|
| Wardrobing | Item used (e.g., worn once) then returned as unused | Return timing, category, return reason text |
| Switch-and-return | A different or lower-value item is returned in place of the original | Reverse-inspection mismatch, weight/dimension anomaly |
| Serial excessive returns | Customer returns a disproportionate share of their orders | `customer_return_rate`, `customer_return_count` |
| Coordinated return-abuse | Multiple accounts/addresses exhibiting correlated abuse patterns | Address/device/network graph signals |
| Reverse-logistics abuse | Return requested primarily to exploit free/subsidized reverse pickup | Return frequency vs. order value, category cost ratio |
| COD-related abuse | Repeated COD order-then-refuse or COD order-then-return cycles | `cod_flag`, prior COD return history |
| Policy-window exploitation | Returns filed at the edge of the policy window with weak justification | `days_since_purchase`, return_reason patterns |

## 5. Scope

**In scope:**
- Real-time scoring of return requests at the moment a return is initiated (post-checkout, pre-refund-completion).
- Economic-impact estimation per candidate intervention.
- Policy-constrained intervention selection (LinUCB among merchant-allowed actions).
- Agentic investigation/verification/action-orchestration for cases that warrant enrichment, run asynchronously to the customer-facing latency path.
- Manual override with immutable audit history.
- Model fallback cascade guaranteeing a decision is always produced.

**Out of scope (v1):**
- Pre-purchase / checkout-time fraud (payment fraud, account-takeover) — the checkout event stream is consumed only to build behavioral context, not scored for payment fraud.
- Cross-merchant identity graph / consortium data sharing.
- Real-time SHAP-based per-decision explanation (v1 uses feature-contribution summaries from the model's built-in gain-based importance and rule triggers; see §42 of the master prompt / TRD.md §Explainability).
- Automated legal or law-enforcement action.

## 6. Non-Goals

- The system does not attempt to be a general-purpose fraud platform (payments, account security, promo abuse are explicitly out of scope for this track).
- The system does not attempt 100% automation — manual review and override are first-class, permanent parts of the design, not a fallback to be engineered away.
- The system does not optimize for "catch the most abuse" in isolation; it optimizes for expected net merchant value net of customer-friction cost.

## 7. Defensive-Only Guarantee

This system:
- Detects suspicious return behavior and estimates return-abuse risk.
- Estimates economic impact to support merchant decision-making.
- Selects the least-harmful intervention from a merchant-configured, policy-constrained action set.
- Produces an auditable trail for every decision, including model version, fallback tier, and rationale.
- Supports manual review and human override at every decision point.

This system explicitly does **not**:
- Generate offensive fraud techniques, evasion strategies, or instructions for bypassing merchant controls.
- Attempt unauthorized account access of any kind.
- Profile customers using protected or sensitive attributes (religion, caste, race, gender, political affiliation, health data, sexual orientation, or similar).
- Allow an LLM to be the source of truth for a numerical risk score or to make an irreversible high-impact decision unilaterally. ML models and the deterministic policy engine own risk/economic numbers and hard constraints; agents investigate, verify, explain, and orchestrate within those constraints.

## 8. System Objectives

1. Produce a calibrated `p_return_abuse` for every return request within a bounded synchronous latency budget.
2. Never fail to produce a decision — a bounded, deterministic fallback cascade guarantees availability even when ML infrastructure is degraded.
3. Convert risk into an economic decision, not a binary block/allow.
4. Keep every decision auditable and reversible.
5. Keep agentic/LLM components off the synchronous latency-critical path unless a specific case requires synchronous verification, and never let them be the numeric source of truth.

## 9. Success Metrics

### 10. ML Metrics (offline, on held-out temporal test set)

| Metric | Target | Rationale |
|---|---|---|
| PR-AUC | ≥ 0.65 | Primary metric under class imbalance (abuse is a minority class); accuracy is explicitly rejected as a headline metric (§ML Metrics Rationale below). |
| ROC-AUC | Reported, secondary | Useful for comparing model discrimination but insensitive to class imbalance; not used as the promotion gate. |
| Precision @ HIGH+CRITICAL band | ≥ 0.75 | Bounds false-positive rate for the bands that trigger customer-visible friction. |
| Recall @ HIGH+CRITICAL band | ≥ 0.60 | Ensures the model is not simply avoiding the positive class to inflate precision. |
| F1 (HIGH+CRITICAL) | Reported | Composite check, not a standalone gate. |
| Brier score | ≤ 0.15 | Calibration quality — required because the economic layer consumes `p_return_abuse` as a probability, not a rank. |
| Expected Calibration Error (ECE) | ≤ 0.05 | Secondary calibration diagnostic, bucketed reliability check. |
| False-positive rate (overall) | Reported and monitored, no fixed target pre-deployment | Tracked against the false-positive cost model in §14; the acceptable FPR is a business decision made via the cost curve, not a fixed ML target. |
| False-negative rate (overall) | Reported and monitored | Same as above. |

**Why PR-AUC over accuracy under class imbalance:** if abusive returns are a small minority of all return requests (typical for this problem — most returns are legitimate), a trivial "always legitimate" classifier scores high accuracy while catching zero abuse. PR-AUC evaluates precision/recall trade-offs specifically on the positive (minority, abuse) class across all thresholds, which is what the business actually cares about, and is far less inflated by the negative-class majority than ROC-AUC or accuracy.

### 11. Business Metrics

| Metric | Definition |
|---|---|
| Estimated merchant margin saved | Sum of `ExpectedNetValue(action)` for all HIGH/CRITICAL decisions where an intervention was taken and later confirmed effective, tracked as an engineering target metric once labels exist. |
| Intervention rate | Share of return requests receiving a friction-inducing intervention (A1–A4). |
| Manual-review rate | Share of return requests escalated to A4 (MANUAL_REVIEW). |
| Legitimate-customer friction rate | Share of *eventually-confirmed-legitimate* returns that received a friction-inducing intervention (a proxy for false-positive cost realized). |
| Zero-friction rate | Share of return requests resolved via A0 (ZERO_FRICTION_APPROVAL). |

## 12. Latency Objectives

| Path | Budget (p95) |
|---|---|
| Synchronous decision path (event ingest → risk score → economic estimate → policy-constrained action → persisted decision) | ≤ 150 ms, excluding asynchronous agent processing |
| Model inference call (XGBoost + isotonic calibration) | ≤ 100 ms (see `MODEL_INFERENCE_TIMEOUT_MS`) |
| Asynchronous agent enrichment (Investigator → Verifier → Action Orchestrator) | Not on the customer-facing critical path; target completion ≤ 5 s for audit/enrichment purposes |

## 13. Reliability Objectives

| Objective | Target |
|---|---|
| Decision availability (a decision — including fallback-tier decisions — is always produced) | ≥ 99.9% (demo/service objective, not a production SLA claim) |
| Fallback cascade correctness (Tier 0 → Tier 1 → Tier 2 activates on the correct trigger, see ARCHITECTURE.md) | 100% of defined trigger conditions covered by tests (see TRD.md §Testing) |

## 14. False-Positive Cost Model

See TRD.md and PRD.md for the full formulation. Summary:

- **C_FP** — cost of unnecessary friction imposed on a legitimate customer (support cost, conversion loss, LTV impact).
- **C_FN** — expected loss from an undetected abusive return (merchandise loss, reverse-logistics cost, refund leakage).
- **C_TP** — cost of the defensive intervention applied to a correctly identified abusive case (still non-zero: manual review has an operational cost even when correct).
- **C_TN** — cost of a normal, correctly-treated legitimate transaction (baseline, typically the lowest-cost path).

```
ExpectedLoss(action | x) = P(abuse | x) * Loss_if_abuse(action)
                          + (1 - P(abuse | x)) * FrictionCost(action)

ExpectedNetValue(action | x) = ExpectedLoss(no_intervention | x) - ExpectedLoss(action | x)
```

An intervention is selected only when it has positive expected net value under merchant-configured policy constraints — not simply because the risk probability crossed a band boundary. A high-risk, low-order-value case may still resolve to zero friction if the cost of intervening exceeds the expected recoverable loss (see §49 of the master prompt / TRD.md §Economic Guardrails).

## 15. False-Negative Cost Model

False negatives are priced through `Loss_if_abuse(no_intervention)`, which the Random Forest Reward Model estimates from transaction value, product value, reverse-logistics cost, and historical category/customer return-cost signals. This cost feeds directly into `ExpectedLoss` above; there is no separate "false-negative penalty" bolted on outside the expected-value formulation, keeping the economic model internally consistent.

## 16. Economic Objective

**Maximize expected net merchant value, not fraud-catch rate.** The system explicitly rejects "higher risk score → always more friction" as a design principle. Risk (`p_return_abuse`), economic impact (`ExpectedNetValue`), and the final action are three distinct, separately computed and separately logged quantities (see TRD.md DTOs).

## 17. Calibration Requirements

- Primary model probability must be calibrated via Isotonic Regression fit on a held-out calibration split disjoint from both training and test data.
- Calibration quality is measured via Brier score and a reliability diagram (predicted probability vs. observed frequency, bucketed).
- Isotonic calibration is preferred over Platt scaling for this problem because return-abuse probability is not assumed to follow a sigmoid relationship to the raw XGBoost margin, and sufficient calibration-set volume is expected to be available in a retail return-volume setting; see ARCHITECTURE.md / TRD.md for the tradeoffs and reconsideration criteria (small calibration sets, unstable score distributions favor Platt scaling instead).

## 18. Risk Bands

| Band | Range (calibrated `p_return_abuse`) |
|---|---|
| LOW | 0.00 ≤ p < 0.25 |
| MEDIUM | 0.25 ≤ p < 0.60 |
| HIGH | 0.60 ≤ p < 0.85 |
| CRITICAL | 0.85 ≤ p ≤ 1.00 |

These are **policy defaults**, not universal truth, and are distinct from the underlying **model threshold** concept: the model produces a continuous calibrated probability; risk bands are a policy-layer bucketing of that probability used for reporting, dashboarding, and as one (not the only) input to intervention selection. Band boundaries must ultimately be tuned against validation-set cost curves once real label data exists, not left as fixed constants indefinitely.

## 19. Intervention Evaluation

Interventions (A0–A4, defined fully in PRD.md) are evaluated by `ExpectedNetValue(action | x)` under LinUCB policy selection, constrained to the subset of actions the merchant has enabled and further constrained by the economic guardrails in §49 of the master prompt (minimum expected value, minimum value-to-cost ratio). Evaluation in offline settings uses rejection-sampling based off-policy evaluation against logged historical actions (see TRD.md §LinUCB).

## 20. Offline Evaluation Methodology

- Temporal split: TRAIN (historical period) → VALIDATION (subsequent period) → TEST (latest held-out period). No random shuffling across temporally correlated transactions.
- Entity-level leakage checks: a given `customer_id_hash` must not appear in both a training fold and the test fold in a way that leaks post-decision information about that same return.
- Metrics computed per §10 above, plus calibration diagnostics.
- LinUCB policy evaluated offline via rejection sampling against logged (simulated, in the absence of real production logs) historical action/outcome pairs before any online exploration is permitted.

## 21. Online / Demo Evaluation Methodology

Since no production traffic exists yet, "online" evaluation for the hackathon demo means: replaying the six demo scenarios in ROADMAP.md/PRD.md against the live service and confirming that (a) each scenario produces the expected band, fallback tier, and intervention, and (b) every decision is visible on the dashboard with a complete audit trail. This is a functional-correctness check, not a statistical evaluation, and must not be reported as a performance benchmark.

## 22. Model Monitoring

Track prediction-distribution drift (band distribution over time), feature missingness rate, calibration drift (rolling Brier score once labels become available), and fallback-activation rate. See TRD.md §Prometheus Metrics for concrete metric names.

## 23. Drift Monitoring

Population Stability Index (PSI) or an equivalent distributional-distance measure computed per feature and for the score distribution, on a rolling window, compared against the training-time reference distribution. A concrete PSI threshold (e.g., PSI > 0.2 = investigate, PSI > 0.25 = alert) should be finalized once real feature distributions exist; until then this is documented as the intended mechanism, not a validated threshold.

## 24. Data-Quality Monitoring

Per-feature completeness ratio, out-of-range value rate, and schema-mismatch rate at inference time, all exported as Prometheus metrics and feeding directly into the fallback-cascade trigger conditions (ARCHITECTURE.md §Fallback Cascade).

## 25. Acceptance Criteria

For the hackathon submission to be considered complete against this SPEC:

- [ ] All eight documents (SPEC, ARCHITECTURE, ROADMAP, STATE, PLAN, SUMMARY, PRD, TRD) exist and are internally consistent (identical thresholds, names, entities across all documents).
- [ ] The fallback cascade (Tier 0 → Tier 1 → Tier 2) is implemented and independently testable per the mandatory tests in TRD.md §Testing.
- [ ] All six demo scenarios (ROADMAP.md/PRD.md) are reproducible end-to-end.
- [ ] Manual override exists, preserves the original decision, and produces an audit event.
- [ ] No component claims an achieved benchmark number; all ML metrics are stated as targets with the exact evaluation command/artifact identified in TRD.md.
- [ ] LLM/agent components never originate a numerical risk or economic value used in a decision — all such values trace to XGBoost, Isotonic calibration, Isolation Forest, the Rules Engine, or the Random Forest Reward Model.
