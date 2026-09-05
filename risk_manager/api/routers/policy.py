"""Policy API router.

Provides endpoints for inspecting policy actions, guardrails, and decision history.
"""

from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.session import get_db_session
from risk_manager.domain.schemas.enums import Action, ActionSelector

router = APIRouter(prefix="/api/v1/policy", tags=["Policy Engine"])


class ActionInfo(BaseModel):
    """Metadata for an authoritative intervention action."""

    action: str
    code: str
    name: str
    description: str
    friction_level: str
    operational_cost_inr: float
    guardrail_rules: list[str]


class PolicyDecisionDetail(BaseModel):
    """Authoritative policy decision information for a decision."""

    decision_id: str
    risk_decision_id: str
    previous_action: str | None = None
    selected_action: str
    selected_by: str
    operator_id: str | None = None
    reason: str | None = None
    created_at: str


@router.get("/actions", response_model=list[ActionInfo])
async def list_policy_actions() -> list[ActionInfo]:
    """Return all authoritative candidate intervention actions and guardrails."""
    return [
        ActionInfo(
            action=Action.A0.value,
            code="A0",
            name="Instant Refund / Zero Friction",
            description="Trust-first immediate refund processing with zero doorstep friction.",
            friction_level="NONE",
            operational_cost_inr=0.0,
            guardrail_rules=["Disallowed when p_return_abuse > 0.40"],
        ),
        ActionInfo(
            action=Action.A1.value,
            code="A1",
            name="Standard Pickup Verification",
            description="Standard reverse logistics with basic verification checks.",
            friction_level="LOW",
            operational_cost_inr=35.0,
            guardrail_rules=["Standard baseline intervention"],
        ),
        ActionInfo(
            action=Action.A2.value,
            code="A2",
            name="OTP Doorstep Inspection",
            description="Courier requires OTP verification and physical package inspection before accepting.",
            friction_level="MEDIUM",
            operational_cost_inr=75.0,
            guardrail_rules=["Recommended for high risk return rate anomalies"],
        ),
        ActionInfo(
            action=Action.A3.value,
            code="A3",
            name="Store Credit / Re-routing",
            description="Offer instantaneous store credit or dedicated drop-off center re-routing.",
            friction_level="HIGH",
            operational_cost_inr=50.0,
            guardrail_rules=["Disallowed for trusted/low-risk customers with order_count >= 5 and return_rate <= 0.10"],
        ),
        ActionInfo(
            action=Action.A4.value,
            code="A4",
            name="Disallow Return / Manual Escalation",
            description="Flag for mandatory human review; return suspended pending specialist investigation.",
            friction_level="VERY_HIGH",
            operational_cost_inr=150.0,
            guardrail_rules=["Mandatory human review routing; restricted for high-confidence severe abuse"],
        ),
    ]


@router.get("/{decision_id}", response_model=PolicyDecisionDetail)
async def get_policy_decision(
    decision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> PolicyDecisionDetail:
    """Retrieve the authoritative policy decision record for a risk decision."""
    query = (
        select(PolicyDecision)
        .where(PolicyDecision.risk_decision_id == decision_id)
        .order_by(desc(PolicyDecision.created_at))
    )
    result = await db.execute(query)
    decision = result.scalars().first()

    if not decision:
        # Check if risk decision exists
        rd_query = select(RiskDecision).where(RiskDecision.id == decision_id)
        rd_res = await db.execute(rd_query)
        if not rd_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Risk decision {decision_id} not found",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy decision record found for {decision_id}",
        )

    prev_action = decision.previous_action.value if hasattr(decision.previous_action, "value") else decision.previous_action
    new_action = decision.new_action.value if hasattr(decision.new_action, "value") else decision.new_action
    sel_by = decision.selected_by.value if hasattr(decision.selected_by, "value") else decision.selected_by

    return PolicyDecisionDetail(
        decision_id=str(decision.id),
        risk_decision_id=str(decision.risk_decision_id),
        previous_action=prev_action,
        selected_action=new_action,
        selected_by=str(sel_by),
        operator_id=decision.operator_id,
        reason=decision.reason,
        created_at=decision.created_at.isoformat() if decision.created_at else "",
    )
