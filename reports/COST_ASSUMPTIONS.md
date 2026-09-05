# Authoritative Economic Cost Assumptions & Business Model

**Document Version:** 1.0.0  
**Currency:** Indian Rupee (INR / ₹)  
**Status:** Frozen Economic Contract (TRD.md §D, SPEC.md §14, `risk_manager/domain/actions.py`)  
**Data Scope:** SYNTHETIC / DEMONSTRATION ECONOMIC SIMULATION  

---

## 1. Economic Optimization Objective

The policy engine maximizes net merchant value over the canonical action space $\mathcal{A} = \{A_0, A_1, A_2, A_3, A_4\}$:
$$\max_{a \in \mathcal{A}} \mathbb{E}[V(a)] = \mathbb{E}[L_{\text{no\_action}}] - \mathbb{E}[L(a)] - C_{\text{friction}}(a) - C_{\text{operational}}(a)$$
Where:
- $\mathbb{E}[L_{\text{no\_action}}] = p_{\text{return\_abuse}} \times (\text{order\_value} + C_{\text{reverse\_logistics}} - V_{\text{recovery}})$
- $\mathbb{E}[L(a)] = (1 - \text{mitigation\_rate}(a)) \times \mathbb{E}[L_{\text{no\_action}}]$
- $C_{\text{friction}}(a)$: Customer friction cost reflecting estimated lifetime value (LTV) drop-off.
- $C_{\text{operational}}(a)$: Direct merchant execution cost (courier OTP, inspection fee, manual specialist review).

---

## 2. Canonical Action Cost & Mitigation Matrix

| Action Code | Action Name | Customer Friction Cost ($C_{\text{friction}}$) | Merchant Operational Cost ($C_{\text{operational}}$) | Abuse Loss Mitigation Rate | Status | Rationale / Grounding |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **$A_0$** | `ZERO_FRICTION_APPROVAL` | **₹0.00** | **₹0.00** | **0.0%** | Synthetically Modeled | Unconditional instant return approval. Zero friction, zero extra courier fees, zero abuse loss prevention. |
| **$A_1$** | `DYNAMIC_RETURN_FEE` | **₹50.00** | **₹20.00** | **35.0%** | Synthetically Modeled | Nominal reverse pickup processing fee (₹150–₹300) deducted from refund. Moderate churn friction penalty; deters low-conviction/casual returns. |
| **$A_2$** | `OTP_DOORSTEP_INSPECTION` | **₹40.00** | **₹60.00** | **75.0%** | Synthetically Modeled | Courier physically unboxes, verifies item presence and IMEI/tag, and captures customer OTP at doorstep. High abuse deterrence; minimal customer friction. |
| **$A_3$** | `STORE_CREDIT` | **₹80.00** | **₹15.00** | **50.0%** | Synthetically Modeled | Refund issued as merchant wallet balance rather than cash reversal. Higher friction for customers desiring cash; preserves gross revenue within ecosystem. |
| **$A_4$** | `MANUAL_REVIEW` | **₹120.00** | **₹150.00** | **95.0%** | Synthetically Modeled | Return request suspended for risk operations specialist review prior to courier dispatch. High friction due to 24-48h SLA delay; near-total prevention of confirmed fraud. |

---

## 3. Logistics & Salvage Assumptions

| Parameter | Value Range (₹) | Unit | Status | Rationale |
| :--- | :---: | :---: | :---: | :--- |
| **Reverse Logistics (LOCAL)** | **₹80.00** | ₹ / return | Assumed Industry Standard | Standard 3PL intracity surface reverse courier rate (Delhivery / Shadowfax / Blue Dart). |
| **Reverse Logistics (REGIONAL)** | **₹140.00** | ₹ / return | Assumed Industry Standard | Inter-city state zone reverse shipping with volumetric weight adjustments. |
| **Reverse Logistics (NATIONAL)** | **₹220.00** | ₹ / return | Assumed Industry Standard | Long-haul air / express interstate reverse courier transit. |
| **Restocking / Salvage Recovery** | **10% – 75%** | % of Order Value | Assumed Industry Standard | Fraction of item value recovered if returned undamaged. Electronics: ~75%, Apparel: ~60%, Beauty/Personal: ~10% (non-restockable). |
| **Order Value Distribution** | **₹500 – ₹35,000** | ₹ | Synthetically Simulated | Typical Indian D2C basket sizes across apparel, footwear, and consumer electronics. |

---

## 4. Policy Guardrail Constraints

1. **Mandatory Manual Review ($A_4$) on Critical Risk**: Any transaction with $p_{\text{return\_abuse}} \ge 0.85$ or `CRITICAL` risk band cannot be automatically approved via $A_0$ or $A_1$.
2. **Protection for New / Clean Customers**: Customers with $\le 1$ prior returns cannot receive punitive interventions ($A_3, A_4$) unless absolute risk is extreme.
3. **Minimum Order Value Eligibility**:
   - $A_1$: Order Value $\ge ₹500$
   - $A_2$: Order Value $\ge ₹1,000$
   - $A_3$: Order Value $\ge ₹300$
   - $A_4$: Order Value $\ge ₹1,500$
