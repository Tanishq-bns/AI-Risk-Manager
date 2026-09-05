# Phase 8 — Production Observability, Distributed Tracing & Reliability Hardening

## 1. Executive Summary & Architecture

The **AI Risk Manager** observability subsystem bridges distributed tracing, Prometheus-compatible metrics, structured JSON logging, and security-hardened telemetry into a cohesive operational fabric. It guarantees complete end-to-end visibility across:

$$\text{HTTP Ingress} \longrightarrow \text{Feature Pipeline} \longrightarrow \text{Phase 4 ML Cascade} \longrightarrow \text{Phase 5 Policy Engine} \longrightarrow \text{Phase 6 Multi-Agent Workflow} \longrightarrow \text{Persistence \& Audit}$$

### Non-Negotiable Architectural Rules
1. **Observability is Never a Decision Authority**: Telemetry is strictly passive and observational. It can **NEVER** modify $p_{\text{return\_abuse}}$, risk band, expected loss, expected net value, or selected action.
2. **Scoring Isolation & Zero-Downtime Guarantee**: Failures in OpenTelemetry collectors, Prometheus scrapers, or logging formatters are caught and isolated. The synchronous risk scoring path **NEVER** fails due to observability errors.
3. **Zero-Docker Local Mode Preserved**: Local execution requires zero Docker infrastructure. All tracing and metrics layers operate in zero-overhead no-op or in-memory mode when collectors are unavailable.
4. **Zero PII & Bounded Cardinality**: Strict automated regex and key sanitizers redact emails, phone numbers, credit card tokens, and customer text before entering spans or logs. Prometheus metric labels are bounded to low-cardinality enums.

---

## 2. Distributed Tracing (OpenTelemetry)

Distributed tracing utilizes `opentelemetry-api` and `opentelemetry-sdk` with standard W3C trace context propagation.

### Trace Spans Lifecycle
| Span Name | Operation Captured | Primary Attributes Recorded |
| :--- | :--- | :--- |
| `api.request` | HTTP Ingress / ASGI Middleware | `http.method`, `http.status_code`, `http.target`, `duration_ms` |
| `risk.score` | Synchronous risk orchestration | `scoring_source`, `fallback_tier`, `risk_band`, `duration_ms` |
| `feature_engineering` | Feature validation & vector extraction | `feature_count`, `has_abuse_signal` |
| `phase4.risk_cascade` | XGBoost & Isolation Forest inference | `p_return_abuse`, `risk_band`, `cascade_tier` |
| `phase5.policy_engine` | Economics calculation & LinUCB action | `selected_action`, `action_selector`, `candidate_count` |
| `agent.workflow` | Phase 6 LangGraph graph execution | `provider`, `status`, `duration_ms` |
| `agent.investigator` | Multi-agent customer profiling | `agent_name`, `provider`, `is_llm_generated` |
| `agent.verifier` | Deterministic policy invariant check | `invariants_passed`, `violation_count` |
| `agent.orchestrator` | Action synthesis & dispatch | `final_action`, `requires_human_review` |
| `persistence` | Database transaction commit | `entity`, `operation`, `status` |
| `audit.event` | Append-only event store logging | `event_type`, `decision_id` |
| `human_override` | Authorized manual override | `previous_action`, `new_action` |

### Configuration Variables (`.env`)
```bash
# Distributed Tracing
OTEL_ENABLED=false
OTEL_SERVICE_NAME=ai-risk-manager
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
```

---

## 3. Prometheus Metrics Architecture

Metrics are exposed in the standard Prometheus exposition format at `GET /metrics`.

### Metric Categories & Bounded Labels
- **API Traffic**:
  - `http_requests_total` `[method, endpoint, status_code]`
  - `http_request_duration_seconds` `[method, endpoint]`
  - `http_errors_total` `[endpoint, error_code]`
- **Risk Scoring**:
  - `risk_decisions_total` `[scoring_source, fallback_tier]`
  - `risk_decision_duration_seconds` `[scoring_source]`
  - `risk_fallback_total` `[from_tier, to_tier, reason]`
  - `risk_band_total` `[risk_band]`
- **Policy Engine**:
  - `policy_decisions_total` `[selector, action]`
  - `policy_decision_duration_seconds` `[selector]`
  - `intervention_action_total` `[action, is_eligible]`
- **Multi-Agent Operations**:
  - `agent_workflow_total` `[provider, status]`
  - `agent_workflow_duration_seconds` `[provider]`
  - `agent_failures_total` `[agent_name, error_type]`
  - `agent_fallback_total` `[reason]`
  - `agent_human_review_total` `[reason]`
- **Human Oversight & Governance**:
  - `human_review_required_total` `[trigger_source, action]`
  - `human_override_total` `[previous_action, new_action]`
- **Database & Storage**:
  - `persistence_operation_total` `[entity, operation]`
  - `persistence_failure_total` `[entity, error_code]`
- **Security & Integrity**:
  - `prompt_injection_detected_total` `[agent_name, routing_status]`
  - `ai_risk_manager_up` (Gauge)

> [!IMPORTANT]
> **Cardinality Safeguard**: Never use `decision_id`, `customer_id`, `trace_id`, or `request_id` as Prometheus labels. Dynamic URL path segments are normalized to `{id}` by middleware.

---

## 4. Grafana Dashboards

Preconfigured production dashboards are provisioned in `monitoring/grafana/dashboards/`:

1. **Service Health Dashboard** (`service_health.json`):
   - Ingress throughput (RPS) and HTTP error rate.
   - P50, P95, and P99 latency percentiles against the $\le 150\text{ ms}$ SLA.
   - HTTP status code distribution (2xx, 4xx, 5xx).
   - Database persistence operations and failures.
2. **Risk Decisioning Dashboard** (`risk_decisioning.json`):
   - Decision velocity (decisions per minute).
   - Risk band distribution (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
   - ML inference cascade tier usage (Tier 0 XGBoost vs Tier 1 Isolation Forest fallback).
   - Policy intervention distribution (`A0_APPROVE` to `A4_REJECT`).
   - Policy solver latency and human review queue rate.
3. **Agent Operations Dashboard** (`agent_operations.json`):
   - Multi-agent workflow execution rate and status breakdown.
   - LLM provider utilization (`gemini` vs deterministic fallback).
   - Agent phase latencies: Investigator, Verifier, and Orchestrator.
   - Agent failure rate and timeout rate.
   - Adversarial prompt injection detections count.

---

## 5. Production Prometheus Alerts

Alert definitions are configured in `monitoring/prometheus/alerts.yml`:

| Alert Name | Severity | Condition | Threshold |
| :--- | :--- | :--- | :--- |
| `AIRiskManagerDown` | `critical` | Service heartbeat down | `ai_risk_manager_up == 0` for 1m |
| `HighApiErrorRate` | `critical` | 5xx error rate spike | $> 5\%$ 5xx errors for 2m |
| `HighP95LatencySlaBreach` | `warning` | P95 latency exceeds SLA | $> 150\text{ ms}$ for 3m |
| `RiskScoringFallbackSpike` | `warning` | ML cascade degradation | $> 10\%$ fallback rate for 3m |
| `AgentWorkflowFailureSpike` | `warning` | LangGraph failures | $> 5\%$ agent failures for 3m |
| `GeminiFallbackSpike` | `warning` | LLM timeout or fallback | $> 25\%$ deterministic fallbacks |
| `PersistenceFailureDetected` | `critical` | DB write errors | Rate $> 0$ for 1m |
| `HumanReviewBacklogSpike` | `warning` | Queue surge | Elevated manual escalation rate |

---

## 6. Trace & Log Correlation

Every incoming HTTP request is assigned or preserves a correlation identifier:
- **`X-Request-ID`**: Client or edge gateway request token.
- **`X-Trace-ID`**: OpenTelemetry 32-character hex trace ID.
- **`X-Response-Time-Ms`**: High-resolution response elapsed time in milliseconds.

Structured JSON logs automatically extract and output:
```json
{
  "timestamp": "2026-09-04T12:35:00.123Z",
  "level": "INFO",
  "service": "ai-risk-manager",
  "event": "risk.score.completed",
  "request_id": "req_a1b2c3d4",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "decision_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "duration_ms": 78.4,
  "status": "SUCCESS"
}
```

---

## 7. Security, PII & Prompt Injection Controls

All observability components pass through `risk_manager.observability.scrubber`:
- **Automated PII Masking**: Email addresses, phone numbers, and payment cards are regex-redacted.
- **Credential Protection**: Keys matching `password`, `secret`, `api_key`, `token`, `auth` are replaced with `[REDACTED]`.
- **Customer Text Protection**: Untrusted customer inputs (`return_reason`, `customer_notes`) are never dumped raw into traces or metrics; only length metadata or sanitized tokens are preserved.
- **Prompt Injection Telemetry**: Attempts to manipulate instructions trigger `prompt_injection_detected_total` and security flags without altering numerical risk scoring authority.

---

## 8. Optional Observability Compose Stack

For containerized monitoring environments, an optional compose stack is provided:

```bash
docker compose -f docker-compose.observability.yml up -d
```

Services:
- **`ai-risk-manager`**: Backend on port `8000`.
- **`otel-collector`**: OTLP receiver on port `4317` (gRPC) & `4318` (HTTP).
- **`prometheus`**: Scrapes metrics from app on port `9090`.
- **`grafana`**: Dashboards and alerts on port `3000`.
