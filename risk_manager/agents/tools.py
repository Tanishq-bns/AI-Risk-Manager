"""Allowlisted read-only tools for LangGraph agents.

Implements Phase 6 tool access restrictions §7.
All tools are strictly read-only, schema validated, scoped, and auditable.
Agents have ZERO access to payment, refund, database modification, or external side effects.
"""

from typing import Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class DecisionScopedInput(BaseModel):
    """Schema for decision-scoped read-only queries."""

    decision_id: str = Field(description="UUID string of the risk decision")


class CustomerScopedInput(BaseModel):
    """Schema for customer-scoped history queries."""

    customer_id: str = Field(description="Customer identifier or hash")


class ModelMetadataInput(BaseModel):
    """Schema for model version provenance queries."""

    model_version: str = Field(description="Model identifier/version tag")


# In-memory session registry for read-only query resolution during agent execution
_CURRENT_WORKFLOW_CONTEXT: dict[str, Any] = {}


def set_workflow_tool_context(context: dict[str, Any]) -> None:
    """Set active read-only context for the current decision workflow."""
    global _CURRENT_WORKFLOW_CONTEXT
    _CURRENT_WORKFLOW_CONTEXT = context.copy()


def clear_workflow_tool_context() -> None:
    """Clear active workflow context after execution."""
    global _CURRENT_WORKFLOW_CONTEXT
    _CURRENT_WORKFLOW_CONTEXT.clear()


@tool("fetch_risk_decision", args_schema=DecisionScopedInput)
def fetch_risk_decision(decision_id: str) -> dict[str, Any]:
    """Fetch the authoritative Phase 4 numerical risk decision (read-only)."""
    return {
        "decision_id": decision_id,
        "p_return_abuse": _CURRENT_WORKFLOW_CONTEXT.get("p_return_abuse", 0.0),
        "risk_band": _CURRENT_WORKFLOW_CONTEXT.get("risk_band", "LOW"),
        "scoring_source": _CURRENT_WORKFLOW_CONTEXT.get("scoring_source", "XGBOOST"),
        "fallback_tier": _CURRENT_WORKFLOW_CONTEXT.get("fallback_tier", 0),
        "immutable": True,
    }


@tool("fetch_feature_evidence", args_schema=DecisionScopedInput)
def fetch_feature_evidence(decision_id: str) -> dict[str, Any]:
    """Fetch the feature evidence and completeness diagnostics (read-only)."""
    return {
        "decision_id": decision_id,
        "feature_evidence": _CURRENT_WORKFLOW_CONTEXT.get("feature_evidence", {}),
        "completeness_ratio": _CURRENT_WORKFLOW_CONTEXT.get("feature_evidence", {}).get(
            "completeness_ratio", 1.0
        ),
    }


@tool("fetch_economic_evaluation", args_schema=DecisionScopedInput)
def fetch_economic_evaluation(decision_id: str) -> dict[str, Any]:
    """Fetch the candidate action economic evaluations and expected net values (read-only)."""
    return {
        "decision_id": decision_id,
        "candidate_actions": _CURRENT_WORKFLOW_CONTEXT.get("candidate_actions", []),
        "expected_net_value": _CURRENT_WORKFLOW_CONTEXT.get("expected_net_value", 0.0),
        "expected_loss": _CURRENT_WORKFLOW_CONTEXT.get("expected_loss", 0.0),
    }


@tool("fetch_policy_decision", args_schema=DecisionScopedInput)
def fetch_policy_decision(decision_id: str) -> dict[str, Any]:
    """Fetch the authoritative Phase 5 policy decision and applied guardrails (read-only)."""
    return {
        "decision_id": decision_id,
        "selected_action": str(_CURRENT_WORKFLOW_CONTEXT.get("selected_action", "A0")),
        "action_selector": _CURRENT_WORKFLOW_CONTEXT.get("action_selector", "LINUCB"),
        "guardrails_applied": _CURRENT_WORKFLOW_CONTEXT.get("guardrails_applied", []),
    }


@tool("fetch_customer_order_history", args_schema=CustomerScopedInput)
def fetch_customer_order_history(customer_id: str) -> dict[str, Any]:
    """Fetch historical customer metrics and return rates (read-only)."""
    return {
        "customer_id": customer_id,
        "customer_history": _CURRENT_WORKFLOW_CONTEXT.get("customer_history", {}),
    }


@tool("fetch_model_metadata", args_schema=ModelMetadataInput)
def fetch_model_metadata(model_version: str) -> dict[str, Any]:
    """Fetch model version provenance and training metadata (read-only)."""
    return {
        "model_version": model_version,
        "model_metadata": _CURRENT_WORKFLOW_CONTEXT.get("model_metadata", {}),
    }


ALLOWLISTED_TOOLS = [
    fetch_risk_decision,
    fetch_feature_evidence,
    fetch_economic_evaluation,
    fetch_policy_decision,
    fetch_customer_order_history,
    fetch_model_metadata,
]
