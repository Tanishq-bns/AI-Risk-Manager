# Project Artifact Inventory & Provenance Directory

**Repository:** AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel  
**Scope:** Complete Codebase, Test Suites, ML Models, Reports, Frontend, and Documentation  
**Audit Standard:** Buildathon Evidence & Reproducibility  

---

## 1. Core Source Modules (`risk_manager/`)

| Module Path | Purpose | Source of Truth |
| :--- | :--- | :--- |
| `risk_manager/api/app.py` | FastAPI application factory, router registration, static files mount. | Ingress definition |
| `risk_manager/api/services/risk_service.py` | Synchronous risk decisioning orchestrator (Ingress &rarr; Features &rarr; P4 &rarr; P5 &rarr; DB). | Critical path authority |
| `risk_manager/ml/cascade.py` | 3-tier ML scoring cascade (Tier 0 XGBoost &rarr; Tier 1 Isolation Forest &rarr; Tier 2 Rules). | Phase 4 Numerical Authority |
| `risk_manager/ml/xgboost_model/train.py` | XGBoost training and isotonic probability calibration pipeline. | Model training logic |
| `risk_manager/ml/calibration/isotonic.py` | Monotonic probability calibrator fitting and transformation. | Calibration math |
| `risk_manager/policy/engine.py` | Phase 5 LinUCB contextual bandit and Random Forest loss estimator. | Action selection authority |
| `risk_manager/agents/llm.py` | Agent LLM client with structured outputs, timeout bounds, and deterministic fallback. | Phase 6 LLM integration |
| `risk_manager/agents/verifier.py` | Verifier node running 10 deterministic invariants. | Invariant safety checks |
| `risk_manager/db/session.py` | Async SQLAlchemy database engine and session factory. | Database connection layer |
| `risk_manager/observability/tracer.py` | OpenTelemetry tracing and span propagation. | Telemetry layer |

---

## 2. Test Suites (`tests/`)

| Test Suite Path | Test Count | Purpose & Invariants Verified | Command to Reproduce |
| :--- | :---: | :--- | :--- |
| `tests/unit/test_authority_boundaries.py` | 5 | Adversarial tests proving p_abuse invariant, action immutability, verifier dominance, override exclusivity, and What-If isolation. | `pytest tests/unit/test_authority_boundaries.py` |
| `tests/unit/test_phase9_invariants.py` | 5 | Architectural invariants for Phase 6 multi-agent passivity and A4 human review mandate. | `pytest tests/unit/test_phase9_invariants.py` |
| `tests/unit/test_api_endpoints.py` | 15 | REST API contracts, validation errors, and review queue triage. | `pytest tests/unit/test_api_endpoints.py` |
| `tests/unit/test_ml_cascade.py` | 12 | Tier 0–2 degradation logic, isotonic calibration, and outlier handling. | `pytest tests/unit/test_ml_cascade.py` |
| `tests/unit/test_linucb_policy.py` | 11 | Multi-armed bandit exploration, reward updates, and safety guardrails. | `pytest tests/unit/test_linucb_policy.py` |
| `tests/unit/test_features.py` | 14 | Point-in-time feature extraction and zero temporal leakage assertions. | `pytest tests/unit/test_features.py` |
| `tests/unit/test_agents.py` | 16 | LangGraph agent state graph, investigator, verifier, and orchestrator nodes. | `pytest tests/unit/test_agents.py` |
| `tests/integration/test_phase9_simulation_security.py` | 4 | In-memory What-If isolation and governance contract endpoints. | `pytest tests/integration/test_phase9_simulation_security.py` |
| **Complete Suite** | **184** | **Exhaustive regression coverage (0 failures, 0 regressions).** | **`pytest`** |

---

## 3. Machine-Generated Reports (`reports/`)

| Report Path | Purpose | Source of Truth | Command to Reproduce |
| :--- | :--- | :--- | :--- |
| `reports/heldout_test/results.json` | Machine-readable metrics on frozen test split (ROC-AUC 0.978, PR-AUC 0.951). | Evaluated against `data/test.csv` (Seed 42) | `python scripts/evaluate_heldout.py` |
| `reports/heldout_test/ACCESS_LOG.md` | Immutable access and audit log for held-out evaluation. | Run timestamps & Git commits | Generated on evaluation |
| `reports/heldout_test/CAVEATS.md` | Honest analysis of synthetic data, class imbalance, and production limitations. | Scientific audit | Maintained manually |
| `reports/economic_impact.json` | Measurable ₹ business outcomes (₹82,847 loss avoided, +1,434 bps margin gain). | Evaluated across 170 claims | `python scripts/generate_economic_report.py` |
| `reports/ECONOMIC_IMPACT.md` | Markdown narrative of economic outcomes and policy action distribution. | Machine-generated | `python scripts/generate_economic_report.py` |
| `reports/COST_ASSUMPTIONS.md` | Authoritative documentation of logistics, friction, and operational cost parameters. | Financial model standard | Maintained in repo |
| `reports/failure_drills.json` | Machine-readable results of 17 architectural failure drills. | Fault-injection harness | `python scripts/failure_drills.py` |
| `reports/FAILURE_DRILLS.md` | Exhaustive failure drills ledger (17/17 PASSED). | Machine-generated | `python scripts/failure_drills.py` |
| `reports/performance.json` | Synchronous scoring latency percentiles (P50 90.65ms, P95 103.35ms). | 100 benchmark requests | `python scripts/benchmark_performance.py` |
| `reports/PERFORMANCE.md` | Latency benchmark report and tail latency analysis. | Machine-generated | `python scripts/benchmark_performance.py` |

---

## 4. Repeatable Scripts (`scripts/`)

| Script File | Execution Function | Reproducibility Command |
| :--- | :--- | :--- |
| `scripts/generate_synthetic_data.py` | Generates train (1,000), val (200), and held-out test (170) datasets with fixed seed 42. | `python scripts/generate_synthetic_data.py` |
| `scripts/train_models.py` | Trains Tier-0 XGBoost classifier and fits Isotonic Calibrator on temporal splits. | `python scripts/train_models.py` |
| `scripts/evaluate_heldout.py` | Evaluates held-out test split and generates `reports/heldout_test/results.json`. | `python scripts/evaluate_heldout.py` |
| `scripts/generate_economic_report.py`| Simulates economic outcomes and generates ₹ impact report. | `python scripts/generate_economic_report.py` |
| `scripts/failure_drills.py` | Injects 17 architectural faults and records fallback verification. | `python scripts/failure_drills.py` |
| `scripts/benchmark_performance.py` | Executes 100 synchronous scoring requests and computes P50–P99 latencies. | `python scripts/benchmark_performance.py` |

---

## 5. Serialized ML Artifacts (`models/`)

| Artifact File | Model Role | SHA256 Checksum (First 16 chars) | How to Reproduce |
| :--- | :--- | :---: | :--- |
| `models/xgboost_model.joblib` | Tier 0 Return Abuse Classifier | `91842d576c12b5c1` | `python scripts/train_models.py` |
| `models/isotonic_calibrator.joblib` | Monotonic Probability Calibrator | `b59dd63775113251` | `python scripts/train_models.py` |
| `models/isolation_forest.joblib` | Tier 1 Outlier Anomaly Detector | `3a448fbcbe1cfd3f` | Trained on data/train.csv |
| `models/rf_reward_model.joblib` | Phase 5 Economic Loss Regressor | `4b402c66e3c0f214` | Trained on economic returns |
| `models/preprocessor.joblib` | 17-Feature Column Transformer | `4010d7f539810cfe` | Fitted on data/train.csv |

---

## 6. Frontend Presentation (`risk_manager/api/static/`)

| File Path | Function & Role |
| :--- | :--- |
| `risk_manager/api/static/index.html` | Single-page responsive web console featuring 8 tabs + 10-Second Executive Banner. |
| `risk_manager/api/static/styles.css` | Modern vanilla CSS design system (dark theme, glassmorphism, responsive grids). |
| `risk_manager/api/static/app.js` | Frontend controller managing live scoring, What-If simulation, Judge Mode, and dynamic API polling. |

---

## 7. Architecture & System Documentation (`docs/` & Root)

| Document | Purpose & Authority |
| :--- | :--- |
| `README.md` | Master portfolio presentation document (18 sections, sharp insight, metrics, instructions). |
| `ARCHITECTURE.md` | Formal topology document with authoritative Mermaid diagram and invariant definitions. |
| `docs/SECURITY_MODEL.md` | Comprehensive threat model, adversarial prompt injection defense, and OWASP audit. |
| `docs/MODEL_LINEAGE.md` | End-to-end dataset &rarr; features &rarr; training &rarr; calibration &rarr; deployment lineage. |
| `docs/FINAL_DEMO_SCRIPT.md` | Precise 5–7 minute narrative presentation script with timestamps and live clicks. |
| `docs/FINAL_VALIDATION.md` | Formal testing gate audit and final system verification scorecard. |
| `docs/PROJECT_ARTIFACT_INVENTORY.md` | Complete inventory of modules, artifacts, reports, and commands. |
