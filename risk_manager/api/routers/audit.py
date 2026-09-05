"""Audit timeline router implementing Part 7.

Exposes a chronological, immutable audit trail for a decision.
Preserves privacy by omitting raw customer PII while ensuring complete auditability.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.api.routers.agents import resolve_risk_decision_id
from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.session import get_db_session

router = APIRouter(prefix="/api/v1/audit", tags=["Audit Trail"])


@router.get("/{decision_id}", status_code=status.HTTP_200_OK)
async def get_audit_timeline(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Retrieve the chronological audit timeline for a risk decision."""
    risk_id = await resolve_risk_decision_id(session, decision_id)

    # 1. Fetch risk decision
    dec_stmt = select(RiskDecision).where(RiskDecision.id == risk_id)
    dec_res = await session.execute(dec_stmt)
    risk_dec = dec_res.scalar_one_or_none()
    if not risk_dec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DECISION_NOT_FOUND", "message": f"Decision {decision_id} not found"},
        )

    # 2. Query all AuditEvents whose payload references risk_id
    # Since payload is JSON, we can query all audit events or filter
    stmt = (
        select(AuditEvent)
        .order_by(AuditEvent.occurred_at)
    )
    result = await session.execute(stmt)
    all_events = result.scalars().all()

    timeline = []

    # Add initial scoring event
    timeline.append({
        "step": 1,
        "event_type": "risk.scored.v1",
        "timestamp": risk_dec.created_at.isoformat() if risk_dec.created_at else None,
        "title": "Risk Scored (Phase 4)",
        "summary": f"Scored p_abuse={float(risk_dec.p_return_abuse):.2%} (Band: {risk_dec.risk_band.value}) via {risk_dec.scoring_source.value}",
        "details": {
            "p_return_abuse": float(risk_dec.p_return_abuse),
            "risk_band": risk_dec.risk_band.value,
            "scoring_source": risk_dec.scoring_source.value,
            "fallback_tier": risk_dec.fallback_tier,
        },
    })

    # Add matching audit events from the DB
    str_risk_id = str(risk_id)
    step = 2
    for ev in all_events:
        payload = ev.payload or {}
        # Check if this audit event belongs to this risk decision
        if payload.get("risk_decision_id") == str_risk_id or payload.get("decision_id") == str(decision_id):
            title = ev.event_type
            summary = ""
            if ev.event_type == "policy.decision.v1":
                title = "Policy Evaluated (Phase 5)"
                summary = f"Selected action {payload.get('action_selected')} via {payload.get('action_selector')} (NetVal: INR {payload.get('expected_net_value')})"
            elif ev.event_type == "agent.workflow.completed.v1":
                title = "Agent Workflow Completed (Phase 6)"
                prov = payload.get("provenance", {})
                summary = f"Agents finished with status={payload.get('agent_status')} (Provider: {prov.get('provider')}, HumanReview: {payload.get('requires_human_review')})"
            elif ev.event_type == "policy.override.v1":
                title = "Manual Override Applied"
                summary = f"Action overridden to {payload.get('new_action')} by operator '{payload.get('operator_id')}' (Reason: {payload.get('reason')})"

            timeline.append({
                "step": step,
                "event_type": ev.event_type,
                "timestamp": ev.occurred_at.isoformat() if ev.occurred_at else None,
                "title": title,
                "summary": summary,
                "details": payload,
            })
            step += 1

    return {
        "decision_id": str(decision_id),
        "risk_decision_id": str(risk_id),
        "total_events": len(timeline),
        "timeline": timeline,
    }
