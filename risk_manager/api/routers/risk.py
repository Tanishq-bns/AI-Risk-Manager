"""Risk scoring and decision inspection router implementing Parts 3 & 5.

Provides the synchronous critical scoring path (independent of LLM availability)
and read-only decision inspection endpoints.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.api.services.risk_service import (
    format_decision_response,
    score_risk_event,
)
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.session import get_db_session
from risk_manager.domain.schemas.requests import RiskScoreRequest

router = APIRouter(prefix="/api/v1/risk", tags=["Risk Scoring"])


@router.post("/score", status_code=status.HTTP_200_OK)
async def score_risk(
    request: RiskScoreRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Synchronous, real-time risk scoring and intervention assignment.

    Executes Phase 4 ML cascade and Phase 5 policy selection within strict SLA.
    Asynchronously schedules Phase 6 LangGraph agent verification in the background.
    """
    try:
        response = await score_risk_event(
            session=session,
            request=request,
            background_tasks=background_tasks,
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "RISK_SCORING_FAILED", "message": str(e)},
        ) from e


@router.get("/decisions/{decision_id}", status_code=status.HTTP_200_OK)
async def get_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Read-only view of an authoritative risk and policy decision."""
    # Try finding RiskDecision by ID
    stmt = select(RiskDecision).where(RiskDecision.id == decision_id)
    res = await session.execute(stmt)
    dec = res.scalar_one_or_none()

    if not dec:
        # Try finding by PolicyDecision ID
        pol_stmt = select(PolicyDecision).where(PolicyDecision.id == decision_id)
        pol_res = await session.execute(pol_stmt)
        pol = pol_res.scalar_one_or_none()
        if pol:
            dec_stmt = select(RiskDecision).where(RiskDecision.id == pol.risk_decision_id)
            dec_res = await session.execute(dec_stmt)
            dec = dec_res.scalar_one_or_none()

    if not dec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DECISION_NOT_FOUND", "message": f"Decision {decision_id} not found"},
        )

    return await format_decision_response(session, dec)


@router.get("/decisions", status_code=status.HTTP_200_OK)
async def list_recent_decisions(
    limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List recent decisions for the operations dashboard."""
    stmt = (
        select(RiskDecision)
        .order_by(desc(RiskDecision.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    decisions = result.scalars().all()

    return [await format_decision_response(session, d) for d in decisions]


@router.get("/decisions/{decision_id}/replay", status_code=status.HTTP_200_OK)
async def replay_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Read-only deterministic replay trace of a historical risk decision.

    Returns sequential audit stages: Input -> Phase 4 -> Phase 5 -> Agents -> Audit Trail.
    Guarantees zero database writes, zero state mutation, zero production side-effects.
    """
    from datetime import datetime, timezone

    stmt = select(RiskDecision).where(RiskDecision.id == decision_id)
    res = await session.execute(stmt)
    dec = res.scalar_one_or_none()

    if not dec:
        pol_stmt = select(PolicyDecision).where(PolicyDecision.id == decision_id)
        pol_res = await session.execute(pol_stmt)
        pol = pol_res.scalar_one_or_none()
        if pol:
            dec_stmt = select(RiskDecision).where(RiskDecision.id == pol.risk_decision_id)
            dec_res = await session.execute(dec_stmt)
            dec = dec_res.scalar_one_or_none()

    if not dec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DECISION_NOT_FOUND", "message": f"Decision {decision_id} not found"},
        )

    base_resp = await format_decision_response(session, dec)

    candidates = base_resp.get("candidate_actions", [])
    selected_act = base_resp.get("selected_action")
    chosen_cand = next((c for c in candidates if c.get("action") == selected_act), None)
    chosen_net = chosen_cand.get("expected_net_value", 0.0) if chosen_cand else 0.0

    rejected_reasons = []
    for c in candidates:
        if c.get("action") != selected_act:
            if not c.get("is_eligible", True):
                reason = c.get("ineligibility_reason") or "Disqualified by policy guardrails"
            else:
                net_delta = round(chosen_net - c.get("expected_net_value", 0.0), 2)
                reason = f"Lower expected net value (deficit of ₹{net_delta:.2f} vs {selected_act})"
            rejected_reasons.append({
                "action": c.get("action"),
                "action_name": c.get("action_name"),
                "expected_net_value": c.get("expected_net_value"),
                "rejected_reason": reason,
            })

    return {
        "replay_metadata": {
            "mode": "READ_ONLY_REPLAY",
            "decision_id": str(dec.id),
            "replayed_at": datetime.now(timezone.utc).isoformat(),
            "state_mutation_allowed": False,
            "database_writes_committed": 0,
        },
        "step_1_input_features": base_resp.get("features", {}),
        "step_2_phase_4_scoring": {
            "p_return_abuse": base_resp.get("p_return_abuse"),
            "risk_band": base_resp.get("risk_band"),
            "scoring_source": base_resp.get("scoring_source"),
            "fallback_tier": base_resp.get("fallback_tier"),
            "model_metadata": base_resp.get("model_metadata"),
        },
        "step_3_phase_5_economics": {
            "economic_prediction": base_resp.get("economic_prediction"),
            "candidate_actions": candidates,
            "rejected_actions_analysis": rejected_reasons,
        },
        "step_4_action_decision": {
            "selected_action": selected_act,
            "action_name": base_resp.get("action_name"),
            "action_selector": base_resp.get("action_selector"),
            "requires_human_review": base_resp.get("requires_human_review"),
        },
        "step_5_agent_audit": {
            "agent_status": base_resp.get("agent_status"),
            "agent_runs": base_resp.get("agent_runs", []),
        },
        "step_6_audit_trail": base_resp.get("audit_events", []),
    }
