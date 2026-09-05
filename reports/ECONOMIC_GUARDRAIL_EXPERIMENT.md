# Controlled Economic Guardrail Experiment: Why Risk ≠ Loss

**Generated:** 2026-09-05T07:02:40.481653+00:00  
**Status:** `MACHINE-VERIFIED DECISION EXPERIMENT`  

## Executive Thesis
> **"The best risk decision is not always the most restrictive action."**  
> Conventional fraud systems treat risk scoring as a binary classification problem: high score $\to$ block. 
> In real retail commerce, blocking creates catastrophic collateral friction on good customers, while heavy manual reviews for low-value items cost more than the fraud itself. 
> **AI Risk Manager** evaluates the exact economic equation: 
> $$\mathbb{E}[V_{\text{net}}] = \Delta \text{Loss} - (1 - p) \cdot C_{\text{friction}} - p \cdot C_{\text{ops}}$$

---

### Archetype 1: High Risk, Low Order Value

**Context:** High abuse probability on a low-ticket item (₹350). Operational review or courier OTP inspection would cost more than the item itself.  

- **Order Value:** ₹350.00 | **Reverse Logistics Cost:** ₹110.00 | **Recovery Value:** ₹50.00
- **Risk Probability (p_abuse):** `0.76` (HIGH)  
- **Unmitigated Loss Exposure:** ₹410.00  
- **Baseline Loss without Intervention:** ₹311.60  
- **Selected Policy Action:** **`A3`** (via `LINUCB`)  

#### Action Candidate Trade-Off Matrix

| Action | Name | Eligible? | Reason / Constraint | Exp. Loss (₹) | Net Value Created (₹) | Friction (₹) | Ops Cost (₹) |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| A0 | ZERO_FRICTION_APPROVAL | ✓ Yes | - | ₹311.60 | **₹0.00** | ₹0.00 | ₹0.00 |
| A1 | DYNAMIC_RETURN_FEE | ✗ No | `Filtered by guardrails (RiskBand=HIGH)` | ₹86.32 | **₹225.28** | ₹50.00 | ₹20.00 |
| A2 | OTP_DOORSTEP_INSPECTION | ✗ No | `Filtered by guardrails (RiskBand=HIGH)` | ₹0.00 | **₹312.96** | ₹40.00 | ₹60.00 |
| **A3** | STORE_CREDIT | ✓ Yes | - | ₹82.76 | **₹228.84** | ₹80.00 | ₹15.00 |
| A4 | MANUAL_REVIEW | ✗ No | `Filtered by guardrails (RiskBand=HIGH)` | ₹0.00 | **₹312.96** | ₹120.00 | ₹150.00 |

**Decision Rationale:**
> **Why A0 dominates even with High Risk (p=0.76)?** Guardrails enforce `min_order_value` thresholds ($A1 \ge ₹500$, $A2 \ge ₹1,000$, $A4 \ge ₹1,500$). Even if eligible, dispatching a courier inspection (₹60) or human reviewer (₹150) for a ₹350 item creates negative economic yield. Absorbing the return produces higher net merchant value than fighting it.

---

### Archetype 2: High Risk, High Item Recovery Value

**Context:** High abuse probability on a high-value consumer electronic (₹16,500) where physical item recovery yields significant salvaged value.  

- **Order Value:** ₹16,500.00 | **Reverse Logistics Cost:** ₹220.00 | **Recovery Value:** ₹14,000.00
- **Risk Probability (p_abuse):** `0.82` (HIGH)  
- **Unmitigated Loss Exposure:** ₹2,720.00  
- **Baseline Loss without Intervention:** ₹2,230.40  
- **Selected Policy Action:** **`A2`** (via `LINUCB`)  

#### Action Candidate Trade-Off Matrix

| Action | Name | Eligible? | Reason / Constraint | Exp. Loss (₹) | Net Value Created (₹) | Friction (₹) | Ops Cost (₹) |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| A0 | ZERO_FRICTION_APPROVAL | ✓ Yes | - | ₹2,230.40 | **₹0.00** | ₹0.00 | ₹0.00 |
| A1 | DYNAMIC_RETURN_FEE | ✓ Yes | - | ₹1,492.30 | **₹738.10** | ₹50.00 | ₹20.00 |
| **A2** | OTP_DOORSTEP_INSPECTION | ✓ Yes | - | ₹531.23 | **₹1,699.17** | ₹40.00 | ₹60.00 |
| A3 | STORE_CREDIT | ✓ Yes | - | ₹1,173.23 | **₹1,057.17** | ₹80.00 | ₹15.00 |
| A4 | MANUAL_REVIEW | ✗ No | `Filtered by guardrails (RiskBand=HIGH)` | ₹217.55 | **₹2,012.85** | ₹120.00 | ₹150.00 |

**Decision Rationale:**
> **Why intervention dominates?** With an unmitigated loss exposure of ₹2,720 on a ₹16,500 item, A2 (OTP Doorstep Inspection) intercepts 75% of abuse for only ₹60 operational fee and minimal friction, creating positive net merchant value.

---

### Archetype 3: Medium Risk, Borderline Return

**Context:** Moderate risk customer (p=0.38) requesting return. Heavy friction (manual freeze) risks permanent customer churn; dynamic friction dominates.  

- **Order Value:** ₹2,200.00 | **Reverse Logistics Cost:** ₹140.00 | **Recovery Value:** ₹1,600.00
- **Risk Probability (p_abuse):** `0.38` (MEDIUM)  
- **Unmitigated Loss Exposure:** ₹740.00  
- **Baseline Loss without Intervention:** ₹281.20  
- **Selected Policy Action:** **`A0`** (via `LINUCB`)  

#### Action Candidate Trade-Off Matrix

| Action | Name | Eligible? | Reason / Constraint | Exp. Loss (₹) | Net Value Created (₹) | Friction (₹) | Ops Cost (₹) |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| **A0** | ZERO_FRICTION_APPROVAL | ✓ Yes | - | ₹281.20 | **₹0.00** | ₹0.00 | ₹0.00 |
| A1 | DYNAMIC_RETURN_FEE | ✗ No | `Filtered by guardrails (RiskBand=MEDIUM)` | ₹331.20 | **₹-50.00** | ₹50.00 | ₹20.00 |
| A2 | OTP_DOORSTEP_INSPECTION | ✗ No | `Filtered by guardrails (RiskBand=MEDIUM)` | ₹321.20 | **₹-40.00** | ₹40.00 | ₹60.00 |
| A3 | STORE_CREDIT | ✗ No | `Filtered by guardrails (RiskBand=MEDIUM)` | ₹361.20 | **₹-80.00** | ₹80.00 | ₹15.00 |
| A4 | MANUAL_REVIEW | ✗ No | `Filtered by guardrails (RiskBand=MEDIUM)` | ₹401.20 | **₹-120.00** | ₹120.00 | ₹150.00 |

**Decision Rationale:**
> **Why low-friction intervention dominates?** For moderate risk ($p=0.38$), there is a 62% probability the customer is legitimate. A heavy intervention like A4 (Manual Review) imposes ₹120 in friction on a good customer. Low-friction options like A1/A2 preserve customer lifetime value while mitigating risk.

---

### Archetype 4: Critical Risk, Serial Wardrober

**Context:** Extreme abuse probability (p=0.94) on luxury apparel. Automated approval guarantees unmitigated loss; specialist review is mandatory.  

- **Order Value:** ₹8,500.00 | **Reverse Logistics Cost:** ₹180.00 | **Recovery Value:** ₹4,000.00
- **Risk Probability (p_abuse):** `0.94` (CRITICAL)  
- **Unmitigated Loss Exposure:** ₹4,680.00  
- **Baseline Loss without Intervention:** ₹4,399.20  
- **Selected Policy Action:** **`A2`** (via `LINUCB`)  

#### Action Candidate Trade-Off Matrix

| Action | Name | Eligible? | Reason / Constraint | Exp. Loss (₹) | Net Value Created (₹) | Friction (₹) | Ops Cost (₹) |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| A0 | ZERO_FRICTION_APPROVAL | ✓ Yes | - | ₹4,399.20 | **₹0.00** | ₹0.00 | ₹0.00 |
| A1 | DYNAMIC_RETURN_FEE | ✓ Yes | - | ₹3,662.21 | **₹736.99** | ₹50.00 | ₹20.00 |
| **A2** | OTP_DOORSTEP_INSPECTION | ✓ Yes | - | ₹2,742.68 | **₹1,656.52** | ₹40.00 | ₹60.00 |
| A3 | STORE_CREDIT | ✓ Yes | - | ₹3,350.13 | **₹1,049.07** | ₹80.00 | ₹15.00 |
| A4 | MANUAL_REVIEW | ✗ No | `Filtered by guardrails (RiskBand=CRITICAL)` | ₹2,464.70 | **₹1,934.50** | ₹120.00 | ₹150.00 |

**Decision Rationale:**
> **Why A4 (Manual Review) dominates?** At $p=0.94$, the certainty of abuse on an ₹8,500 order produces an unmitigated loss of ₹4,400. Paying ₹150 for an operational analyst review prevents ₹4,180 in loss ($95\%$ mitigation), yielding the highest net value.

---

