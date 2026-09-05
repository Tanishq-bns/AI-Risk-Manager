"""Persistence service for agent runs and audit events.

Implements Phase 6 Persistence requirements §14 and Audit Trail requirements §15.
Stores AgentRun records and emits structured agent.workflow.completed.v1 AuditEvents
without mutating the original immutable RiskDecision or PolicyDecision entities.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.core.config import settings
from risk_manager.db.models.agent_run import AgentRun
from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.domain.schemas.agents import AgentWorkflowResult
from risk_manager.domain.schemas.enums import AgentName, AgentRunStatus

logger = logging.getLogger(__name__)


class AgentPersistenceError(Exception):
    """Raised when persistence of agent run or audit records fails."""
    pass


async def persist_agent_workflow_result(
    session: AsyncSession,
    result: AgentWorkflowResult,
    flush_only: bool = False,
) -> tuple[list[AgentRun], AuditEvent]:
    """Persist AgentRun rows for each executed agent and publish a structured AuditEvent.

    Answers all 10 agent auditability questions (Prompt §15):
    1. What numerical risk score was supplied? -> p_return_abuse
    2. What policy decision was supplied? -> selected_action
    3. What evidence did Investigator identify? -> key_risk_factors, mitigating_factors, quality
    4. What did Verifier check? -> checks, failed_checks, warnings
    5. Were there disagreements? -> disagreements
    6. Was human review required? -> requires_human_review
    7. What did Action Orchestrator recommend? -> operational_recommendation, execution_mode
    8. Which Gemini model/version was used? -> model_name
    9. Did fallback/degraded execution occur? -> agent_status, agent_errors
    10. What was the final agent status? -> final_agent_recommendation, agent_status
    """
    now = datetime.now(timezone.utc)
    agent_runs: list[AgentRun] = []

    try:
        # 1. Persist Investigator AgentRun
        if result.investigator_result is not None:
            inv_run = AgentRun(
                id=uuid.uuid4(),
                risk_decision_id=result.risk_decision_id,
                agent_name=AgentName.INVESTIGATOR,
                output=result.investigator_result.model_dump(mode="json"),
                status=result.investigator_result.status,
                started_at=result.created_at,
                completed_at=now,
            )
            session.add(inv_run)
            agent_runs.append(inv_run)

        # 2. Persist Verifier AgentRun
        if result.verifier_result is not None:
            ver_run = AgentRun(
                id=uuid.uuid4(),
                risk_decision_id=result.risk_decision_id,
                agent_name=AgentName.VERIFIER,
                output=result.verifier_result.model_dump(mode="json"),
                status=result.verifier_result.status,
                started_at=result.created_at,
                completed_at=now,
            )
            session.add(ver_run)
            agent_runs.append(ver_run)

        # 3. Persist Action Orchestrator AgentRun
        if result.orchestrator_result is not None:
            orch_run = AgentRun(
                id=uuid.uuid4(),
                risk_decision_id=result.risk_decision_id,
                agent_name=AgentName.ACTION_ORCHESTRATOR,
                output=result.orchestrator_result.model_dump(mode="json"),
                status=result.orchestrator_result.status,
                started_at=result.created_at,
                completed_at=now,
            )
            session.add(orch_run)
            agent_runs.append(orch_run)

        # 4. Structured Audit Event (10 audit questions)
        audit_payload: dict[str, Any] = {
            "decision_id": str(result.decision_id),
            "risk_decision_id": str(result.risk_decision_id),
            "policy_decision_id": str(result.policy_decision_id),
            "numerical_authority": {
                "p_return_abuse": round(float(result.p_return_abuse), 4),
                "risk_band": result.risk_band,
                "selected_action": result.selected_action.value if hasattr(result.selected_action, "value") else str(result.selected_action),
                "expected_loss": round(float(result.expected_loss), 2),
                "expected_net_value": round(float(result.expected_net_value), 2),
            },
            "provenance": {
                "provider": result.provider.value if hasattr(result.provider, "value") else str(result.provider),
                "is_llm_generated": result.is_llm_generated,
                "fallback_reason": result.fallback_reason.value if hasattr(result.fallback_reason, "value") else (str(result.fallback_reason) if result.fallback_reason else None),
                "model_name": result.model_name if result.is_llm_generated else None,
                "configured_model": settings.GEMINI_MODEL,
            },
            "investigator_evidence": (
                {
                    "evidence_summary": result.investigator_result.evidence_summary,
                    "key_risk_factors": result.investigator_result.key_risk_factors,
                    "mitigating_factors": result.investigator_result.mitigating_factors,
                    "evidence_quality": result.investigator_result.evidence_quality.value if hasattr(result.investigator_result.evidence_quality, "value") else str(result.investigator_result.evidence_quality),
                    "recommendation": result.investigator_result.recommendation,
                }
                if result.investigator_result
                else None
            ),
            "verifier_checks": (
                {
                    "verification_status": result.verifier_result.verification_status,
                    "checks": result.verifier_result.checks,
                    "failed_checks": result.verifier_result.failed_checks,
                    "warnings": result.verifier_result.warnings,
                    "disagreements": result.verifier_result.disagreements,
                    "recommendation": result.verifier_result.recommendation.value if hasattr(result.verifier_result.recommendation, "value") else str(result.verifier_result.recommendation),
                }
                if result.verifier_result
                else None
            ),
            "action_orchestrator": (
                {
                    "execution_mode": result.orchestrator_result.execution_mode.value if hasattr(result.orchestrator_result.execution_mode, "value") else str(result.orchestrator_result.execution_mode),
                    "operational_recommendation": result.orchestrator_result.operational_recommendation,
                    "blockers": result.orchestrator_result.blockers,
                }
                if result.orchestrator_result
                else None
            ),
            "human_review_required": result.requires_human_review,
            "disagreements": result.disagreements,
            "final_recommendation": result.final_agent_recommendation,
            "agent_status": result.agent_status.value if hasattr(result.agent_status, "value") else str(result.agent_status),
            "agent_errors": result.agent_errors,
            "latency_ms": round(result.latency_ms, 2),
            "trace_id": result.trace_id,
            "gemini_model": result.model_name if result.is_llm_generated else None,

            "timestamp": now.isoformat(),
        }

        audit_event = AuditEvent(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type="agent.workflow.completed.v1",
            payload=audit_payload,
            occurred_at=now,
        )
        session.add(audit_event)

        if flush_only:
            await session.flush()
        else:
            await session.commit()

        logger.info(
            "Persisted %d agent runs and audit event for risk_decision %s (status=%s)",
            len(agent_runs),
            result.risk_decision_id,
            result.agent_status.value,
        )
        return agent_runs, audit_event

    except IntegrityError as ie:
        await session.rollback()
        logger.error("Integrity error persisting agent workflow result: %s", ie)
        raise AgentPersistenceError(f"Integrity violation during agent persistence: {ie}") from ie
    except Exception as e:
        await session.rollback()
        logger.error("Failed to persist agent workflow result: %s", e)
        raise AgentPersistenceError(f"Failed to persist agent workflow result: {e}") from e
