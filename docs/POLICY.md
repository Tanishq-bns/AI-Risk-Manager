# POLICY.md — AI Risk Manager Intervention Policy & Guardrail Engine

**Document Version:** 1.0  
**Phase:** Phase 5 — Economic Outcome Model & Intervention Policy Foundation  
**Contextual Bandit:** Disjoint LinUCB with Economic Value Priors  
**Primary Invariant:** Authoritative $p_{\text{return\_abuse}}$ comes exclusively from Phase 4 and is never modified.

---

## 1. System Overview

The Intervention Policy Engine acts as the decision sentinel for return requests. It consumes:
1. **Calibrated Abuse Probability ($p_{\text{return\_abuse}}$)**: Fixed and immutable from Phase 4.
2. **Assigned Risk Band**: `LOW`, `MEDIUM`, or `HIGH`.
3. **Point-in-Time Feature Vector**: 17 domain features from Phase 3.
4. **Economic Predictions**: Projected financial net value from the Random Forest reward model.

It selects the optimal intervention action $a \in \{A0, A1, A2, A3, A4\}$ that maximizes merchant margin preservation while strictly bounding customer friction and operational overhead.

```
       Phase 4 Scorer (Authoritative p_return_abuse)
                          │
                          ▼
            Economic Predictor (Random Forest)
             [Calculates Net Values for A0-A4]
                          │
                          ▼
                 Policy Guardrails
              [Filters Ineligible Actions]
                          │
                          ▼
               Contextual Bandit (LinUCB)
           [Scores Actions: θ_a^T x + α √(x^T A_a^-1 x)]
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
      Valid Decision             Degradation/Failure
    (ActionSelector.LINUCB)    (ActionSelector.RULES)
            │                           │
            └─────────────┬─────────────┘
                          │
                          ▼
            Auditable PolicyDecisionContext
            (Intervention, PolicyDecision, AuditEvent)
```

---

## 2. LinUCB Contextual Bandit Formulation

The policy engine implements a disjoint LinUCB algorithm (Li et al., 2010) where each action $a \in \mathcal{A}$ maintains an independent ridge regression model over context vectors $x \in \mathbb{R}^d$ ($d=10$).

### 2.1 Context Vector Construction ($d=10$)
For each evaluation, the context vector $x$ captures normalized economic and customer behavior signals:
1. `p_return_abuse`: Calibrated risk probability $[0.0, 1.0]$
2. `order_value_norm`: $\min(1.0, \text{order\_value} / 10000.0)$
3. `return_rate`: Customer return rate $[0.0, 1.0]$
4. `tenure_norm`: $\min(1.0, \text{days\_since\_purchase} / 30.0)$
5. `cod_flag`: $1.0$ if COD, else $0.0$
6. `reverse_logistics_norm`: $\min(1.0, \text{reverse\_logistics\_cost} / 500.0)$
7. `prior_returns_norm`: $\min(1.0, \text{customer\_return\_count} / 10.0)$
8. `risk_band_low`: Binary indicator for `LOW` risk band
9. `risk_band_medium`: Binary indicator for `MEDIUM` risk band
10. `risk_band_high`: Binary indicator for `HIGH` risk band

### 2.2 Action Scoring & Exploration Parameter
For each candidate action $a$:
$$\hat{r}_a = \theta_a^T x = (A_a^{-1} b_a)^T x$$
$$\text{bonus}_a = \alpha \sqrt{x^T A_a^{-1} x}$$
$$\text{Score}(a) = \hat{r}_a + \text{bonus}_a$$

Where:
- $A_a \in \mathbb{R}^{d \times d}$: Design matrix initialized to identity $I_d$ (ridge parameter $\lambda = 1.0$).
- $b_a \in \mathbb{R}^d$: Response vector initialized to $0_d$.
- $\alpha$: Exploration parameter (default: $\alpha = 0.25$).

### 2.3 Exploration Safety Controls
- **Default Invariant:** `exploration_enabled = False`.
- In standard production mode, $\text{bonus}_a \equiv 0.0$ and actions are chosen purely by expected reward $\hat{r}_a$ seeded with economic net value priors.
- When offline experimentation enables exploration, it is strictly restricted to actions passing all hard policy guardrails.

---

## 3. Reward Formulation (Prompt §10)

The reward function monetizes the holistic trade-off between merchant loss mitigation, customer friction, and operational costs:

$$\text{Reward}(a \mid x) = \text{NetMarginSaved}(a \mid x) - \text{FrictionCost}(a) - \text{OperationalCost}(a)$$

Where:
- $\text{NetMarginSaved}(a \mid x) = \text{UnmitigatedLoss}(x) \cdot \text{MitigationRate}(a)$
- Friction and operational costs are penalizing terms.
- A high-friction action ($A4$ or $A3$) is penalized unless the unmitigated loss is large enough to warrant the customer inconvenience.

---

## 4. Hard Policy Guardrails (Safety Sentinel)

Before any action is considered by LinUCB, it must pass a suite of non-negotiable deterministic guardrails:

| Rule Code | Guardrail Name | Condition / Enforcement | Ineligible Actions |
|---|---|---|---|
| **G01** | Value Threshold | Orders under INR 100 cannot absorb intervention operational costs. | Disallows $A1, A2, A3, A4$; forces $A0$. |
| **G02** | Risk Band Floor | `RiskBand.LOW` customers must receive frictionless experience. | Disallows $A1, A2, A3, A4$; forces $A0$. |
| **G03** | Human Review Safety | `A4` (`MANUAL_REVIEW`) requires human approval; prohibited in automated execution. | Disallows $A4$ if `is_automated == True`. |
| **G04** | Operational Net Value | An intervention is disallowed if its expected net value is negative ($\text{ExpectedNetValue} < 0$). | Disallows non-profitable interventions. |
| **G05** | Category Constraints | Perishable/intimate products (e.g. `BEAUTY`) cannot be restocked after inspection. | Disallows $A2$ on `BEAUTY` category. |

If all intervention actions are filtered out by guardrails, $A0$ (`ZERO_FRICTION_APPROVAL`) is guaranteed to remain eligible as the universal safe default.

---

## 5. Deterministic Safe Fallback Strategy (Prompt §13)

If the economic model, LinUCB, or the feature pipeline encounters an unexpected error or numerical anomaly, the system degrades safely to `DeterministicPolicyFallback`:

```
                    Failure Detected (LinUCB / Model Error)
                                       │
                                       ▼
                     Fallback Step 1: Risk Band Mapping
                       LOW    ───► Select A0 (Zero Friction)
                       MEDIUM ───► Select A1 (Dynamic Return Fee)
                       HIGH   ───► Select A2 (OTP Doorstep Inspection)
                                       │
                                       ▼
                      Fallback Step 2: Automation Check
                      If A4 was mapped and is_automated=True:
                            Downgrade to A2
                                       │
                                       ▼
                     Fallback Step 3: Eligibility Verify
                    Verify selected action is within eligible set.
                    If not, choose least frictional eligible action.
                                       │
                                       ▼
                       Output: ActionSelector.RULES
```

Every fallback execution is recorded with an explicit machine-readable `fallback_reason`.

---

## 6. Auditability & Persistence (Prompt §16)

Every policy evaluation persists three correlated database records within an atomic transaction:
1. **`interventions`**: The chosen action, expected net value in INR, and selector mechanism.
2. **`policy_decisions`**: Append-only state ledger documenting previous action, effective action, and selector.
3. **`audit_events`**: Immutable structured JSON envelope capturing the full decision context:
   - Authority: $p_{\text{return\_abuse}}$ and `risk_band`.
   - Action Space: Detailed candidate breakdown for all 5 actions.
   - Decision Rationale: Expected net values, LinUCB reward estimate, and exploration bonus.
   - Sentinel Rules: Applied guardrails and fallback reasons.
   - Provenance: Policy model version (`v1.0.0-linucb`) and UTC timestamp.
