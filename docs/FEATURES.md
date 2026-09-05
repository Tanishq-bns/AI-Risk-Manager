# FEATURES.md — AI Risk Manager Feature Dictionary

**Document Version:** 1.0  
**Phase:** Phase 3 — Feature Engineering & Data Pipeline  
**Point-in-Time Principle:** Every feature below is evaluated strictly at `decision_timestamp` ($T_{\text{decision}} = \text{requested\_at}$). Information occurring after $T_{\text{decision}}$ is strictly prohibited.

---

## 1. Feature Specifications (17 Production Features)

| # | Feature Name | Type | Unit / Format | Point-in-Time Rule | Allowed Range | Missing Value Strategy | Model Tier Usage | Description & Calculation |
|---|---|---|---|---|---|---|---|---|
| **1** | `customer_id_hash` | `str` | SHA-256 string | Available at creation | 16–64 char hex | Required; reject if missing | Trace / Entity Key | Pseudonymous customer identity hash. Used for grouping and entity joins; not used as an numeric feature. |
| **2** | `order_value` | `float` | INR (₹) | Transaction time | $(0, \infty)$ | Required; reject if $\le 0$ | Tier 0, Tier 1, Tier 2, Reward | Gross monetary value of the order being returned. |
| **3** | `product_category` | `str` | Category Enum | Transaction time | Categorical (APPAREL, FOOTWEAR, ELECTRONICS, BEAUTY, HOME, ACCESSORIES) | Impute with modal category `APPAREL` | Tier 0, Tier 1, Tier 2, LinUCB | Merchandise classification of the returned product. |
| **4** | `payment_method` | `str` | PREPAID / COD | Transaction time | Binary category | Impute `PREPAID` | Tier 0, Tier 1, Tier 2 | Method used to settle original order. COD carries distinct abuse risk. |
| **5** | `cod_flag` | `bool` | True / False | Transaction time | Boolean | Derived from `payment_method == COD` | Tier 0, Tier 1, Tier 2 | Binary indicator for Cash On Delivery fulfillment. |
| **6** | `customer_order_count` | `int` | Integer count | $t_{\text{order}} < T_{\text{decision}}$ | $[0, \infty)$ | Default 0 | Tier 0, Tier 1, Tier 2 | Total historical orders completed by this customer strictly before this return request. |
| **7** | `customer_return_count` | `int` | Integer count | $t_{\text{return}} < T_{\text{decision}}$ | $[0, \text{order\_count}]$ | Default 0 | Tier 0, Tier 1, Tier 2 | Total prior return requests filed by this customer. The current request is NEVER counted. |
| **8** | `customer_return_rate` | `float` | Ratio | $t < T_{\text{decision}}$ | $[0.0, 1.0]$ | 0.0 if `customer_order_count == 0` | Tier 0, Tier 1, Tier 2, LinUCB | $\frac{\text{customer\_return\_count}}{\text{customer\_order\_count}}$. Primary velocity signal for serial abuse. |
| **9** | `days_since_purchase` | `int` | Elapsed days | Order date to Return date | $[0, 365]$ | Max(0, $T_{\text{decision}} - t_{\text{order}}$) | Tier 0, Tier 1, Tier 2 | Elapsed calendar days between purchase and return filing. Policy edge filings (>12 days) correlate with wardrobing. |
| **10** | `prior_return_value` | `float` | INR (₹) | $t_{\text{return}} < T_{\text{decision}}$ | $[0.0, \infty)$ | Default 0.0 | Tier 0, Tier 1, Reward | Cumulative rupee value of all items previously returned by this customer. |
| **11** | `prior_return_frequency` | `float` | Returns / 30 days | $t < T_{\text{decision}}$ | $[0.0, \infty)$ | Default 0.0 | Tier 0, Tier 1 | Rolling return velocity normalized to a 30-day window: $(\frac{\text{returns}}{\text{tenure\_days}}) \times 30$. |
| **12** | `item_category_return_rate` | `float` | Category baseline | Pre-computed aggregate | $[0.0, 1.0]$ | Category lookup default | Tier 0, Tier 1 | Industry/merchant baseline return rate for the product category. Prevents penalizing normal apparel returns. |
| **13** | `return_reason` | `str` | Text | Captured at return filing | Free text string | Default "Unspecified" | Agents only (as data) | Customer-submitted reason. Passed to LangGraph as untrusted data; not fed into raw ML models. |
| **14** | `delivery_distance_bucket` | `str` | Zone | Delivery address | LOCAL, REGIONAL, NATIONAL | Default `REGIONAL` | Tier 0, Tier 1 | Courier logistics distance tier. Determines reverse logistics costs. |
| **15** | `reverse_logistics_cost` | `float` | INR (₹) | Decision time | $[50.0, 1000.0]$ | Estimated by distance bucket | Tier 0, Tier 1, Reward, LinUCB | Projected courier cost to pick up and inspect the returned unit. |
| **16** | `estimated_item_recovery_value` | `float` | INR (₹) | Decision time | $[0.0, \infty)$ | Estimated by category factor | Tier 0, Tier 1, Reward | Anticipated restock/resale value of the item if returned undamaged minus repackaging. |
| **17** | `historical_abuse_signal` | `float` | Risk score | $t_{\text{outcome}} < T_{\text{decision}}$ | $[0.0, 1.0]$ | Default 0.0 | Tier 0, Tier 1, Tier 2 | Proportion of customer's prior returns confirmed as abusive or fraudulent. |

---

## 2. Post-Outcome Target Labels (NOT Model Inputs)

| Label Field | Type | Point-in-Time Availability | Description |
|---|---|---|---|
| `confirmed_abuse` (`is_return_abuse`) | `bool` | Post-inspection / Post-refund | **Target Label.** Ground-truth indicator whether the return was abusive (wardrobing, switch, serial abuse, COD fraud). |
| `actual_loss` | `float` (INR) | Post-resolution | Realized financial loss suffered by the merchant (restock loss + reverse shipping). Used to train the Reward Model. |
| `refund_completed_at` | `datetime` | Post-resolution | Timestamp when the refund was finalized or rejected. Zero access at inference time. |

---

## 3. Strict Non-Leakage & Safety Verification

1. **Entity Separation:** `FeatureVector` and `OutcomeLabel` share zero common field names (`set(FeatureVector) & set(OutcomeLabel) == empty`).
2. **Temporal Masking:** In all aggregations, the filter `WHERE event_timestamp < decision_timestamp` is strictly applied.
3. **Current Event Exclusion:** The return event being evaluated is never counted in `customer_return_count` or `prior_return_value`.
4. **Privacy & Fairness:** No protected attributes (gender, religion, caste, marital status) and no raw PII (names, phone numbers, emails) exist in the feature set.
