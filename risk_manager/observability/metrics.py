"""Prometheus metrics registry and instrumentation for AI Risk Manager.

Implements Phase 8 metric requirements:
- Bounded, low-cardinality labels only (method, status, risk_band, action, provider).
- Strictly forbids decision_id, customer_id, trace_id, or request_id in metric labels.
- Standard Prometheus counters and histograms with explicit seconds units.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("risk_manager.observability.metrics")

_PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        REGISTRY,
        generate_latest,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    REGISTRY = None
    generate_latest = None

# Custom registry for clean isolation and testing
registry = REGISTRY if _PROMETHEUS_AVAILABLE else None


# ------------------------------------------------------------------------------
# Metric Definitions (Bounded Cardinality)
# ------------------------------------------------------------------------------

if _PROMETHEUS_AVAILABLE:
    AI_RISK_MANAGER_UP = Gauge(
        "ai_risk_manager_up",
        "Status of AI Risk Manager service.",
    )
    AI_RISK_MANAGER_UP.set(1)

    # A. API Metrics
    HTTP_REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests received by the application.",
        ["method", "endpoint", "status_code"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration latency in seconds.",
        ["method", "endpoint"],
        buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    HTTP_ERRORS_TOTAL = Counter(
        "http_errors_total",
        "Total HTTP error responses returned by the application.",
        ["endpoint", "error_code"],
    )

    # B. Risk Scoring Metrics
    RISK_DECISIONS_TOTAL = Counter(
        "risk_decisions_total",
        "Total risk evaluation requests processed.",
        ["scoring_source", "fallback_tier"],
    )
    RISK_DECISION_DURATION_SECONDS = Histogram(
        "risk_decision_duration_seconds",
        "Duration of risk scoring computation in seconds.",
        ["scoring_source"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5),
    )
    RISK_FALLBACK_TOTAL = Counter(
        "risk_fallback_total",
        "Total risk cascade degradation fallback occurrences.",
        ["from_tier", "to_tier", "reason"],
    )

    # C. Risk Bands
    RISK_BAND_TOTAL = Counter(
        "risk_band_total",
        "Distribution of assigned risk bands.",
        ["risk_band"],
    )

    # D. Policy Metrics
    POLICY_DECISIONS_TOTAL = Counter(
        "policy_decisions_total",
        "Total intervention decisions evaluated by policy engine.",
        ["selector", "action"],
    )
    POLICY_DECISION_DURATION_SECONDS = Histogram(
        "policy_decision_duration_seconds",
        "Duration of policy engine evaluation in seconds.",
        ["selector"],
        buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1),
    )
    INTERVENTION_ACTION_TOTAL = Counter(
        "intervention_action_total",
        "Total interventions assigned by policy action code.",
        ["action", "is_eligible"],
    )

    # E. Agent Operations Metrics
    AGENT_WORKFLOW_TOTAL = Counter(
        "agent_workflow_total",
        "Total Phase 6 agent graph workflow executions.",
        ["provider", "status"],
    )
    AGENT_WORKFLOW_DURATION_SECONDS = Histogram(
        "agent_workflow_duration_seconds",
        "Duration of agent graph workflow execution in seconds.",
        ["provider"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0),
    )
    AGENT_FAILURES_TOTAL = Counter(
        "agent_failures_total",
        "Total agent workflow execution errors.",
        ["agent_name", "error_type"],
    )
    AGENT_FALLBACK_TOTAL = Counter(
        "agent_fallback_total",
        "Total transitions to deterministic agent fallback.",
        ["reason"],
    )
    AGENT_HUMAN_REVIEW_TOTAL = Counter(
        "agent_human_review_total",
        "Total agent recommendations requiring human specialist review.",
        ["reason"],
    )

    # F. Human Review & Overrides
    HUMAN_REVIEW_REQUIRED_TOTAL = Counter(
        "human_review_required_total",
        "Total decisions routed to the manual review queue.",
        ["trigger_source", "action"],
    )
    HUMAN_OVERRIDE_TOTAL = Counter(
        "human_override_total",
        "Total authorized operator manual overrides performed.",
        ["previous_action", "new_action"],
    )

    # G. Persistence Metrics
    PERSISTENCE_OPERATION_TOTAL = Counter(
        "persistence_operation_total",
        "Total database persistence operations executed.",
        ["entity", "operation"],
    )
    PERSISTENCE_FAILURE_TOTAL = Counter(
        "persistence_failure_total",
        "Total database persistence failures.",
        ["entity", "error_code"],
    )

    # H. Security / Prompt Injection
    PROMPT_INJECTION_DETECTED_TOTAL = Counter(
        "prompt_injection_detected_total",
        "Total adversarial prompt injection attempts detected.",
        ["agent_name", "routing_status"],
    )

else:
    # No-Op Placeholders if prometheus_client is absent
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_SECONDS = None
    HTTP_ERRORS_TOTAL = None
    RISK_DECISIONS_TOTAL = None
    RISK_DECISION_DURATION_SECONDS = None
    RISK_FALLBACK_TOTAL = None
    RISK_BAND_TOTAL = None
    POLICY_DECISIONS_TOTAL = None
    POLICY_DECISION_DURATION_SECONDS = None
    INTERVENTION_ACTION_TOTAL = None
    AGENT_WORKFLOW_TOTAL = None
    AGENT_WORKFLOW_DURATION_SECONDS = None
    AGENT_FAILURES_TOTAL = None
    AGENT_FALLBACK_TOTAL = None
    AGENT_HUMAN_REVIEW_TOTAL = None
    HUMAN_REVIEW_REQUIRED_TOTAL = None
    HUMAN_OVERRIDE_TOTAL = None
    PERSISTENCE_OPERATION_TOTAL = None
    PERSISTENCE_FAILURE_TOTAL = None
    PROMPT_INJECTION_DETECTED_TOTAL = None


def get_metrics_payload() -> tuple[bytes, str]:
    """Generate Prometheus exposition payload and content-type header."""
    if not _PROMETHEUS_AVAILABLE or generate_latest is None:
        fallback_text = (
            "# HELP ai_risk_manager_up Status of AI Risk Manager service\n"
            "# TYPE ai_risk_manager_up gauge\n"
            "ai_risk_manager_up 1\n"
        ).encode("utf-8")
        return fallback_text, "text/plain; version=0.0.4; charset=utf-8"

    return generate_latest(registry or REGISTRY), CONTENT_TYPE_LATEST
