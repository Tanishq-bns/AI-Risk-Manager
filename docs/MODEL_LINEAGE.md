# Model & Data Lineage Specification

**Status:** Authoritative & Machine-Verified  
**Repository:** AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel  
**Compliance Standard:** Buildathon Evidence Protocol & Model Governance  

---

## 1. Lineage Flow Summary

```
[ Synthetic Domain Dataset ] (Seed 42, 1,370 records)
             │
             ├──> [ data/train.csv ] (1,000 samples)
             ├──> [ data/val.csv ]   (200 samples)
             └──> [ data/test.csv ]  (170 samples, Held-Out Split)
                         │
                         ▼
[ 17-Feature Point-in-Time Schema ]
             │
             ├──> FeatureEncoder (preprocessor.joblib)
             │
             ▼
[ Model Training & Optimization ]
             │
             ├──> XGBoost Classifier (max_depth=4, lr=0.08, n=100)
             ├──> Isolation Forest Anomaly Detector (contamination=0.05)
             └──> Random Forest Economic Loss Predictor (n=100, max_depth=8)
                         │
                         ▼
[ Monotonic Probability Calibration ]
             │
             └──> Isotonic Regression on Validation Probabilities
                         │
                         ▼
[ Frozen Artifact Store: models/ ]
             │
             ├──> xgboost_model.joblib       (SHA256: 91842d576c12b5c1...)
             ├──> isotonic_calibrator.joblib (SHA256: b59dd63775113251...)
             ├──> isolation_forest.joblib    (SHA256: 3a448fbcbe1cfd3f...)
             ├──> rf_reward_model.joblib     (SHA256: 4b402c66e3c0f214...)
             └──> preprocessor.joblib        (SHA256: 4010d7f539810cfe...)
                         │
                         ▼
[ Held-Out Evaluation Protocol ]
             │
             └──> reports/heldout_test/results.json (ROC-AUC 0.978, PR-AUC 0.951)
                         │
                         ▼
[ Production Inference & Decisioning ]
             │
             └──> Synchronous Risk Service (P95 <= 150ms SLA)
```

---

## 2. Dataset Lineage & Generation

- **Source:** Synthetic e-commerce return transactions modeled on Indian retail logistics (COD vs. Prepaid, RTO patterns, courier distance bands).
- **Generation Script:** `scripts/generate_synthetic_data.py`
- **Random Seed:** `42` (Deterministic and reproducible)
- **Data Partitions:**
  - **Training Split:** `data/train.csv` (1,000 rows, 58.8% non-abusive, 41.2% abusive).
  - **Validation Split:** `data/val.csv` (200 rows, used exclusively for hyperparameter tuning and isotonic calibrator fitting).
  - **Held-Out Test Split:** `data/test.csv` (170 rows, strictly untouched during training and threshold selection).
- **Explicit Label:** `SYNTHETIC DATA / DEMONSTRATION VALIDATION` — Not measured on live merchant production traffic.

---

## 3. Feature Schema Lineage (17 Contract Features)

- **Feature Schema Version:** `v1.0.0`
- **Preprocessor Artifact:** `models/preprocessor.joblib`
- **Preprocessor SHA256:** `4010d7f539810cfe01c0be220f04cbb6c26887858c634c0e64ae5049a468d7e0`
- **Categorical Encoders:** One-hot / frequency mapping for `product_category`, `payment_method`, `delivery_distance_bucket`.
- **Numerical Encoders:** Robust min-max / standard scaling for `order_value`, `customer_return_rate`, `prior_return_frequency`, etc.

---

## 4. Artifact Registry & SHA256 Verification

Every binary artifact deployed in production has a cryptographically verifiable SHA256 digest:

| Artifact File | Model Tier / Role | Size (Bytes) | SHA256 Checksum (First 16 chars) | Status |
| :--- | :--- | :---: | :---: | :---: |
| `xgboost_model.joblib` | Tier 0: Return Abuse Classifier | 60,355 | `91842d576c12b5c1` | Verified |
| `isotonic_calibrator.joblib` | Tier 0: Isotonic Probability Calibrator | 684 | `b59dd63775113251` | Verified |
| `isolation_forest.joblib` | Tier 1: Anomaly Fallback Scorer | 1,162,882 | `3a448fbcbe1cfd3f` | Verified |
| `rf_reward_model.joblib` | Phase 5: Economic Loss Predictor | 428,082 | `4b402c66e3c0f214` | Verified |
| `preprocessor.joblib` | Pipeline: Feature Encoder | 4,118 | `4010d7f539810cfe` | Verified |

---

## 5. Training Hyperparameters & Configuration

### Tier 0: XGBoost Classifier
- **Model Type:** `xgboost.XGBClassifier`
- **Objective:** `binary:logistic`
- **Evaluation Metric:** `logloss`
- **Tree Depth (`max_depth`):** 4
- **Learning Rate (`learning_rate`):** 0.08
- **Estimators (`n_estimators`):** 100
- **Subsample Ratio:** 0.85
- **Colsample By Tree:** 0.85
- **Class Imbalance Handling:** `scale_pos_weight = 1.0` (Balanced synthetic sampling)

### Tier 0: Probability Calibration
- **Method:** Isotonic Regression (`sklearn.isotonic.IsotonicRegression`)
- **Out-of-Bounds Handling:** `out_of_bounds="clip"`
- **Monotonicity:** Strictly enforced non-decreasing mapping from raw tree log-odds to well-calibrated probabilities.

### Phase 5: Economic Loss Predictor
- **Model Type:** `sklearn.ensemble.RandomForestRegressor`
- **Estimators (`n_estimators`):** 100
- **Max Depth (`max_depth`):** 8
- **Evaluation Metric:** MAE (Mean Absolute Error) = ₹49.86, R² = 0.9623.

---

## 6. Evaluation & Deployment Artifacts

- **Authoritative Held-Out Results:** `reports/heldout_test/results.json`
- **Access Audit Trail:** `reports/heldout_test/ACCESS_LOG.md`
- **Limitations & Caveats:** `reports/heldout_test/CAVEATS.md`
- **Economic Value Report:** `reports/economic_impact.json`
- **Runtime Ingress:** `risk_manager/ml/cascade.py` loads models via `MLCascadeScorer.load_from_directory()`.
