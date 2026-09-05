# ECONOMICS.md — AI Risk Manager Economic Outcome Model

**Document Version:** 1.0  
**Phase:** Phase 5 — Economic Outcome Model & Intervention Policy Foundation  
**Authoritative Input:** Calibrated $p_{\text{return\_abuse}}$ produced exclusively by Phase 4 XGBoost + Isotonic Calibrator.

---

## 1. Executive Summary & Architectural Invariant

The Economic Outcome Model estimates the expected financial consequences of intervention actions across return requests in Indian D2C commerce.

> [!IMPORTANT]
> **Strict Non-Negotiable Architectural Rule:**  
> The Phase 4 XGBoost + Isotonic Calibration pipeline is the **sole numerical authority** for $p_{\text{return\_abuse}}$.  
> Neither the Random Forest Regressor, LinUCB, nor any downstream agent may modify, override, invent, or reinterpret $p_{\text{return\_abuse}}$.  
> The economic model strictly consumes this probability to compute financial outcomes and margins saved. It never outputs an abuse probability.

---

## 2. Economic Formulation (SPEC.md §14)

For a return request with context $x$ and calibrated abuse probability $P(\text{abuse} \mid x) = p_{\text{return\_abuse}}$, we evaluate each intervention action $a \in \mathcal{A} = \{A0, A1, A2, A3, A4\}$.

### 2.1 Expected Loss Under Action $a$
$$\text{ExpectedLoss}(a \mid x) = P(\text{abuse} \mid x) \cdot \text{Loss\_if\_abuse}(a) + (1 - P(\text{abuse} \mid x)) \cdot \text{FrictionCost}(a)$$

Where:
- $\text{Loss\_if\_abuse}(a) = \text{UnmitigatedLoss} \cdot (1 - \text{MitigationRate}(a)) + \text{OperationalCost}(a)$
- $\text{UnmitigatedLoss} = \text{OrderValue} + \text{ReverseLogisticsCost} - \text{EstimatedRecoveryValue}$
- $\text{FrictionCost}(a)$: Customer goodwill and churn risk monetized in INR.
- $\text{OperationalCost}(a)$: Courier OTP, fee processing, or manual inspection cost in INR.

### 2.2 Expected Net Value Relative to Zero Friction ($A0$)
$$\text{ExpectedNetValue}(a \mid x) = \text{ExpectedLoss}(A0 \mid x) - \text{ExpectedLoss}(a \mid x)$$

Interpretation:
- If $\text{ExpectedNetValue}(a \mid x) > 0$, applying intervention $a$ yields a net expected financial benefit to the merchant compared to zero-friction approval.
- For $a = A0$, $\text{ExpectedNetValue}(A0 \mid x) \equiv 0.0$.

---

## 3. Intervention Action Space & Parameters

The system supports five canonical interventions with parameterized Indian D2C economics:

| Action ID | Action Name | Customer Friction Cost | Merchant Ops Cost | Abuse Mitigation Rate | Reversible | Requires Human | Automated Allowed |
|---|---|---|---|---|---|---|---|
| **A0** | `ZERO_FRICTION_APPROVAL` | INR 0 | INR 0 | 0.00 (0%) | Yes | No | Yes |
| **A1** | `DYNAMIC_RETURN_FEE` | INR 50 | INR 20 | 0.35 (35%) | Yes | No | Yes |
| **A2** | `OTP_DOORSTEP_INSPECTION` | INR 40 | INR 60 | 0.75 (75%) | No | No | Yes |
| **A3** | `STORE_CREDIT` | INR 80 | INR 15 | 0.50 (50%) | Yes | No | Yes |
| **A4** | `MANUAL_REVIEW` | INR 120 | INR 150 | 0.95 (95%) | Yes | Yes | No (Human Only) |

---

## 4. Random Forest Regressor Architecture

The economic model is trained to predict `expected_net_value` given the pre-decision feature context and candidate action encoding.

### 4.1 Feature Inputs (14 Engineered Signals)
1. `p_return_abuse`: Calibrated probability from Phase 4 $[0.0, 1.0]$
2. `order_value`: Gross transaction value in INR
3. `reverse_logistics_cost`: Carrier return transit cost in INR
4. `estimated_item_recovery_value`: Restock/salvage recovery in INR
5. `customer_return_rate`: Historical return frequency ratio $[0.0, 1.0]$
6. `prior_return_value`: Historical returned rupee sum
7. `prior_return_frequency`: Returns per 30-day velocity
8. `customer_order_count`: Completed historical orders count
9. `customer_return_count`: Historical return requests count
10. `cod_flag`: Binary indicator (1 for COD, 0 for Prepaid)
11. `days_since_purchase`: Elapsed days from fulfillment to return
12. `action_id`: One-hot or integer encoded action ($0 \dots 4$)
13. `friction_cost`: Action customer friction in INR
14. `operational_cost`: Action merchant operational cost in INR

### 4.2 Model Hyperparameters
- **Estimator:** `sklearn.ensemble.RandomForestRegressor`
- `n_estimators`: 100
- `max_depth`: 12
- `min_samples_split`: 5
- `min_samples_leaf`: 2
- `random_state`: 42
- `n_jobs`: -1

---

## 5. Offline Synthetic Training & Validation Discipline

### 5.1 Dataset Splits (Temporal Realism)
To prevent temporal leakage and match the Phase 3/4 evaluation boundaries:
- **Train Set:** $N = 3,950$ synthetic action-outcome observations ($t < T_{\text{val\_cutoff}}$)
- **Validation Set:** $N = 845$ observations ($T_{\text{val\_cutoff}} \le t < T_{\text{test\_cutoff}}$)
- **Test Set:** $N = 850$ held-out observations ($t \ge T_{\text{test\_cutoff}}$)

### 5.2 Leakage Controls
- Ground truth `is_return_abuse` is used **only** to generate the simulated outcome target in the generator; it is strictly excluded from feature inputs.
- No post-inspection outcome fields are present in the feature vectors.
- Preprocessor scales features using statistics fitted exclusively on the training split.

---

## 6. Model Evaluation & Performance Metrics

Evaluated on the held-out temporal test set ($N=850$):

| Metric | Target / Benchmark | Achieved Test Result |
|---|---|---|
| **Mean Absolute Error (MAE)** | $< \text{INR } 80.00$ | **INR 49.86** |
| **Root Mean Squared Error (RMSE)** | $< \text{INR } 150.00$ | **INR 103.30** |
| **Coefficient of Determination ($R^2$)** | $> 0.90$ | **0.9623** |
| **Worst-Case Error** | $< \text{INR } 1000.00$ | **INR 644.23** |

### 6.1 Action-Level Metrics
| Action | Test Samples | Action MAE (INR) | Action RMSE (INR) |
|---|---|---|---|
| **A0** (`ZERO_FRICTION_APPROVAL`) | 170 | INR 0.00 | INR 0.00 |
| **A1** (`DYNAMIC_RETURN_FEE`) | 170 | INR 38.48 | INR 72.16 |
| **A2** (`OTP_DOORSTEP_INSPECTION`) | 170 | INR 60.19 | INR 110.97 |
| **A3** (`STORE_CREDIT`) | 170 | INR 63.61 | INR 110.68 |
| **A4** (`MANUAL_REVIEW`) | 170 | INR 87.00 | INR 153.57 |

---

## 7. Model Artifacts & Reproducibility

All model artifacts are persisted under `models/`:
- `models/rf_reward_model.joblib`: Trained Random Forest regressor
- `models/economic_metrics.json`: Evaluated test metrics and distribution
- `models/economic_model_metadata.json`: Feature schema, training timestamp, parameter configuration

### Reproduction CLI:
```bash
python -m risk_manager.ml.reward_model.train --seed 42 --output-dir models
```
