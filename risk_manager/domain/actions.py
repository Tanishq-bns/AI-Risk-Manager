"""Canonical intervention action space and metadata registry.

Implements PRD.md §5, TRD.md §D, SPEC.md §14, and prompt requirement §2.
Binds canonical actions A0-A4 with friction costs, operational costs,
abuse mitigation rates, and automated execution constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from risk_manager.domain.schemas.enums import Action, RiskBand


@dataclass(frozen=True)
class ActionMetadata:
    """Explicit metadata governing an intervention action."""

    action_id: Action
    action_name: str
    customer_friction_cost: float       # Direct customer friction penalty in INR
    merchant_operational_cost: float     # Direct operational courier/review cost in INR
    abuse_loss_mitigation_rate: float    # Fraction [0.0, 1.0] of abuse loss prevented if abusive
    is_reversible: bool                  # Whether intervention can be undone/refunded via override
    requires_human_approval: bool        # Whether human operator review is required before completion
    is_automated_allowed: bool           # Whether policy engine may execute this action automatically
    min_order_value: float = 0.0         # Minimum order value threshold for eligibility
    allowed_risk_bands: tuple[RiskBand, ...] = field(
        default_factory=lambda: (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)
    )
    description: str = ""


# Canonical Registry of Actions (PRD.md §5 & SPEC.md §14)
ACTION_REGISTRY: dict[Action, ActionMetadata] = {
    Action.A0: ActionMetadata(
        action_id=Action.A0,
        action_name="ZERO_FRICTION_APPROVAL",
        customer_friction_cost=0.0,
        merchant_operational_cost=0.0,
        abuse_loss_mitigation_rate=0.0,
        is_reversible=False,
        requires_human_approval=False,
        is_automated_allowed=True,
        min_order_value=0.0,
        allowed_risk_bands=(RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL),
        description="Immediate return authorization with zero customer friction or doorstep verification.",
    ),
    Action.A1: ActionMetadata(
        action_id=Action.A1,
        action_name="DYNAMIC_RETURN_FEE",
        customer_friction_cost=50.0,
        merchant_operational_cost=20.0,
        abuse_loss_mitigation_rate=0.35,
        is_reversible=True,
        requires_human_approval=False,
        is_automated_allowed=True,
        min_order_value=500.0,
        allowed_risk_bands=(RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL),
        description="Apply nominal reverse pickup processing fee (₹150-₹300) deducted from refund.",
    ),
    Action.A2: ActionMetadata(
        action_id=Action.A2,
        action_name="OTP_DOORSTEP_INSPECTION",
        customer_friction_cost=40.0,
        merchant_operational_cost=60.0,
        abuse_loss_mitigation_rate=0.75,
        is_reversible=True,
        requires_human_approval=False,
        is_automated_allowed=True,
        min_order_value=1000.0,
        allowed_risk_bands=(RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL),
        description="Require courier verification of physical package contents and customer OTP at pickup.",
    ),
    Action.A3: ActionMetadata(
        action_id=Action.A3,
        action_name="STORE_CREDIT",
        customer_friction_cost=80.0,
        merchant_operational_cost=15.0,
        abuse_loss_mitigation_rate=0.50,
        is_reversible=True,
        requires_human_approval=False,
        is_automated_allowed=True,
        min_order_value=300.0,
        allowed_risk_bands=(RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL),
        description="Offer immediate wallet or store credit refund instead of cash reversal.",
    ),
    Action.A4: ActionMetadata(
        action_id=Action.A4,
        action_name="MANUAL_REVIEW",
        customer_friction_cost=120.0,
        merchant_operational_cost=150.0,
        abuse_loss_mitigation_rate=0.95,
        is_reversible=True,
        requires_human_approval=True,
        is_automated_allowed=False,  # Human review must route to operator queue
        min_order_value=1500.0,
        allowed_risk_bands=(RiskBand.HIGH, RiskBand.CRITICAL),
        description="Escalate case to operations/risk analyst queue for evidence review before refund.",
    ),
}


def get_action_metadata(action: Action | str) -> ActionMetadata:
    """Retrieve metadata for a given action enum or string."""
    act_enum = Action(action) if isinstance(action, str) else action
    if act_enum not in ACTION_REGISTRY:
        raise ValueError(f"Unknown action: {action}")
    return ACTION_REGISTRY[act_enum]
