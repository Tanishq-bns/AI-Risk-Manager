"""Agent workflow execution and inspection router implementing Parts 4 & 6.

Executes and inspects the asynchronous LangGraph multi-agent orchestration layer.
Guarantees truthful LLM vs fallback provenance and absolute numerical immutability.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.agents.graph import run_agent_workflow
from risk_manager.agents.persistence import persist_agent_workflow_result
from risk_manager.api.services.risk_service import build_agent_graph_state_for_decision
from risk_manager.db.models.agent_run import AgentRun
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.session import get_db_session
from risk_manager.domain.schemas.enums import AgentName, AgentProvider

router = APIRouter(prefix="/api/v1/agents", tags=["Agent Orchestration"])


async def resolve_risk_decision_id(session: AsyncSession, decision_id: uuid.UUID) -> uuid.UUID:
    """Resolve whether decision_id is a RiskDecision ID or PolicyDecision ID."""
    stmt = select(RiskDecision.id).where(RiskDecision.id == decision_id)
    res = await session.execute(stmt)
    r_id = res.scalar_one_or_none()
    if r_id:
        return r_id

    pol_stmt = select(PolicyDecision.risk_decision_id).where(PolicyDecision.id == decision_id)
    pol_res = await session.execute(pol_stmt)
    p_risk_id = pol_res.scalar_one_or_none()
    if p_risk_id:
        return p_risk_id

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "DECISION_NOT_FOUND", "message": f"Decision {decision_id} not found"},
    )


@router.post("/run/{decision_id}", status_code=status.HTTP_200_OK)
async def run_agents_for_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Execute Phase 6 LangGraph multi-agent workflow for an existing decision."""
    risk_id = await resolve_risk_decision_id(session, decision_id)

    try:
        state = await build_agent_graph_state_for_decision(session, risk_id)
        result = await run_agent_workflow(state)
        await persist_agent_workflow_result(session, result)

        return {
            "decision_id": str(decision_id),
            "risk_decision_id": str(risk_id),
            "agent_status": result.agent_status.value if hasattr(result.agent_status, "value") else str(result.agent_status),
            "provider": result.provider.value if hasattr(result.provider, "value") else str(result.provider),
            "model_name": result.model_name,
            "is_llm_generated": result.is_llm_generated,
            "fallback_reason": result.fallback_reason.value if hasattr(result.fallback_reason, "value") else (str(result.fallback_reason) if result.fallback_reason else None),
            "requires_human_review": result.requires_human_review,
            "final_agent_recommendation": result.final_agent_recommendation,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "AGENT_WORKFLOW_FAILED", "message": str(e)},
        ) from e


@router.get("/{decision_id}", status_code=status.HTTP_200_OK)
async def get_agent_results(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Retrieve structured agent investigation, verification, and orchestration outputs."""
    risk_id = await resolve_risk_decision_id(session, decision_id)

    stmt = (
        select(AgentRun)
        .where(AgentRun.risk_decision_id == risk_id)
        .order_by(AgentRun.started_at)
    )
    result = await session.execute(stmt)
    runs = result.scalars().all()

    if not runs:
        return {
            "decision_id": str(decision_id),
            "risk_decision_id": str(risk_id),
            "status": "PENDING",
            "message": "Agent workflow is pending execution or in progress.",
            "investigator": None,
            "verifier": None,
            "orchestrator": None,
            "provenance": {
                "provider": AgentProvider.DETERMINISTIC_FALLBACK.value,
                "is_llm_generated": False,
                "model_name": None,
                "fallback_reason": None,
            },
        }

    inv_output = None
    ver_output = None
    orch_output = None
    provenance = {
        "provider": AgentProvider.DETERMINISTIC_FALLBACK.value,
        "is_llm_generated": False,
        "model_name": None,
        "fallback_reason": None,
    }

    for r in runs:
        if r.agent_name == AgentName.INVESTIGATOR:
            inv_output = r.output
        elif r.agent_name == AgentName.VERIFIER:
            ver_output = r.output
        elif r.agent_name == AgentName.ACTION_ORCHESTRATOR:
            orch_output = r.output

    # Infer provenance from runs
    if ver_output and ver_output.get("provider"):
        provenance["provider"] = ver_output.get("provider")
        provenance["is_llm_generated"] = bool(ver_output.get("is_llm_generated"))
        provenance["model_name"] = ver_output.get("model_name")
        provenance["fallback_reason"] = ver_output.get("fallback_reason")

    runs_list = [
        {
            "agent_name": r.agent_name.value.lower() if hasattr(r.agent_name, "value") else str(r.agent_name).lower(),
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "output": r.output,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]

    return {
        "decision_id": str(decision_id),
        "risk_decision_id": str(risk_id),
        "status": "COMPLETED",
        "investigator": inv_output,
        "verifier": ver_output,
        "orchestrator": orch_output,
        "provenance": provenance,
        "runs": runs_list,
    }
