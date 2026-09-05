# AI Risk Manager — API Specification (Phase 7)

This document provides the complete, authoritative API reference for the **AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel** application.

---

## 1. Architectural Overview & Authority Principles

The API layer bridges high-throughput checkout and return workflows to the underlying numerical scoring, economic policy, and asynchronous sentinel subsystems:

1. **Phase 4 Scoring Authority:** `p_return_abuse`, `risk_band`, `scoring_source`, and `fallback_tier` are calculated exclusively by the Phase 4 ML cascade (Tier 0 XGBoost + Isotonic Calibration $\to$ Tier 1 Isolation Forest $\to$ Tier 2 Rules Engine). The API cannot fabricate or modify these values.
2. **Phase 5 Economic Authority:** `expected_loss`, `expected_net_value`, candidate action evaluations, and the selected `Action` (A0–A4) are determined strictly by the economic model and LinUCB policy engine with guardrail enforcement.
3. **Phase 6 Multi-Agent Asynchrony:** LangGraph agents (Investigator, Verifier, Action Orchestrator) run **out-of-band** or asynchronously. They **never block** the synchronous scoring path and **cannot mutate** authoritative Phase 4/5 outputs.
4. **Append-Only Immutability:** The only mechanism permitted to modify an operational action is an authorized human override (`POST /api/v1/review/{id}/override`), which appends an immutable `policy.override.v1` audit record.

---

## 2. Universal Envelopes & Headers

### Correlation & Timing Headers
Every HTTP request and response is tagged for end-to-end tracing:
- `X-Request-ID`: Client-provided or server-generated UUID tracing the lifecycle of the request.
- `X-Response-Time-Ms`: Server processing duration in milliseconds.

### Error Envelope
Standardized error responses protect against stack trace leakage while providing structured diagnostic error codes:
```json
{
  "error": {
    "code": "DECISION_NOT_FOUND",
    "message": "Risk decision b1e8992c-6330-4e20-9289-e13788229f3d not found",
    "request_id": "99f43057-0a12-4217-b714-c4ba52077e64"
  }
}
```

---

## 3. API Endpoints

### 3.1 Health & Readiness
#### `GET /api/v1/health`
Inspects operational health of core system dependencies without throwing unhandled exceptions if optional components are degraded.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "service": "ai-risk-manager",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-09-04T10:45:00.123456Z",
  "dependencies": {
    "database": "healthy",
    "ml_models": "healthy",
    "agent_layer": "enabled"
  }
}
```

---

### 3.2 Real-Time Risk Scoring
#### `POST /api/v1/risk/score`
The primary synchronous endpoint. Ingests return/checkout events, constructs the point-in-time feature vector, executes the Phase 4 cascade and Phase 5 policy engine, persists records, and enqueues Phase 6 agent investigation asynchronously.

**Headers:**
- `Content-Type: application/json`
- `X-Request-ID`: (Optional) Client correlation UUID.

**Request Body:**
```json
{
  "customer_id_hash": "cust_8281aef91204",
  "idempotency_key": "idemp_ord_9821_ret_01",
  "order_value": 3499.0,
  "product_category": "APPAREL",
  "payment_method": "PREPAID",
  "cod_flag": false,
  "return_reason": "Size does not fit properly",
  "days_since_purchase": 4,
  "customer_order_count": 14,
  "customer_return_count": 1,
  "customer_return_rate": 0.071,
  "prior_return_value": 850.0,
  "prior_return_frequency": 0.25,
  "delivery_distance_bucket": "REGIONAL",
  "reverse_logistics_cost": 65.0,
  "estimated_item_recovery_value": 2800.0,
  "historical_abuse_signal": 0.0
}
```

**Response `200 OK`:**
```json
{
  "decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "risk_decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "p_return_abuse": 0.1245,
  "risk_band": "LOW",
  "scoring_source": "XGBOOST",
  "fallback_tier": 0,
  "selected_action": "A0_INSTANT_REFUND",
  "action_name": "Instant Refund / Zero Friction",
  "economic": {
    "expected_loss": 435.63,
    "expected_net_value": 3063.37
  },
  "guardrails_applied": [],
  "candidate_actions": [
    {
      "action": "A0_INSTANT_REFUND",
      "action_name": "Instant Refund",
      "expected_loss": 435.63,
      "expected_net_value": 3063.37,
      "friction_cost": 0.0,
      "operational_cost": 0.0,
      "is_eligible": true,
      "ineligibility_reason": null
    },
    {
      "action": "A1_STANDARD_VERIFICATION",
      "action_name": "Standard Pickup Verification",
      "expected_loss": 450.12,
      "expected_net_value": 3013.88,
      "friction_cost": 35.0,
      "operational_cost": 35.0,
      "is_eligible": true,
      "ineligibility_reason": null
    },
    {
      "action": "A2_OTP_DOORSTEP_INSPECTION",
      "action_name": "OTP Doorstep Inspection",
      "expected_loss": 490.50,
      "expected_net_value": 2933.50,
      "friction_cost": 75.0,
      "operational_cost": 75.0,
      "is_eligible": true,
      "ineligibility_reason": null
    },
    {
      "action": "A3_STORE_CREDIT_DISCOUNT",
      "action_name": "Store Credit",
      "expected_loss": 520.00,
      "expected_net_value": 2929.00,
      "friction_cost": 50.0,
      "operational_cost": 50.0,
      "is_eligible": false,
      "ineligibility_reason": "Disallowed for trusted low-risk customer"
    },
    {
      "action": "A4_DISALLOW_RETURN_ESCALATE",
      "action_name": "Escalate to Human Review",
      "expected_loss": 600.00,
      "expected_net_value": 2749.00,
      "friction_cost": 150.0,
      "operational_cost": 150.0,
      "is_eligible": true,
      "ineligibility_reason": null
    }
  ],
  "agent_status": "PENDING"
}
```

**Idempotency Semantics:**
If a request with an identical `idempotency_key` is submitted within the retention window, the API returns the exact authoritative decision previously committed, without re-scoring or generating duplicate database rows.

---

### 3.3 Decision Details
#### `GET /api/v1/risk/decisions/{decision_id}`
Retrieves the read-only decision record, including point-in-time risk features, ML confidence, economic calculations, and current human review status.

**Response `200 OK`:**
```json
{
  "decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "risk_decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "created_at": "2026-09-04T10:45:00.123456Z",
  "p_return_abuse": 0.1245,
  "risk_band": "LOW",
  "scoring_source": "XGBOOST",
  "fallback_tier": 0,
  "selected_action": "A0_INSTANT_REFUND",
  "action_name": "Instant Refund / Zero Friction",
  "economic": {
    "expected_loss": 435.63,
    "expected_net_value": 3063.37
  },
  "candidate_actions": [...],
  "guardrails_applied": [],
  "agent_status": "COMPLETED",
  "requires_human_review": false,
  "manual_override_applied": false
}
```

#### `GET /api/v1/risk/decisions`
Lists recent decisions for administrative and audit inspection (supports `limit` and `offset` query parameters).

---

### 3.4 Policy Catalog & Inspection
#### `GET /api/v1/policy/actions`
Returns the authoritative candidate intervention catalog, including economic cost defaults, customer friction levels, and active guardrail definitions.

#### `GET /api/v1/policy/{decision_id}`
Returns the policy state transition history for a decision, including original action, latest action, selected_by, and reason.

---

### 3.5 Asynchronous Agent Operations
#### `POST /api/v1/agents/run/{decision_id}`
Executes the Phase 6 LangGraph multi-agent workflow on-demand for an existing decision.

**Response `200 OK`:**
```json
{
  "decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "agent_status": "COMPLETED",
  "provider": "DETERMINISTIC_FALLBACK",
  "is_llm_generated": false,
  "fallback_reason": null,
  "requires_human_review": false,
  "final_agent_recommendation": "EXECUTE_A0_AUTOMATED"
}
```

#### `GET /api/v1/agents/{decision_id}`
Returns granular structured findings from each specialist agent:
- **Investigator:** Key risk factors, mitigating factors, evidence quality, adversarial input detection flag.
- **Verifier:** 10 deterministic validation checks (order value checks, risk band monotonicity, guardrail consistency, etc.) with explicit PASS/FAIL/WARNING statuses.
- **Action Orchestrator:** Operational routing mode (`AUTOMATED`, `MANUAL_REVIEW_QUEUE`, `ESCALATED`), blockers, and execution guidance.
- **Provenance:** LLM model name, provider, and execution timestamp.

---

### 3.6 Chronological Audit Timeline
#### `GET /api/v1/audit/{decision_id}`
Returns the tamper-evident chronological event stream for a decision. All PII is redacted.

**Response `200 OK`:**
```json
{
  "risk_decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "total_events": 3,
  "timeline": [
    {
      "event_id": "31b20a4b-fc54-47b2-a400-3488737c35e8",
      "event_type": "risk.scored.v1",
      "timestamp": "2026-09-04T10:45:00.123456Z",
      "payload": {
        "p_return_abuse": 0.1245,
        "risk_band": "LOW",
        "scoring_source": "XGBOOST",
        "fallback_tier": 0
      }
    },
    {
      "event_id": "834c9f1e-f3ba-4ef3-a309-88094f31c201",
      "event_type": "policy.decision.v1",
      "timestamp": "2026-09-04T10:45:00.145000Z",
      "payload": {
        "action_selected": "A0_INSTANT_REFUND",
        "expected_loss": 435.63,
        "expected_net_value": 3063.37
      }
    },
    {
      "event_id": "99ea78b2-3c12-4ee0-82a1-2139049a88bc",
      "event_type": "agent.workflow.completed.v1",
      "timestamp": "2026-09-04T10:45:00.220000Z",
      "payload": {
        "provider": "DETERMINISTIC_FALLBACK",
        "requires_human_review": false,
        "operational_recommendation": "EXECUTE_A0_AUTOMATED"
      }
    }
  ]
}
```

---

### 3.7 Human Review & Manual Override
#### `GET /api/v1/review/queue`
Returns all decisions flagged for human review (e.g. Action A4, verifier failures, or high-risk conflicts).

#### `POST /api/v1/review/{decision_id}/override`
Allows an authorized risk operator to change an operational intervention. Creates an immutable `policy.override.v1` audit entry.

**Request Body:**
```json
{
  "operator_id": "operator_sarah_102",
  "reason": "Customer verified via phone call; package unopened with seal intact.",
  "new_action": "A0"
}
```

**Response `200 OK`:**
```json
{
  "decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "risk_decision_id": "b1e8992c-6330-4e20-9289-e13788229f3d",
  "previous_action": "A2_OTP_DOORSTEP_INSPECTION",
  "new_action": "A0",
  "operator_id": "operator_sarah_102",
  "reason": "Customer verified via phone call; package unopened with seal intact.",
  "audit_event_id": "2d8f9901-b21a-4663-8822-e1047712ba9c"
}
```

---

### 3.8 Demo Presets
#### `GET /api/v1/demo/presets`
Returns standard test scenarios for immediate evaluation in the browser dashboard:
1. `legitimate_low_risk` (Low return rate, high order count $\to$ A0)
2. `suspicious_returner` (Elevated return frequency $\to$ A2 OTP Doorstep)
3. `serial_returner` (High abuse signal and return rate $\to$ A2/A3)
4. `critical_human_review` (Severe repeat returns and value $\to$ A4 Manual Review)
5. `prompt_injection_defense` (Adversarial jailbreak payload in `return_reason`)

---

### 3.9 Observability
#### `GET /metrics`
Returns Prometheus exposition format metrics tracking request throughput, status codes, and service availability.
