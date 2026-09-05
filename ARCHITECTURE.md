# System Architecture & Topology

**Status:** Authoritative Production Implementation  
**Project:** AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel  
**Compliance Standard:** Buildathon Excellence & Evidence Specification  

---

## 1. System Topology & Path Isolation

The diagram below details the end-to-end topology of the AI Risk Manager.

```mermaid
flowchart TB
    %% ==========================================
    %% SYNCHRONOUS INGRESS & CRITICAL PATH
    %% ==========================================
    subgraph SYNC["Synchronous Decision Authority Path (SLA <= 150ms)"]
        direction TB
        REQ["1. Ingress Request\n(RiskScoreRequest)"]
        VAL["2. Pydantic v2\nBoundary Validation"]
        IDEM{"3. Idempotency Gate\n(Cached Key?)"}
        FEAT["4. Feature Engineering\n(17 Point-in-Time Features)"]
        P4["5. Phase 4 ML Cascade\n(Numerical Authority)"]
        P5["6. Phase 5 Policy Bandit\n(Economic Authority)"]
        PERS["7. Async Persistence\n(Risk & Policy Decision)"]
        AUD["8. Audit Ledger\n(Immutable AuditEvent)"]
        RESP["9. Synchronous Response\n(RiskScoreResponse)"]

        REQ --> VAL --> IDEM
        IDEM -- Cache Miss --> FEAT --> P4 --> P5 --> PERS --> AUD --> RESP
        IDEM -- Cache Hit --> RESP
    end

    %% ==========================================
    %% PHASE 4 & 5 FALLBACK SUBSYSTEM
    %% ==========================================
    subgraph FALLBACKS["Layered Fallback Subsystem"]
        direction TB
        T0["Tier 0: XGBoost Classifier\n+ Isotonic Calibrator"]
        T1["Tier 1: Isolation Forest\nAnomaly Detector"]
        T2["Tier 2: Conservative\nDeterministic Rules"]
        POL_FB["Policy Fallback:\nStatic Risk-Band Guardrail Map"]

        P4 -. Primary Scorer .-> T0
        T0 -. Failure / Outlier .-> T1
        T1 -. Model Degraded .-> T2
        P5 -. LinUCB Exception .-> POL_FB
    end

    %% ==========================================
    %% ASYNCHRONOUS AGENT SENTINELS (PASSIVE)
    %% ==========================================
    subgraph ASYNC_AGENTS["Asynchronous Agent Sentinels (Zero Numerical Authority)"]
        direction TB
        EVT_BUS["Event Bus / Background Task\n(In-Memory / Redpanda)"]
        INV["Investigator Agent\n(Risk & Injection Scanner)"]
        VER["Verifier Agent\n(Deterministic Invariant Checker)"]
        ORCH["Action Orchestrator\n(Passive Explainer & Router)"]
        REV_Q["Risk Operations\nReview Queue"]
        HUMAN["Authorized Human Override\n(Append-Only Audit)"]

        AUD -. Publishes Event .-> EVT_BUS
        EVT_BUS --> INV --> VER --> ORCH
        ORCH -. Flagged or A4 .-> REV_Q
        REV_Q -. Specialist Review .-> HUMAN
        HUMAN -. Appends Override .-> PERS
    end

    %% ==========================================
    %% DATA & INFRASTRUCTURE
    %% ==========================================
    subgraph DATA_INFRA["Data & Storage Tier"]
        SQLITE[("SQLite Async (Zero-Docker)\nor PostgreSQL")]
        CACHE[("In-Memory Cache\nor Redis")]
        MODELS[("Serialized Artifacts: models/\n(SHA256 Verified Joblib)")]
        MLFLOW[("MLflow Tracking\n& Registry")]

        PERS <--> SQLITE
        AUD --> SQLITE
        IDEM <--> CACHE
        P4 <--> MODELS
    end

    %% ==========================================
    %% OBSERVABILITY & TELEMETRY
    %% ==========================================
    subgraph OBS["Telemetry & Observability (Non-Blocking)"]
        OTEL["OpenTelemetry Tracing\n(W3C Trace Context)"]
        PROM["Prometheus Metrics\n(/metrics Endpoint)"]
        GRAF["Grafana Dashboards"]
        LSMITH["LangSmith Tracing\n(Agent Spans Only)"]

        SYNC -. Span Traces .-> OTEL
        SYNC -. Metric Increments .-> PROM
        PROM --> GRAF
        ASYNC_AGENTS -. Agent Traces .-> LSMITH
    end

    %% ==========================================
    %% OFFLINE TRAINING & EVALUATION
    %% ==========================================
    subgraph OFFLINE_LEARNING["Offline Learning & Evaluation Pipeline"]
        DATASET[("Synthetic Dataset\n(Seed 42, 1,370 Records)")]
        PREPROC["Feature Preprocessor\n(FeatureEncoder)"]
        TRAIN["Model Training\n(XGBoost + RF Loss)"]
        CALIB["Isotonic Calibration\n(Monotonic Fitting)"]
        HELDOUT["Held-Out Evaluation\n(results.json N=170)"]

        DATASET --> PREPROC --> TRAIN --> CALIB --> HELDOUT --> MODELS
        TRAIN -. Log Params .-> MLFLOW
    end
```

> **The center path is the synchronous decision authority; side branches provide fallbacks, persistence, offline learning, streaming, agent investigation, and observability without being allowed to alter the authoritative decision.**

---

## 2. Invariant Boundary Definitions

### Synchronous Critical Path
The synchronous risk decision path executes in $\le 150\text{ ms}$ (P95 target). It contains exactly nine sequential steps:
1. Ingress request validation (`RiskScoreRequest`).
2. Idempotency deduplication check (`idempotency_key`).
3. Point-in-time feature engineering (17 deterministic features).
4. **Phase 4 ML Cascade Scoring:** Sole numerical authority for $p_{\text{return\_abuse}}$, `risk_band`, `scoring_source`, and `fallback_tier`.
5. **Phase 5 Economic & Policy Engine:** Sole authority for expected loss, net value, candidate action eligibility, and selected action.
6. Asynchronous database transaction persistence.
7. Append-only audit ledger entry (`AuditEvent`).
8. Synchronous response formatting (`RiskScoreResponse`).

No generative AI model, agentic workflow, external telemetry exporter, or human review blocks this synchronous pipeline.

### Asynchronous Multi-Agent Sentinel Path
Once the decision is committed, domain events trigger the Phase 6 LangGraph agent sentinel asynchronously:
- **Investigator:** Performs text feature extraction, checks return claim plausibility, scans for adversarial prompt injection, and flags contradictions.
- **Verifier:** Evaluates 10 deterministic invariants (risk band consistency, action validity, eligibility guardrails, economic non-negativity). If any deterministic check fails, verification **fails definitively**; no LLM output can override a deterministic failure.
- **Action Orchestrator:** Formulates plain-language risk explanations and routes flagged or critical cases to human review.
- **Strict Boundary:** Agents possess **zero numerical authority**. They can never alter $p_{\text{return\_abuse}}$, change the selected policy action, or mutate historical records.

### Human Review & Override Exclusivity
- An authorized human operator in the Risk Operations console is the **only** entity permitted to alter an effective policy action.
- Overrides follow append-only semantics: the original algorithmic decision is **never deleted or mutated**. A new `PolicyDecision` row is appended with `selected_by=MANUAL_OVERRIDE`, linked to an immutable `AuditEvent` recording operator ID, timestamp, and justification.

### Pure In-Memory What-If Counterfactual Sandbox
- The counterfactual simulation endpoint (`POST /api/v1/demo/simulate`) executes the real Phase 4 cascade and Phase 5 policy bandit.
- Simulations run **entirely in memory**, creating 0 database rows, 0 audit events, and 0 production state alterations.
