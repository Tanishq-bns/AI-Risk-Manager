"""Human review queue and manual override router implementing Part 8.

Enforces the critical human-override boundary:
- Human override is the ONLY authorized mechanism to modify an existing policy decision.
- Directly invokes apply_manual_override with mandatory operator justification and an immutable AuditEvent.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.api.routers.agents import resolve_risk_decision_id
from risk_manager.db.models.agent_run import AgentRun
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.services.override_service import OverrideError, apply_manual_override
from risk_manager.db.session import get_db_session
from risk_manager.domain.schemas.enums import Action, AgentName, RiskBand
from risk_manager.domain.schemas.override import ManualOverrideRequest, ManualOverrideResponse

router = APIRouter(prefix="/api/v1/review", tags=["Human Review Queue"])


@router.get("/queue", status_code=status.HTTP_200_OK)
async def get_review_queue(
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Retrieve decisions pending human operator review."""
    # 1. Fetch recent risk decisions
    stmt = (
        select(RiskDecision)
        .order_by(desc(RiskDecision.created_at))
        .limit(50)
    )
    result = await session.execute(stmt)
    decisions = result.scalars().all()

    queue = []
    for d in decisions:
        # Determine latest action
        latest_act = Action.A0
        if d.policy_decisions:
            sorted_pd = sorted(d.policy_decisions, key=lambda x: x.created_at, reverse=True)
            latest_act = sorted_pd[0].new_action
        elif d.interventions:
            sorted_int = sorted(d.interventions, key=lambda x: x.created_at, reverse=True)
            latest_act = sorted_int[0].action

        # Check agent runs for verifier escalation
        requires_human = False
        escalation_reason = None

        if d.agent_runs:
            for r in d.agent_runs:
                if r.agent_name == AgentName.VERIFIER and r.output:
                    if r.output.get("requires_human_review"):
                        requires_human = True
                        failed = r.output.get("failed_checks", [])
                        disagreements = r.output.get("disagreements", [])
                        escalation_reason = (
                            f"Verifier flagged: {', '.join(failed or disagreements or ['Inconsistency detected'])}"
                        )

        # Invariant: A4 or CRITICAL always requires review
        if latest_act == Action.A4 or str(latest_act) in ("A4", "Action.A4"):
            requires_human = True

            if not escalation_reason:
                escalation_reason = "Selected action A4 mandates manual review"
        elif d.risk_band == RiskBand.CRITICAL:
            requires_human = True
            if not escalation_reason:
                escalation_reason = "CRITICAL risk band mandates manual review"

        if requires_human:
            queue.append({
                "decision_id": str(d.id),
                "risk_decision_id": str(d.id),
                "p_return_abuse": float(d.p_return_abuse),
                "risk_band": d.risk_band.value,
                "selected_action": latest_act.value,
                "reason": escalation_reason or "Escalated for human oversight",
                "agent_status": "COMPLETED" if d.agent_runs else "PENDING",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            })

    return queue


@router.post("/{decision_id}/override", status_code=status.HTTP_200_OK, response_model=ManualOverrideResponse)
async def override_decision(
    decision_id: uuid.UUID,
    request: ManualOverrideRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ManualOverrideResponse:
    """Apply an authorized manual override to an existing decision."""
    risk_id = await resolve_risk_decision_id(session, decision_id)

    try:
        response = await apply_manual_override(
            session=session,
            risk_decision_id=risk_id,
            request=request,
        )
        return response
    except OverrideError as oe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "OVERRIDE_FAILED", "message": str(oe)},
        ) from oe
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "OVERRIDE_FAILED", "message": str(e)},
        ) from e
