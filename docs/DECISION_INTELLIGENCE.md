# Decision Intelligence & Factor Explainability Framework

## 1. Product Philosophy: Economic Awareness vs False-Positive Destruction

Most e-commerce return fraud systems fail because they operate under a simplistic heuristic:
> *"If risk score is elevated, block or disallow the return."*

In modern digital commerce, this paradigm destroys customer lifetime value (LTV). Aggressively blocking loyal shoppers generates catastrophic friction, brand abandonment, and dispute costs that far exceed the price of an individual return item.

The **AI Risk Operating System** replaces blunt blocking with **calibrated economic optimization**:
$$\max_{a \in \mathcal{A}_{\text{eligible}}} V(a) = R - L(a) - C_{\text{friction}}(a) - C_{\text{op}}(a)$$

Where:
- $R$: Expected recovery value of the returned merchandise.
- $L(a)$: Expected merchant loss under intervention $a$.
- $C_{\text{friction}}(a)$: Customer friction cost imposed by action $a$ (quantifying negative goodwill).
- $C_{\text{op}}(a)$: Direct courier, inspection, and verification costs.

---

## 2. Canonical Action Tradeoff Spectrum

| Action Code | Action Name | Friction Cost | Operational Cost | Primary Economic Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **A0** | `ZERO_FRICTION_APPROVAL` | **INR 0.00** | **INR 0.00** | Maximize repeat customer trust for low-risk purchases. Instant refund. |
| **A1** | `DYNAMIC_RETURN_FEE` | **INR 15.00** | **INR 35.00** | Offsets marginal reverse logistics costs without blocking legitimate returns. |
| **A2** | `OTP_DOORSTEP_INSPECTION`| **INR 40.00** | **INR 75.00** | Eliminates empty-box and counterfeit swaps before driver accepts item. |
| **A3** | `STORE_CREDIT_DEFAULT` | **INR 50.00** | **INR 50.00** | Preserves merchant capital while resolving disputed claims. |
| **A4** | `MANUAL_REVIEW_ESCALATE` | **INR 150.00** | **INR 150.00** | Strict human-in-the-loop escalation for severe fraud or anomalous signals. |

---

## 3. Honest Explainability vs Fabricated Attributions

### Why Fabricated Client-Side SHAP Values Are Rejected
Many demo platforms display arbitrary client-side bar charts claiming: *"Order value contributed +32% to fraud probability."* Unless a formal Game-Theoretic Shapley computation is executed over verified marginal feature subsets, these visual gimmicks create dangerous false confidence and legal exposure in fintech risk underwriting.

### The Decision Factor Approach
The AI Risk Manager provides **honest, mathematically defensible decision factors**:
1. **Economic Advantage Delta ($\Delta V_{\text{A0}}$)**: Quantifies the exact expected INR net gain of the selected action over a zero-friction instant refund:
   $$\Delta V_{\text{A0}} = V(a^*) - V(\text{A0})$$
2. **Risk Band Calibration Driver**: Documents the calibrated probability $p_{\text{return\_abuse}}$ mapped directly from the Phase 4 isotonic curve into its authoritative risk band (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
3. **Active Eligibility Guardrails**: Explicitly lists why alternative interventions were disqualified (e.g. *"Action A3 disallowed because customer has $\ge 5$ orders and $\le 10\%$ return rate"*).
4. **Non-Causal Language**: Statements describe *observed correlation and policy constraints* (e.g. *"Associated with elevated historical return frequency"*) rather than claiming *unproven causality*.

---

## 4. What-If Counterfactual Simulator

The What-If Simulator (`POST /api/v1/demo/simulate`) allows risk underwriters to simulate policy shifts in-memory without polluting live merchant records:
- **Sandbox Guarantee**: Executes feature assembly, ML cascade scoring, and LinUCB policy evaluation purely in memory; zero database rows or audit events are created.
- **Side-by-Side Diffing**: Renders live baseline metrics against simulated outcomes to show immediate economic impact.
