"""Manual override service implementing ADR-012 and TRD.md §C/D.

Provides an authorized, append-only human review override mechanism.
Guarantees that policy actions are only modified by an authenticated human operator
with a mandatory reason and an immutable AuditEvent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.intervention import Intervention
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.domain.schemas.enums import Action, ActionSelector
from risk_manager.domain.schemas.override import ManualOverrideRequest, ManualOverrideResponse
from risk_manager.observability import (
    HUMAN_OVERRIDE_TOTAL,
    PERSISTENCE_FAILURE_TOTAL,
    trace_span,
)

logger = logging.getLogger(__name__)


class OverrideError(Exception):
    """Raised when manual override fails validation or persistence."""
    pass


async def apply_manual_override(
    session: AsyncSession,
    risk_decision_id: uuid.UUID,
    request: ManualOverrideRequest,
) -> ManualOverrideResponse:
    """Apply an authorized manual override to an existing risk decision.

    Preserves original decision immutability while recording a new PolicyDecision
    transition and an immutable AuditEvent.

    Args:
        session: Active async database session
        risk_decision_id: Target risk decision UUID
        request: Validated ManualOverrideRequest (operator_id, reason, new_action)

    Returns:
        ManualOverrideResponse with transition audit details.
    """
    if not request.operator_id or not request.operator_id.strip():
        raise OverrideError("operator_id is mandatory for manual override")
    if not request.reason or not request.reason.strip():
        raise OverrideError("reason is mandatory for manual override")

    new_act_val = request.new_action.value if hasattr(request.new_action, "value") else str(request.new_action)
    with trace_span("human_override", {"risk_decision_id": str(risk_decision_id), "new_action": new_act_val}) as span:
        try:
            # 1. Fetch existing RiskDecision and its latest PolicyDecision/Intervention
            stmt = (
                select(RiskDecision)
                .where(RiskDecision.id == risk_decision_id)
            )
            result = await session.execute(stmt)
            risk_decision = result.scalar_one_or_none()
            if not risk_decision:
                raise OverrideError(f"Risk decision {risk_decision_id} not found")

            # Find the current active action (latest policy decision or intervention)
            curr_action = Action.A0
            if risk_decision.interventions:
                sorted_interventions = sorted(
                    risk_decision.interventions,
                    key=lambda x: x.created_at,
                    reverse=True,
                )
                curr_action = sorted_interventions[0].action
            elif risk_decision.policy_decisions:
                sorted_pd = sorted(
                    risk_decision.policy_decisions,
                    key=lambda x: x.created_at,
                    reverse=True,
                )
                curr_action = sorted_pd[0].new_action

            now = datetime.now(timezone.utc)
            prev_act_val = curr_action.value if hasattr(curr_action, "value") else str(curr_action)
            span.set_attribute("previous_action", prev_act_val)

            # 2. Append new PolicyDecision record
            override_policy_decision = PolicyDecision(
                id=uuid.uuid4(),
                risk_decision_id=risk_decision_id,
                previous_action=curr_action,
                new_action=request.new_action,
                selected_by=ActionSelector.MANUAL_OVERRIDE,
                operator_id=request.operator_id.strip(),
                reason=request.reason.strip(),
                created_at=now,
            )
            session.add(override_policy_decision)

            # 3. Append updated Intervention record
            override_intervention = Intervention(
                id=uuid.uuid4(),
                risk_decision_id=risk_decision_id,
                action=request.new_action,
                expected_net_value=Decimal("0.00"),
                selected_by=ActionSelector.MANUAL_OVERRIDE,
                created_at=now,
            )
            session.add(override_intervention)

            # 4. Append immutable AuditEvent
            audit_event_id = uuid.uuid4()
            audit_payload = {
                "event_type": "policy.override.v1",
                "risk_decision_id": str(risk_decision_id),
                "previous_action": prev_act_val,
                "new_action": new_act_val,
                "operator_id": request.operator_id.strip(),
                "reason": request.reason.strip(),
                "p_return_abuse": float(risk_decision.p_return_abuse),
                "risk_band": risk_decision.risk_band.value if hasattr(risk_decision.risk_band, "value") else str(risk_decision.risk_band),
                "timestamp": now.isoformat(),
            }
            audit_event = AuditEvent(
                id=audit_event_id,
                event_id=uuid.uuid4(),
                event_type="policy.override.v1",
                payload=audit_payload,
                occurred_at=now,
            )
            session.add(audit_event)
            await session.commit()

            if HUMAN_OVERRIDE_TOTAL is not None:
                HUMAN_OVERRIDE_TOTAL.labels(previous_action=prev_act_val, new_action=new_act_val).inc()

            logger.info(
                "Manual override applied for decision %s: %s -> %s by operator %s",
                risk_decision_id,
                prev_act_val,
                new_act_val,
                request.operator_id,
            )

            return ManualOverrideResponse(
                decision_id=risk_decision_id,
                previous_action=curr_action,
                new_action=request.new_action,
                overridden_at=now,
                audit_event_id=audit_event_id,
            )
        except Exception as e:
            if PERSISTENCE_FAILURE_TOTAL is not None and not isinstance(e, OverrideError):
                PERSISTENCE_FAILURE_TOTAL.labels(entity="manual_override", error_code=type(e).__name__).inc()
            raise e
