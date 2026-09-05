"""Persistence service for policy decisions, interventions, and audit events.

Implements TRD.md §D/§E, SPEC.md §14/§16, and Phase 5 prompt requirements §14, §15, §16.
Provides an atomic, append-only persistence layer for policy outcomes.
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.intervention import Intervention
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.domain.schemas.economics import PolicyDecisionContext
from risk_manager.domain.schemas.enums import Action, ActionSelector

logger = logging.getLogger(__name__)


class PolicyPersistenceError(Exception):
    """Raised when persistence of policy outcomes fails."""
    pass


async def persist_policy_evaluation(
    session: AsyncSession,
    policy_context: PolicyDecisionContext,
    previous_action: Action | None = None,
    operator_id: str | None = None,
    flush_only: bool = False,
) -> tuple[Intervention, PolicyDecision, AuditEvent]:
    """Persist an Intervention, PolicyDecision, and AuditEvent in an atomic transaction.

    Answers all 10 auditability questions structurally (Prompt §16):
    1. What was the risk score? -> p_return_abuse
    2. What risk band was assigned? -> risk_band
    3. What actions were considered? -> candidate_actions
    4. What did each action economically represent? -> candidate_actions economic breakdown
    5. Which action was selected? -> action_selected
    6. Why was it selected? -> rationale / reward_estimate / guardrails_applied
    7. Which policy selector was used? -> action_selector (LINUCB / RULES / etc.)
    8. Were guardrails applied? -> guardrails_applied
    9. Was fallback used? -> fallback_reason
    10. Which model/policy version produced the result? -> policy_model_version

    Args:
        session: Async SQLAlchemy session
        policy_context: The evaluated PolicyDecisionContext from PolicyEngine
        previous_action: Optional previous action state if transition
        operator_id: Optional human operator ID if override
        flush_only: If True, flushes changes without committing (caller commits)

    Returns:
        tuple of (Intervention, PolicyDecision, AuditEvent) entities.
    """
    try:
        # 1. Create Intervention record
        # Note: expected_net_value is bounded and rounded to 2 decimal places for INR Numeric(12,2)
        net_val_decimal = Decimal(str(round(policy_context.expected_net_value, 2)))

        intervention = Intervention(
            id=uuid.uuid4(),
            risk_decision_id=policy_context.risk_decision_id,
            action=policy_context.action_selected,
            expected_net_value=net_val_decimal,
            selected_by=policy_context.action_selector,
            created_at=policy_context.created_at,
        )
        session.add(intervention)

        # 2. Create PolicyDecision record (state transition ledger)
        decision_reason = policy_context.fallback_reason
        if not decision_reason:
            decision_reason = (
                f"Selected via {policy_context.action_selector.value} "
                f"with net_val=INR {policy_context.expected_net_value:.2f}"
            )

        policy_decision = PolicyDecision(
            id=policy_context.decision_id,
            risk_decision_id=policy_context.risk_decision_id,
            previous_action=previous_action,
            new_action=policy_context.action_selected,
            selected_by=policy_context.action_selector,
            operator_id=operator_id,
            reason=decision_reason,
            created_at=policy_context.created_at,
        )
        session.add(policy_decision)

        # 3. Create AuditEvent record with complete structural audit payload
        audit_payload: dict[str, Any] = {
            "decision_id": str(policy_context.decision_id),
            "risk_decision_id": str(policy_context.risk_decision_id),
            "p_return_abuse": round(float(policy_context.p_return_abuse), 4),
            "risk_band": policy_context.risk_band.value,
            "action_selected": policy_context.action_selected.value,
            "action_selector": policy_context.action_selector.value,
            "expected_net_value": round(float(policy_context.expected_net_value), 2),
            "reward_estimate": round(float(policy_context.reward_estimate), 4),
            "exploration_bonus": round(float(policy_context.exploration_bonus), 4),
            "policy_model_version": policy_context.policy_model_version,
            "guardrails_applied": policy_context.guardrails_applied,
            "fallback_reason": policy_context.fallback_reason,
            "candidate_actions": [
                {
                    "action": a.action.value,
                    "action_name": a.action_name,
                    "expected_loss": round(float(a.expected_loss), 2),
                    "expected_net_value": round(float(a.expected_net_value), 2),
                    "friction_cost": round(float(a.friction_cost), 2),
                    "operational_cost": round(float(a.operational_cost), 2),
                    "is_eligible": a.is_eligible,
                    "ineligibility_reason": a.ineligibility_reason,
                }
                for a in policy_context.candidate_actions
            ],
            "timestamp": policy_context.created_at.isoformat(),
        }

        audit_event = AuditEvent(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type="policy.decision.v1",
            payload=audit_payload,
            occurred_at=policy_context.created_at,
        )
        session.add(audit_event)

        if flush_only:
            await session.flush()
        else:
            await session.commit()

        logger.info(
            "Persisted policy decision %s for risk_decision %s (action=%s, selector=%s)",
            policy_context.decision_id,
            policy_context.risk_decision_id,
            policy_context.action_selected.value,
            policy_context.action_selector.value,
        )

        return intervention, policy_decision, audit_event

    except IntegrityError as ie:
        await session.rollback()
        logger.error("Database integrity error persisting policy evaluation: %s", ie)
        raise PolicyPersistenceError(f"Integrity violation during policy persistence: {ie}") from ie
    except Exception as e:
        await session.rollback()
        logger.error("Failed to persist policy evaluation: %s", e)
        raise PolicyPersistenceError(f"Failed to persist policy evaluation: {e}") from e
