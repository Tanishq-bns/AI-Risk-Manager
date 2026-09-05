"""Action Orchestrator agent node for LangGraph multi-agent orchestration.

Implements Phase 6 Action Orchestrator requirements §2, §6, §8, §21.
Translates the authoritative Phase 5 policy decision into operational execution guidance
without altering actions, modifying numerical values, or performing side effects.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from risk_manager.agents.llm import default_agent_llm
from risk_manager.agents.prompts import (
    ACTION_ORCHESTRATOR_SYSTEM_PROMPT,
    ACTION_ORCHESTRATOR_USER_PROMPT_TEMPLATE,
)
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.tools import (
    clear_workflow_tool_context,
    set_workflow_tool_context,
)
from risk_manager.domain.schemas.agents import ActionDecision, InvestigationResult, VerificationResult
from risk_manager.domain.schemas.enums import Action, AgentName, AgentRunStatus
from risk_manager.observability.tracer import traced

logger = logging.getLogger(__name__)


@traced("agent.orchestrator")
async def action_orchestrator_node(state: AgentGraphState) -> dict[str, Any]:
    """Execute the Action Orchestrator agent node within the LangGraph workflow."""
    start_time = time.perf_counter()
    errors: list[str] = list(state.get("agent_errors", []))
    latencies: dict[str, float] = dict(state.get("latencies_ms", {}))

    try:
        set_workflow_tool_context(dict(state))

        selected_action: Action = state.get("selected_action", Action.A0)
        action_selector = state.get("action_selector", "LINUCB")
        expected_net_value = state.get("expected_net_value", 0.0)
        guardrails_applied = state.get("guardrails_applied", [])

        v_res: VerificationResult | None = state.get("verifier_result")
        inv_res: InvestigationResult | None = state.get("investigator_result")
        customer_history = state.get("customer_history", {})
        return_reason = str(customer_history.get("return_reason", "Not provided"))

        # Render prompts with strict security boundaries
        user_prompt = ACTION_ORCHESTRATOR_USER_PROMPT_TEMPLATE.format(
            selected_action=selected_action.value if hasattr(selected_action, "value") else str(selected_action),
            action_label=selected_action.label if hasattr(selected_action, "label") else str(selected_action),
            action_selector=action_selector,
            expected_net_value=expected_net_value,
            guardrails_applied=", ".join(guardrails_applied) if guardrails_applied else "None",
            verification_status=v_res.verification_status if v_res else "UNKNOWN",
            verifier_recommendation=v_res.recommendation.value if v_res else "UNKNOWN",
            requires_human_review=state.get("requires_human_review", False),
            disagreements=", ".join(state.get("disagreements", [])) or "None",
            warnings=", ".join(v_res.warnings) if v_res else "None",
            evidence_summary=inv_res.evidence_summary if inv_res else "None",
            investigator_recommendation=inv_res.recommendation if inv_res else "UNKNOWN",
            return_reason=return_reason,
        )

        result = await default_agent_llm.invoke_structured(
            schema=ActionDecision,
            system_prompt=ACTION_ORCHESTRATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=dict(state),
            agent_name=AgentName.ACTION_ORCHESTRATOR,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["orchestrator"] = latency_ms

        # IMMUTABILITY ENFORCEMENT:
        # Guarantee LLM cannot alter the Phase 5 selected action
        if result.selected_action_reference != selected_action:
            logger.warning(
                "Orchestrator attempted to alter selected action from %s to %s. Restoring authoritative action.",
                selected_action.value,
                result.selected_action_reference,
            )
            result.selected_action_reference = selected_action
            result.action = selected_action
            errors.append("Orchestrator attempted action alteration; authoritative action restored.")

        # If human review was required by verifier or action is A4, enforce it
        if state.get("requires_human_review") or selected_action == Action.A4:
            result.requires_human_review = True
            result.requires_manual_review = True
            result.execution_mode = "MANUAL_REVIEW_QUEUE"

        logger.info(
            "Action orchestrator node completed for action %s (mode=%s, requires_human_review=%s)",
            selected_action.value,
            result.execution_mode,
            result.requires_human_review,
        )

        return {
            "orchestrator_result": result,
            "final_agent_recommendation": result.operational_recommendation,
            "latencies_ms": latencies,
            "agent_errors": errors,
        }

    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["orchestrator"] = latency_ms
        err_msg = f"Action Orchestrator node failed: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

        fallback_action = state.get("selected_action", Action.A0)
        fallback_res = ActionDecision(
            agent_name=AgentName.ACTION_ORCHESTRATOR,
            status=AgentRunStatus.FAILED,
            provider="DETERMINISTIC_FALLBACK",
            is_llm_generated=False,
            fallback_reason="OTHER",
            model_name=None,
            selected_action_reference=fallback_action,
            execution_mode="MANUAL_REVIEW_QUEUE",
            operational_recommendation=f"Fallback routing for {fallback_action.value} due to orchestrator error: {e}",
            requires_human_review=True,
            blockers=[err_msg],
            confidence=0.0,
            action=fallback_action,
            rationale=err_msg,
            requires_manual_review=True,
        )

        return {
            "orchestrator_result": fallback_res,
            "final_agent_recommendation": "MANUAL_REVIEW",
            "latencies_ms": latencies,
            "agent_errors": errors,
            "agent_status": AgentRunStatus.DEGRADED,
            "requires_human_review": True,
        }
    finally:
        clear_workflow_tool_context()
