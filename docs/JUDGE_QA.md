# Technical Judge Q&A & Defense Compendium — AI Risk Manager

This document provides concise, technical, and brutally honest answers to the 25 most challenging architectural, machine learning, and operational questions that a senior reviewer, ML scientist, or hackathon judge could pose.

---

### 1. Why XGBoost for Tier 0 Risk Scoring?
**Answer:** Tabular financial data is dominated by heterogeneous feature distributions, non-linear feature interactions, and discrete thresholds (e.g. days since purchase, prior return counts). Gradient boosted decision trees (specifically XGBoost) consistently outperform deep architectures on tabular tasks while executing within **$12.5\text{ ms}$** on CPU with zero GPU dependencies.

### 2. Why is Probability Calibration Mandatory?
**Answer:** Ranking metrics like ROC-AUC only measure sorting quality, not probability fidelity. In our architecture, Phase 5 directly multiplies $p_{\text{return\_abuse}}$ into financial loss expectations ($\mathbb{E}[\text{Loss}] = p \cdot \text{Loss Exposure}$). A model that outputs $0.80$ for cases that only fail $40\%$ of the time will over-penalize legitimate shoppers, destroying merchant margin through collateral friction. Calibration ensures $p$ is a true empirical probability.

### 3. Why Isotonic Regression over Platt Scaling (Sigmoid)?
**Answer:** Platt scaling assumes a parametric sigmoid shape for log-odds, which fails when model miscalibration is asymmetric or concentrated in extreme probability tails. Isotonic Regression is non-parametric and rank-preserving, fitting a monotonic step function that reduced our Expected Calibration Error (ECE) from **$0.0761$** down to **$0.0035$** ($95.4\%$ reduction).

### 4. Why Isolation Forest for Tier 1?
**Answer:** Unsupervised anomaly detection does not rely on labeled return fraud data. When new merchants onboard or zero-day syndicate fraud patterns emerge without historical labels, Isolation Forest scores isolation depth directly from feature geometry, providing an active statistical fallback before supervised models can be retrained.

### 5. Why Not Deep Learning / Neural Networks for Risk Scoring?
**Answer:** Tabular risk decisioning requires sub-15ms deterministic inference, explicit tree-based feature interpretability, and robust handling of sparse categorical inputs. Deep neural nets require extensive hyperparameter tuning, GPU acceleration, and offer worse inductive bias on tabular distributions while adding substantial operational latency.

### 6. Why Not Let an LLM Score the Risk Probability Directly?
**Answer:** LLMs are non-deterministic, hallucinatory, vulnerable to prompt injection, and orders of magnitude too slow ($800\text{--}2,500\text{ ms}$ vs. our $12\text{ ms}$ ML pass). Financial fraud scoring demands strict numerical repeatability, verifiable calibration, and formal auditability that autoregressive language models cannot guarantee.

### 7. Why Use LLM-Powered Agents at All?
**Answer:** While LLMs are disqualified from numerical authority, they excel as passive contextual sentinels: synthesizing unstructured return reasons, detecting adversarial prompt injections, checking compliance against high-level policy rules, and generating explainable summaries for human operators in operations review queues.

### 8. Why Can't Agents Change the Algorithmic Decision?
**Answer:** Security and regulatory compliance. If an agent could modify $p_{\text{return\_abuse}}$ or alter the selected intervention action, an attacker could manipulate the outcome via indirect prompt injection in the customer notes. By sealing Phase 4 and Phase 5 authority, the decision engine remains impervious to prompt manipulation.

### 9. Why LinUCB for Action Selection?
**Answer:** Return intervention is a contextual multi-armed bandit problem. LinUCB balances exploitation (choosing the action with highest predicted net merchant value) with bounded exploration under parameter uncertainty ($\alpha \sqrt{x^\top A^{-1} x}$), adapting to changing merchant cost dynamics without requiring off-policy reinforcement learning replay buffers.

### 10. Why Not Full Reinforcement Learning (RL)?
**Answer:** Full sequential RL (like DQN or PPO) assumes state transitions where an action changes future environment states. In retail returns, each return request is an episodic decision conditioned on customer history. Contextual bandits solve this formulation without credit assignment instability or massive sample inefficiency.

### 11. How Do You Prevent Customer Discrimination?
**Answer:** Protected demographic attributes (gender, age, race, religion, location demographics) are strictly excluded from the `FeatureVector` schema. Features are limited strictly to transactional, behavioral, and logistical variables (e.g. order value, delivery distance bucket, return frequency). Furthermore, customer friction guardrails protect established loyal shoppers from intrusive interventions.

### 12. How Do You Prevent Prompt Injection?
**Answer:** Defense-in-depth:
1. **Quarantine:** Untrusted customer text never enters system prompts as raw instructions; it is passed strictly as structured data context.
2. **Keyword & Regex Sentinel:** Scans for jailbreak patterns (`"ignore previous"`, `"system prompt"`, `"administrator"`, `<script>`).
3. **Architectural Decoupling:** Even if an injection bypassed LLM filters, Phase 4 scoring and Phase 5 action selection do not consume LLM outputs.

### 13. What Happens if Google Gemini is Down or Times Out?
**Answer:** The synchronous risk scoring path ($103\text{ ms}$ P95) is completely decoupled from Gemini. Gemini runs asynchronously in Phase 6. If Gemini fails or times out, the system falls back to `AgentProvider.DETERMINISTIC_FALLBACK` in under $1\text{ ms}$, logging `PROVIDER_UNAVAILABLE` while the merchant response returns unaffected.

### 14. What Happens if Redis / Cache is Unavailable?
**Answer:** The caching layer uses a fail-open pattern backed by in-process memory caching. If Redis disconnects, feature retrieval and idempotency checks seamlessly degrade to direct database queries without throwing 500 errors. Verified in Failure Drill 4.

### 15. What Happens if the Database is Degraded or Down?
**Answer:** Synchronous scoring continues in memory using client-provided features. The resulting decision is buffered in an in-memory fallback queue for asynchronous retry persistence once connectivity restores, preventing merchant checkout or return portal blockages. Verified in Failure Drill 5.

### 16. What Happens if a Model Artifact is Corrupted?
**Answer:** The cascade detects corrupt joblib binaries or checksum mismatches and immediately routes to Tier 2 Deterministic Rules ($0.08\text{ ms}$ latency), ensuring continuous zero-downtime scoring. Verified in Failure Drills 1 & 2.

### 17. Why is the Decision Economically Aware?
**Answer:** Because binary fraud detection solves the wrong problem. A merchant does not care if a return is $60\%$ suspicious if stopping it costs more than the item value. Phase 5 evaluates:
$$\mathbb{E}[V_{\text{net}}] = \Delta \text{Loss} - (1 - p) \cdot C_{\text{friction}} - p \cdot C_{\text{ops}}$$
ensuring that interventions are only deployed when net recovery mathematically exceeds friction and operational costs.

### 18. Why Not Simply Block High-Risk Returns?
**Answer:** Our offline Policy Ablation (`reports/POLICY_ABLATION.md`) proves that fixed risk threshold blocking incurs **₹12,450** in operational reviews and **₹48.62** in customer friction on borderline accounts, spending ₹150 of human review time to prevent an ₹80 loss on low-ticket items. Surgical economic optimization achieves superior net value while preserving customer retention.

### 19. How Was Calibration Evaluated?
**Answer:** Binned reliability curves and Expected Calibration Error (ECE) were computed across decile buckets on an untouched held-out test split (`data/test.csv`, $N=170$) that was never seen during XGBoost training or isotonic fitting. The calibrated ECE is **$0.0035$**, well within the $<0.0500$ production benchmark.

### 20. What Happens Under Distribution Drift?
**Answer:** When retail seasons shift (e.g. Diwali festive sales surge return volume), feature drift triggers drift alerts. Because the architecture includes an unsupervised anomaly detector (Tier 1) and rule-based guardrails (Tier 2), the system degrades gracefully while drift reports flag the need for model recalibration.

### 21. Is This System Production-Ready?
**Answer:** The core algorithmic engine, authority boundaries, fallback cascades, and security models are production-grade. However, deploying to enterprise scale requires provisioning external Redis/PostgreSQL clusters and configuring merchant-specific webhooks rather than using local in-process SQLite.

### 22. What are the Biggest Honest Limitations?
**Answer:**
1. **Synthetic Training Data:** Trained on 2,500 synthetically generated Indian retail return profiles.
2. **Offline Calibration:** Calibration is frozen; live production requires streaming isotonic updates.
3. **Tail Latency Spikes:** Python GC and SQLite disk commits produce occasional P99 latency spikes up to $280\text{ ms}$ on Windows.

### 23. Why Synthetic Data Instead of Real Merchant Data?
**Answer:** Real merchant transaction and fraud dispute logs contain sensitive PII, cardholder data, and proprietary merchant financials protected by strict NDAs and DPDP regulations. Synthetic generation allowed us to publish an open, fully reproducible repository with documented ground truth.

### 24. How Would This Scale to 10,000 Requests/Second?
**Answer:**
1. Stateless horizontal scaling of FastAPI worker containers behind an AWS ALB or Cloudflare.
2. Feature caching via high-throughput Redis Cluster or DragonflyDB.
3. Asynchronous agent passes and audit persistence offloaded to Apache Kafka / Redpanda worker consumers.
4. Model scoring ported to ONNX Runtime with C++ bindings for $<2\text{ ms}$ scoring.

### 25. How Would a Real Merchant Deploy This with Razorpay?
**Answer:** A merchant configures Razorpay Webhooks (`order.paid`, `refund.created`) or embeds the AI Risk Manager REST API (`/api/v1/risk/score`) directly into their returns portal. When a shopper clicks "Request Return", the frontend queries the endpoint synchronously ($\sim 100\text{ ms}$) to dynamically display appropriate return options (instant refund, doorstep OTP requirement, or return fee) based on the assigned policy action.
