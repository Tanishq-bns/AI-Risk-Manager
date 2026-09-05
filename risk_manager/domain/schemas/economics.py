"""Domain schemas and DTOs for economic evaluation and policy decisions.

Implements TRD.md §E/§O, SPEC.md §14, and prompt requirements §3, §5, §14.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import Action, ActionSelector, RiskBand


class EconomicOutcomeRecord(BaseModel):
    """Synthetic or realized economic training observation (offline training only)."""

    sample_id: str
    action: Action
    order_value: float = Field(ge=0.0)
    p_return_abuse: float = Field(ge=0.0, le=1.0)
    is_return_abuse: int = Field(ge=0, le=1, description="Ground truth for offline training only")
    expected_loss_no_action: float = Field(ge=0.0)
    expected_loss_with_action: float = Field(ge=0.0)
    friction_cost: float = Field(ge=0.0)
    operational_cost: float = Field(ge=0.0)
    margin_saved: float = Field(description="Gross margin preserved by intervention")
    expected_net_value: float = Field(description="ExpectedNetValue = Loss(no_action) - Loss(action)")
    realized_or_simulated_outcome: float = Field(description="Simulated economic reward")


class ActionEvaluation(BaseModel):
    """Economic evaluation metrics for a candidate action considered by the policy engine."""

    action: Action
    action_name: str
    expected_loss: float = Field(ge=0.0, description="Projected loss under this action in INR")
    expected_net_value: float = Field(description="Net value relative to A0 in INR")
    friction_cost: float = Field(ge=0.0, description="Customer friction cost in INR")
    operational_cost: float = Field(ge=0.0, description="Merchant operational cost in INR")
    is_eligible: bool = Field(default=True, description="Whether action satisfies hard policy constraints")
    ineligibility_reason: str | None = Field(default=None, description="Guardrail reason if ineligible")


class PolicyDecisionContext(BaseModel):
    """Auditable state record produced by the policy engine (TRD.md §E)."""

    decision_id: UUID = Field(default_factory=uuid4)
    risk_decision_id: UUID
    p_return_abuse: float = Field(ge=0.0, le=1.0)
    risk_band: RiskBand
    action_selected: Action
    action_selector: ActionSelector
    candidate_actions: list[ActionEvaluation] = Field(default_factory=list)
    expected_net_value: float = Field(description="Selected action expected net value (INR)")
    reward_estimate: float = Field(description="LinUCB predicted reward")
    exploration_bonus: float = Field(default=0.0, description="LinUCB confidence bonus")
    policy_model_version: str = Field(default="v1.0.0-linucb")
    guardrails_applied: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
