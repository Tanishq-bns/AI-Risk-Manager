"""Investigator agent node for LangGraph multi-agent orchestration.

Implements Phase 6 Investigator requirements §2, §6, §8, §16.
Synthesizes evidence and identifies risk/mitigating factors while strictly adhering
to the immutable numerical boundary.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from risk_manager.agents.llm import default_agent_llm
from risk_manager.agents.prompts import (
    INVESTIGATOR_SYSTEM_PROMPT,
    INVESTIGATOR_USER_PROMPT_TEMPLATE,
)
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.tools import (
    clear_workflow_tool_context,
    set_workflow_tool_context,
)
from risk_manager.domain.schemas.agents import InvestigationResult
from risk_manager.domain.schemas.enums import (
    AgentName,
    AgentRunStatus,
    EvidenceQuality,
)
from risk_manager.observability.tracer import traced

logger = logging.getLogger(__name__)


@traced("agent.investigator")
async def investigator_node(state: AgentGraphState) -> dict[str, Any]:
    """Execute the Investigator agent node within the LangGraph workflow."""
    start_time = time.perf_counter()
    errors: list[str] = list(state.get("agent_errors", []))
    latencies: dict[str, float] = dict(state.get("latencies_ms", {}))

    try:
        # Set allowlisted tool context for current decision
        set_workflow_tool_context(dict(state))

        # Extract authoritative read-only evidence
        decision_id = state.get("decision_id")
        p_return_abuse = state.get("p_return_abuse", 0.0)
        risk_band = state.get("risk_band", "LOW")
        scoring_source = state.get("scoring_source", "XGBOOST")
        fallback_tier = state.get("fallback_tier", 0)
        selected_action = state.get("selected_action")
        expected_net_value = state.get("expected_net_value", 0.0)
        guardrails_applied = state.get("guardrails_applied", [])

        feature_evidence = state.get("feature_evidence", {})
        customer_history = state.get("customer_history", {})

        order_value = customer_history.get("order_value", 0.0)
        payment_method = customer_history.get("payment_method", "PREPAID")
        order_count = customer_history.get("order_count", 0)
        return_count = customer_history.get("return_count", 0)
        historical_abuse_rate = customer_history.get("historical_abuse_rate", 0.0)

        # Untrusted customer inputs - sanitized into passive string
        return_reason = str(customer_history.get("return_reason", "Not provided"))
        customer_notes = str(customer_history.get("customer_notes", "None"))

        # Render prompts with strict security boundaries
        user_prompt = INVESTIGATOR_USER_PROMPT_TEMPLATE.format(
            decision_id=decision_id,
            p_return_abuse=p_return_abuse,
            risk_band=risk_band,
            scoring_source=scoring_source,
            fallback_tier=fallback_tier,
            selected_action=selected_action.value if hasattr(selected_action, "value") else str(selected_action),
            expected_net_value=expected_net_value,
            guardrails_applied=", ".join(guardrails_applied) if guardrails_applied else "None",
            feature_telemetry=str(feature_evidence),
            order_value=order_value,
            payment_method=payment_method,
            order_count=order_count,
            return_count=return_count,
            historical_abuse_rate=historical_abuse_rate,
            return_reason=return_reason,
            customer_notes=customer_notes,
        )

        result = await default_agent_llm.invoke_structured(
            schema=InvestigationResult,
            system_prompt=INVESTIGATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=dict(state),
            agent_name=AgentName.INVESTIGATOR,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["investigator"] = latency_ms

        logger.info(
            "Investigator node completed for decision %s in %.2f ms (evidence_quality=%s)",
            decision_id,
            latency_ms,
            result.evidence_quality.value,
        )

        return {
            "investigator_result": result,
            "latencies_ms": latencies,
            "agent_errors": errors,
        }

    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["investigator"] = latency_ms
        err_msg = f"Investigator node failed: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

        # Fallback conservative result ensuring no crash
        fallback_res = InvestigationResult(
            case_id=state.get("decision_id"),
            agent_name=AgentName.INVESTIGATOR,
            status=AgentRunStatus.FAILED,
            evidence_summary=f"Investigation failed due to: {e}",
            evidence_quality=EvidenceQuality.LOW,
            confidence=0.0,
            recommendation="ESCALATE",
        )

        return {
            "investigator_result": fallback_res,
            "latencies_ms": latencies,
            "agent_errors": errors,
            "agent_status": AgentRunStatus.DEGRADED,
            "requires_human_review": True,
        }
    finally:
        clear_workflow_tool_context()
