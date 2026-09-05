# ML Evaluation Protocol & Splitting Methodology

**Protocol Version:** 1.0.0  
**Model Targets:** Tier 0 Return Abuse Risk Classifier (`v1.0.0-xgb-calibrated`) & Economic Reward Model (`v1.0.0-rf-econ`)  
**Data Type:** Synthetic Indian E-commerce Return Simulation (`seed=42`)  
**Status:** Frozen & Machine-Verified  

---

## 1. Principle of Evaluation Integrity

To avoid data leakage, overfitting, and optimistic bias, this project enforces strict temporal separation across all dataset splits. The held-out test split is never used for:
- Hyperparameter tuning
- Early stopping
- Probability calibration fitting
- Threshold optimization
- Repeated cherry-picking

Every metric reported in this repository is programmatically produced by `scripts/evaluate_heldout.py` and output to [`reports/heldout_test/results.json`](file:///reports/heldout_test/results.json).

---

## 2. Dataset Generation & Temporal Windows

The underlying return stream is generated using realistic archetypes (Legitimate, Wardrobing, COD Abuse, Serial Returners, Switch-and-Return) with non-leakage point-in-time feature extraction.

### Chronological Cutoffs
- **Dataset Start:** `2026-01-10T13:00:00+00:00`
- **Train Window:** `2026-01-10` to `2026-05-24T20:00:00+00:00` (790 returns, 3,950 economic pairs)
- **Validation Window:** `2026-05-24` to `2026-06-07T12:00:00+00:00` (169 returns, 845 economic pairs)
- **Held-Out Test Window:** `2026-06-07T13:00:00` to `2026-06-29T14:00:00+00:00` (170 returns, 850 economic pairs)

| Split | Time Period | Return Count | Abuse Count | Legit Count | Abuse Rate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Train** | Jan 10 – May 24 | 790 | 321 | 469 | 40.63% |
| **Validation** | May 24 – Jun 07 | 169 | 60 | 109 | 35.50% |
| **Held-Out Test** | Jun 07 – Jun 29 | 170 | 78 | 92 | 45.88% |
| **Total** | Jan 10 – Jun 29 | 1,129 | 459 | 670 | 40.66% |

---

## 3. Strict Target Leakage Protection

The Tier-0 model consumes strictly 16 point-in-time features defined by `FeatureVector.model_feature_names()`:
- **Order Characteristics:** `order_value`, `product_category`, `payment_method`, `cod_flag`
- **Customer Behavioral Aggregates (Strictly pre-decision):** `customer_order_count`, `customer_return_count`, `customer_return_rate`
- **Return Timing & History:** `days_since_purchase`, `prior_return_value`, `prior_return_frequency`
- **Logistics & Category Context:** `item_category_return_rate`, `delivery_distance_bucket`, `reverse_logistics_cost`, `estimated_item_recovery_value`
- **Risk Signal & Untrusted Text:** `historical_abuse_signal`, `return_reason`

**Leakage Assertions:** Post-outcome fields (`actual_loss`, `confirmed_abuse`, `refund_completed_at`) and identifiers (`customer_id_hash`, `order_id`) are asserted to be strictly absent from model training matrices.

---

## 4. Calibration & Evaluation Pipeline

1. **Training:** XGBoost binary classifier fitted on `X_train` with early stopping on `X_val` (`eval_metric="aucpr"`).
2. **Calibration:** `IsotonicProbabilityCalibrator` fitted **strictly on validation split predictions** (`val_raw_probs`, `y_val`). Test data is never observed during calibration fitting.
3. **Evaluation:** Calibrated model predicts on `X_test`. All metrics are computed by scikit-learn without manual adjustments.

---

## 5. Machine-Generated Results Summary

Refer to [`reports/heldout_test/results.json`](file:///reports/heldout_test/results.json) for exact floating-point outputs:
- **PR-AUC:** `0.951220`
- **ROC-AUC:** `0.978261`
- **Precision (0.5 threshold):** `0.939759`
- **Recall (0.5 threshold):** `1.000000`
- **F1 Score:** `0.968944`
- **Brier Score:** `0.025610`
- **Expected Calibration Error (ECE):** `0.027028`
- **Economic Model MAE:** `₹49.86` (R² = 0.9623)
