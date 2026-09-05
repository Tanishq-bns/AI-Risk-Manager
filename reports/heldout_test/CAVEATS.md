# Held-Out Evaluation: Brutally Honest Caveats & Limitations

**Status:** Transparent Audit  
**Auditor:** Principal AI/ML Architect & Senior Research Scientist  

---

## 1. Synthetic Data vs Real Production Traffic

> [!WARNING]
> **This evaluation was conducted on synthetically generated return events.**  
> While the generator models realistic Indian e-commerce phenomena (COD doorstep refusal loops, wardrobing on expensive apparel, and serial returners), **synthetic distributions cannot capture the full chaotic entropy, seasonal anomalies, and organized adversarial fraud rings of live production traffic.**

### Specific Data Limitations
1. **Sample Size:** The held-out test split contains **170 return events** (and 850 economic intervention evaluations). While statistically informative for prototype validation, production systems require hundreds of thousands of returns evaluated across multi-month production drift.
2. **Abuse Base Rate:** The test set abuse rate is **45.88%** (78 abusive / 92 legitimate returns). In a real-world mature marketplace, return abuse typically hovers between **12% and 25%** of all returns. The higher base rate in this test set concentrates risk signals and produces an artificially elevated PR-AUC (`0.9512`) compared to a sparse production environment.
3. **Bimodal Calibrated Distribution:** On this synthetic dataset, the calibrated probabilities cluster heavily near 0.0 (87 samples in `LOW`) and 1.0 (82 samples in `CRITICAL`), with only 1 sample falling in `MEDIUM` and 0 in `HIGH`. In live production, real human behavior produces far more ambiguity in the `MEDIUM` (0.25–0.60) and `HIGH` (0.60–0.85) bands.

---

## 2. Model & Calibration Limitations

1. **Isotonic Calibration Monotonic Step Function:**
   Isotonic regression produces piece-wise constant probabilities. When validation sample sizes are small, it can assign identical clipped probabilities (e.g. `0.5948` or `1.0000`) across a range of raw logit scores. A production deployment would benefit from spline calibration or Platt scaling when data volume is thin.
2. **Absence of Real Delayed Feedback:**
   In real life, return abuse labels are delayed by days or weeks (e.g., waiting for the warehouse inspection report or merchant chargeback). The synthetic dataset assumes ground-truth labels are instantly available at evaluation time.
3. **Feature Stationarity:**
   The features assume stationary distributions between January and June 2026. Real e-commerce faces severe distribution shifts during festive sales (Diwali, Great Indian Festival) where order volume surges 5x and return velocity spikes.

---

## 3. Economic Model Assumptions

1. **Fixed Customer Friction Costs:**
   Friction costs ($A_1 = ₹25, A_2 = ₹150, A_3 = ₹75, A_4 = ₹500$) are currently modeled as fixed values per action. In production, friction cost is a continuous function of customer lifetime value (LTV), brand loyalty, and social sentiment.
2. **Simulated Counterfactual Outcomes:**
   The true economic outcome of an intervention ($A_1$ fee or $A_2$ inspection) is estimated via Random Forest regression on simulated margin savings. Without live A/B randomized controlled trials (RCTs), counterfactual treatment effects contain unobservable selection bias.

---

## 4. Summary Verdict

The metrics presented in [`results.json`](file:///reports/heldout_test/results.json) prove that **the algorithmic architecture, training pipeline, and evaluation harness are mathematically sound, leak-free, and reproducible**. However, **they must be viewed as an engineering benchmark under synthetic conditions, not as an in-situ production claim.**
