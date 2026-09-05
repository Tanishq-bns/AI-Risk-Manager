"""LangGraph workflow construction and asynchronous executor.

Implements Phase 6 LangGraph Workflow specification §3, §4, §11, §12, §13.
Topological orchestration:
START -> LoadDecisionContext -> Investigator -> Verifier -> [Router]
                                                              |-- Inconsistency/Review -> HumanReviewRequired -> Finalize -> END
                                                              `-- Normal -> ActionOrchestrator -> Finalize -> END
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any
import uuid

from langgraph.graph import END, START, StateGraph

from risk_manager.agents.investigator import investigator_node
from risk_manager.agents.orchestrator import action_orchestrator_node
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.verifier import verifier_node
from risk_manager.core.config import settings
from risk_manager.domain.schemas.agents import (
    ActionDecision,
    AgentWorkflowResult,
    InvestigationResult,
    VerificationResult,
)
from risk_manager.domain.schemas.enums import (
    Action,
    AgentName,
    AgentRunStatus,
    RiskBand,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Node: LoadDecisionContext
# ------------------------------------------------------------------------------
async def load_decision_context_node(state: AgentGraphState) -> dict[str, Any]:
    """Initialize workflow state, timestamps, and enforce read-only baseline."""
    now_iso = datetime.now(timezone.utc).isoformat()
    timestamps = dict(state.get("timestamps", {}))
    timestamps["start"] = now_iso

    trace_id = state.get("trace_id") or str(uuid.uuid4())

    # Configure LangSmith environment if enabled
    if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT

    return {
        "trace_id": trace_id,
        "timestamps": timestamps,
        "agent_errors": list(state.get("agent_errors", [])),
        "disagreements": list(state.get("disagreements", [])),
        "latencies_ms": dict(state.get("latencies_ms", {})),
        "agent_status": AgentRunStatus.RUNNING,
    }


# ------------------------------------------------------------------------------
# Node: HumanReviewRequired (Escalation Path)
# ------------------------------------------------------------------------------
async def human_review_escalation_node(state: AgentGraphState) -> dict[str, Any]:
    """Escalate decision to human review when verifier detects material inconsistencies."""
    selected_action: Action = state.get("selected_action", Action.A0)
    expected_net_value = state.get("expected_net_value", 0.0)
    v_res: VerificationResult | None = state.get("verifier_result")
    disagreements = list(state.get("disagreements", []))

    blockers = list(v_res.failed_checks) if v_res else []
    if disagreements:
        blockers.extend([f"Disagreement: {d}" for d in disagreements])

    escalation_decision = ActionDecision(
        agent_name=AgentName.ACTION_ORCHESTRATOR,
        status=AgentRunStatus.COMPLETED,
        selected_action_reference=selected_action,
        execution_mode="MANUAL_REVIEW_QUEUE",
        operational_recommendation=(
            f"Escalate decision to human risk review queue. "
            f"Preserved policy action: {selected_action.value}."
        ),
        requires_human_review=True,
        blockers=blockers,
        confidence=0.90,
        action=selected_action,
        rationale="Automated verification detected material inconsistency; human intervention required.",
        expected_net_value=expected_net_value,
        policy_constraints_satisfied=False,
        requires_manual_review=True,
    )

    return {
        "orchestrator_result": escalation_decision,
        "requires_human_review": True,
        "final_agent_recommendation": "ESCALATE_TO_HUMAN_REVIEW",
    }


# ------------------------------------------------------------------------------
# Node: FinalizeAgentResult
# ------------------------------------------------------------------------------
async def finalize_agent_result_node(state: AgentGraphState) -> dict[str, Any]:
    """Calculate aggregate latencies, finalize recommendation, and seal results."""
    now_iso = datetime.now(timezone.utc).isoformat()
    timestamps = dict(state.get("timestamps", {}))
    timestamps["end"] = now_iso

    latencies = dict(state.get("latencies_ms", {}))
    total_latency = sum(latencies.values())
    latencies["total_graph"] = total_latency

    final_status = AgentRunStatus.COMPLETED
    if state.get("agent_errors") or state.get("agent_status") == AgentRunStatus.DEGRADED:
        final_status = AgentRunStatus.DEGRADED
    elif state.get("agent_status") == AgentRunStatus.FAILED:
        final_status = AgentRunStatus.FAILED

    final_rec = state.get("final_agent_recommendation")
    if not final_rec:
        if state.get("requires_human_review"):
            final_rec = "MANUAL_REVIEW"
        else:
            final_rec = "CONFIRM"

    return {
        "timestamps": timestamps,
        "latencies_ms": latencies,
        "agent_status": final_status,
        "final_agent_recommendation": final_rec,
    }


# ------------------------------------------------------------------------------
# Conditional Router
# ------------------------------------------------------------------------------
def verifier_routing_condition(state: AgentGraphState) -> str:
    """Route to human review escalation if verifier found inconsistencies, otherwise orchestrator."""
    v_res = state.get("verifier_result")
    requires_human = (
        state.get("requires_human_review", False)
        or (v_res is not None and (v_res.requires_human_review or bool(v_res.failed_checks)))
        or bool(state.get("disagreements"))
        or state.get("selected_action") == Action.A4
    )

    if requires_human:
        return "human_review_escalation"
    return "action_orchestrator"


# ------------------------------------------------------------------------------
# Graph Construction & Compilation
# ------------------------------------------------------------------------------
def build_agent_graph() -> StateGraph:
    """Construct the LangGraph workflow with strict bounded transitions."""
    builder = StateGraph(AgentGraphState)

    # Add nodes
    builder.add_node("load_context", load_decision_context_node)
    builder.add_node("investigator", investigator_node)
    builder.add_node("verifier", verifier_node)
    builder.add_node("human_review_escalation", human_review_escalation_node)
    builder.add_node("action_orchestrator", action_orchestrator_node)
    builder.add_node("finalize", finalize_agent_result_node)

    # Define edges
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "investigator")
    builder.add_edge("investigator", "verifier")

    # Conditional branching after Verifier
    builder.add_conditional_edges(
        "verifier",
        verifier_routing_condition,
        {
            "human_review_escalation": "human_review_escalation",
            "action_orchestrator": "action_orchestrator",
        },
    )

    # Join paths to finalize
    builder.add_edge("human_review_escalation", "finalize")
    builder.add_edge("action_orchestrator", "finalize")
    builder.add_edge("finalize", END)

    return builder


# Compile singleton graph
agent_workflow_graph = build_agent_graph().compile()


# ------------------------------------------------------------------------------
# Public Execution API
# ------------------------------------------------------------------------------
async def run_agent_workflow(
    initial_state: AgentGraphState,
    timeout_ms: int | None = None,
) -> AgentWorkflowResult:
    """Execute the asynchronous multi-agent orchestration workflow.

    Enforces:
    - Bounded execution with strict timeout (AGENT_TOTAL_TIMEOUT_MS)
    - Complete numerical truth immutability (p_return_abuse & selected_action)
    - Resilient fallback on any failure
    """
    start_time = time.perf_counter()
    timeout_sec = float(timeout_ms or settings.AGENT_TOTAL_TIMEOUT_MS) / 1000.0

    decision_id = initial_state.get("decision_id") or uuid.uuid4()
    risk_decision_id = initial_state.get("risk_decision_id") or uuid.uuid4()
    policy_decision_id = initial_state.get("policy_decision_id") or uuid.uuid4()
    p_return_abuse = float(initial_state.get("p_return_abuse", 0.0))
    risk_band = str(initial_state.get("risk_band", "LOW"))
    selected_action: Action = initial_state.get("selected_action", Action.A0)

    try:
        # Bounded execution with total graph timeout
        final_state: dict[str, Any] = await asyncio.wait_for(
            agent_workflow_graph.ainvoke(initial_state),
            timeout=timeout_sec,
        )

        total_latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Extract structured outputs
        inv_res = final_state.get("investigator_result")
        v_res = final_state.get("verifier_result")
        orch_res = final_state.get("orchestrator_result")

        expected_loss = float(initial_state.get("expected_loss", 0.0))
        expected_net_value = float(initial_state.get("expected_net_value", 0.0))

        # Determine workflow-level provenance
        is_llm = bool(
            inv_res and inv_res.is_llm_generated
            and v_res and v_res.is_llm_generated
            and (orch_res is None or orch_res.is_llm_generated)
        )
        if is_llm:
            provider = "GEMINI"
            fallback_reason = None
            model_name = settings.GEMINI_MODEL
        else:
            provider = "DETERMINISTIC_FALLBACK"
            reasons = [
                r.fallback_reason
                for r in (inv_res, v_res, orch_res)
                if r is not None and r.fallback_reason
            ]
            fallback_reason = reasons[0] if reasons else "PROVIDER_UNAVAILABLE"
            model_name = None

        # Guarantee numerical immutability
        # If any agent somehow touched p_return_abuse or selected_action, preserve original!
        return AgentWorkflowResult(
            decision_id=decision_id,
            risk_decision_id=risk_decision_id,
            policy_decision_id=policy_decision_id,
            p_return_abuse=p_return_abuse,  # strictly preserved
            risk_band=risk_band,  # strictly preserved
            selected_action=selected_action,  # strictly preserved
            expected_loss=expected_loss,  # strictly preserved
            expected_net_value=expected_net_value,  # strictly preserved
            provider=provider,
            is_llm_generated=is_llm,
            fallback_reason=fallback_reason,
            model_name=model_name,
            investigator_result=inv_res,
            verifier_result=v_res,
            orchestrator_result=orch_res,
            requires_human_review=final_state.get("requires_human_review", False),
            disagreements=final_state.get("disagreements", []),
            final_agent_recommendation=final_state.get("final_agent_recommendation", "CONFIRM"),
            agent_status=final_state.get("agent_status", AgentRunStatus.COMPLETED),
            agent_errors=final_state.get("agent_errors", []),
            latency_ms=total_latency_ms,
            trace_id=final_state.get("trace_id", str(uuid.uuid4())),
        )

    except asyncio.TimeoutError:
        total_latency_ms = (time.perf_counter() - start_time) * 1000.0
        logger.warning(
            "Agent workflow for decision %s timed out after %.2f s. Returning degraded result.",
            decision_id,
            timeout_sec,
        )
        return AgentWorkflowResult(
            decision_id=decision_id,
            risk_decision_id=risk_decision_id,
            policy_decision_id=policy_decision_id,
            p_return_abuse=p_return_abuse,
            risk_band=risk_band,
            selected_action=selected_action,
            expected_loss=float(initial_state.get("expected_loss", 0.0)),
            expected_net_value=float(initial_state.get("expected_net_value", 0.0)),
            provider="DETERMINISTIC_FALLBACK",
            is_llm_generated=False,
            fallback_reason="TIMEOUT",
            model_name=None,
            requires_human_review=True,
            disagreements=["Workflow timed out"],
            final_agent_recommendation="DEGRADED_TIMEOUT",
            agent_status=AgentRunStatus.DEGRADED,
            agent_errors=[f"Workflow exceeded total timeout of {timeout_sec}s"],
            latency_ms=total_latency_ms,
            trace_id=initial_state.get("trace_id", str(uuid.uuid4())),
        )

    except Exception as e:
        total_latency_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error("Agent workflow for decision %s failed: %s", decision_id, e, exc_info=True)
        return AgentWorkflowResult(
            decision_id=decision_id,
            risk_decision_id=risk_decision_id,
            policy_decision_id=policy_decision_id,
            p_return_abuse=p_return_abuse,
            risk_band=risk_band,
            selected_action=selected_action,
            expected_loss=float(initial_state.get("expected_loss", 0.0)),
            expected_net_value=float(initial_state.get("expected_net_value", 0.0)),
            provider="DETERMINISTIC_FALLBACK",
            is_llm_generated=False,
            fallback_reason="OTHER",
            model_name=None,
            requires_human_review=True,
            disagreements=[f"Workflow execution failure: {e}"],
            final_agent_recommendation="DEGRADED_ERROR",
            agent_status=AgentRunStatus.FAILED,
            agent_errors=[str(e)],
            latency_ms=total_latency_ms,
            trace_id=initial_state.get("trace_id", str(uuid.uuid4())),
        )
