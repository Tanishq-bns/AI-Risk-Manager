# System Failure & Fallback Resilience Matrix

## 1. Reliability Architecture Overview

The **AI Risk Operating System** is engineered with strict defense-in-depth degradation:
1. **Critical Path Isolation**: The synchronous risk decisioning path (`POST /api/v1/risk/score`) has an absolute SLA budget of $\le 150\text{ ms}$ P95.
2. **Zero-Downtime Fallbacks**: Every single component—from ML classifiers and LLM APIs to database connections and OpenTelemetry exporters—has a deterministic, in-process fallback.
3. **Immutability of Numerical Authority**: No fallback mechanism is permitted to escalate risk or bypass policy guardrails silently.

---

## 2. Component Degradation Matrix

| Layer / Component | Primary Function | Failure Mode Detected | Fallback Pathway | Latency Budget | User / Merchant Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 0: XGBoost Classifier** | $p_{\text{return\_abuse}}$ prediction | Model artifact missing, NaN features, unhandled inference crash | **Tier 1 Isolation Forest** unsupervised anomaly detector activated | $\le 15\text{ ms}$ | Decision succeeds with `fallback_tier: 1`; audit flag logged. |
| **Tier 1: Isolation Forest** | Out-of-distribution anomaly scoring | Pipeline transformation error or memory fault | **Tier 2 Deterministic Rules Engine** evaluates domain heuristics | $\le 20\text{ ms}$ | Decision succeeds with `fallback_tier: 2`; conservative risk assigned. |
| **Tier 2: Rules Engine** | Hard safety boundary | Logic exception | Hardcoded fallback: `p_abuse = 0.50` (MEDIUM band, A2 inspection) | $\le 2\text{ ms}$ | Merchant assets protected; customer not blocked. |
| **Phase 5 Policy Engine** | LinUCB action selection & expected net value | LinUCB matrix inversion singularity or parameter error | Hardcoded policy lookup: `LOW -> A0`, `MEDIUM/HIGH -> A2`, `CRITICAL -> A4` | $\le 10\text{ ms}$ | Intervention assigned safely within policy boundaries. |
| **Google Gemini 2.0 Flash** | Asynchronous investigation & unstructured text reasoning | Rate limit (429), API timeout ($> 5\text{s}$), malformed JSON, network drop | **DeterministicFallbackAgent** runs 10 deterministic invariant checks in Python | $\le 5000\text{ ms}$ (Async) | Synchronous score **completely unaffected**; provenance stamped `DETERMINISTIC_FALLBACK`. |
| **Phase 6 Deterministic Verifier** | 10 Invariant safety checks | Local execution error | Strict fail-safe: routes case to **Human Review Queue** (`A4`) | $\le 5\text{ ms}$ (Async) | High-risk cases held for human eyes; zero unauthorized automation. |
| **Database (SQLite / Postgres)** | Decision, order, and audit persistence | Disk full, lock timeout, network partition | Error caught and recorded in telemetry; read-only response returned | $\le 10\text{ ms}$ | Synchronous response returns valid decision; persistence failure metric incremented. |
| **OpenTelemetry / Collector** | Distributed trace export | Collector unreachable, network timeout, exporter error | Safe in-process `NoOpSpan`; zero-overhead execution | $\le 1\text{ ms}$ | Traces emitted locally; risk scoring continues without interruption. |

---

## 3. Failure Demonstration & Chaos Injection (Demo Mode Only)

In `DEMO_MODE`, the system allows operators to simulate failure conditions to verify resilience:
1. **Gemini Disconnected**: Remove `GEMINI_API_KEY` from `.env` $\to$ System immediately switches to `DeterministicFallbackAgent`. All 10 invariant checks execute with zero latency penalty.
2. **Collector Disconnected**: Set `OTEL_ENABLED=false` or point to dummy port $\to$ API continues normally; health endpoint accurately reflects `tracing_exporter: unconfigured`.
3. **Database Degraded**: Read-only simulation mode (`POST /api/v1/demo/simulate`) exercises the entire ML and policy pipeline with zero database reads/writes.
