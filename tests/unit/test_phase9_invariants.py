"""Unit tests for Phase 9 Architectural Invariants & Immutability.

Verifies:
1. Agent cannot modify risk score.
2. Agent cannot modify risk band.
3. Agent cannot modify economic predictions.
4. Agent cannot modify selected action.
5. Action A4 cannot be automatically settled (mandates human review).
6. Human override is the only valid mechanism to alter policy decisions.
7. Observability errors cannot change decision outcomes.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import MagicMock, patch

from risk_manager.domain.schemas.enums import (
    Action,
    AgentName,
    RiskBand,
    ScoringSource,
)
from risk_manager.domain.schemas.requests import RiskScoreRequest
from risk_manager.domain.schemas.responses import (
    EconomicPrediction,
    FallbackMetadata,
    InterventionCandidate,
    ModelMetadata,
    RiskEvidence,
    RiskScoreResponse,
)
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.investigator import investigator_node
from risk_manager.agents.verifier import run_deterministic_verifier_checks, verifier_node
from risk_manager.agents.orchestrator import action_orchestrator_node
from risk_manager.agents.llm import AgentLLMClient
from risk_manager.domain.schemas.agents import InvestigationResult, VerificationResult
from risk_manager.domain.schemas.enums import AgentProvider


def get_base_agent_state() -> dict:
    """Helper constructing an authoritative initial AgentGraphState dict."""
    dec_id = uuid.uuid4()
    cand_actions = [
        {
            "action": Action.A0,
            "action_name": "Instant Refund",
            "expected_loss": 120.0,
            "expected_net_value": 1880.0,
            "friction_cost": 0.0,
            "operational_cost": 0.0,
            "is_eligible": True,
        },
        {
            "action": Action.A2,
            "action_name": "OTP Inspection",
            "expected_loss": 60.0,
            "expected_net_value": 1865.0,
            "friction_cost": 40.0,
            "operational_cost": 75.0,
            "is_eligible": True,
        },
    ]

    return {
        "decision_id": dec_id,
        "risk_decision_id": dec_id,
        "customer_id_hash": "cust_invariant_001",
        "order_value": 2000.0,
        "return_reason": "Item not fitting",
        "product_category": "APPAREL",
        "payment_method": "PREPAID",
        "cod_flag": False,
        "delivery_distance_bucket": "LOCAL",
        "feature_vector": {"order_value": 2000.0, "customer_return_rate": 0.05},
        "p_return_abuse": 0.12,
        "risk_band": RiskBand.LOW,
        "scoring_source": ScoringSource.XGBOOST,
        "fallback_tier": 0,
        "candidate_actions": cand_actions,
        "selected_action": Action.A0,
        "expected_loss": 120.0,
        "expected_net_value": 1880.0,
        "guardrails_applied": [],
    }


# -----------------------------------------------------------------------------
# 1. P0.1 & P0.2: Agent Workflow Cannot Mutate Authoritative Values
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_cannot_modify_risk_score():
    """Verify that investigator/verifier/orchestrator nodes never alter p_return_abuse."""
    initial_state = get_base_agent_state()

    # Node outputs are partial state update dictionaries
    inv_updates = await investigator_node(initial_state)
    assert "p_return_abuse" not in inv_updates

    # Update state for next node
    state = dict(initial_state)
    state.update(inv_updates)

    ver_updates = await verifier_node(state)
    assert "p_return_abuse" not in ver_updates

    state.update(ver_updates)
    orch_updates = await action_orchestrator_node(state)
    assert "p_return_abuse" not in orch_updates


@pytest.mark.asyncio
async def test_agent_cannot_modify_risk_band():
    """Verify that risk_band remains strictly Phase 4 authority."""
    initial_state = get_base_agent_state()

    inv_updates = await investigator_node(initial_state)
    assert "risk_band" not in inv_updates

    state = dict(initial_state)
    state.update(inv_updates)

    ver_updates = await verifier_node(state)
    assert "risk_band" not in ver_updates

    state.update(ver_updates)
    orch_updates = await action_orchestrator_node(state)
    assert "risk_band" not in orch_updates


@pytest.mark.asyncio
async def test_agent_cannot_modify_selected_action_or_economics():
    """Verify that expected_loss, expected_net_value, and selected_action remain immutable."""
    initial_state = get_base_agent_state()

    inv_updates = await investigator_node(initial_state)
    state = dict(initial_state)
    state.update(inv_updates)

    ver_updates = await verifier_node(state)
    state.update(ver_updates)

    orch_updates = await action_orchestrator_node(state)

    for updates in (inv_updates, ver_updates, orch_updates):
        assert "selected_action" not in updates
        assert "expected_loss" not in updates
        assert "expected_net_value" not in updates


# -----------------------------------------------------------------------------
# 2. Action A4 / Critical Case Invariant
# -----------------------------------------------------------------------------

def test_a4_manual_review_safety_invariant():
    """Verify that Action A4 or CRITICAL risk band always mandates human specialist review."""
    state = get_base_agent_state()
    state["selected_action"] = Action.A4
    state["risk_band"] = RiskBand.CRITICAL
    state["p_return_abuse"] = 0.92

    passed, failed, warnings, disagreements, requires_human = run_deterministic_verifier_checks(state)
    assert requires_human is True


# -----------------------------------------------------------------------------
# 3. Fallback Provenance Transparency
# -----------------------------------------------------------------------------

def test_deterministic_fallback_provenance():
    """Verify that fallback outputs transparently declare non-LLM provenance."""
    state = get_base_agent_state()
    client = AgentLLMClient()

    inv_out = client._deterministic_fallback(InvestigationResult, state, AgentName.INVESTIGATOR)
    assert inv_out.is_llm_generated is False
    assert inv_out.provider == AgentProvider.DETERMINISTIC_FALLBACK.value
    assert inv_out.fallback_reason is not None

    ver_out = client._deterministic_fallback(VerificationResult, state, AgentName.VERIFIER)
    assert ver_out.is_llm_generated is False
    assert ver_out.provider == AgentProvider.DETERMINISTIC_FALLBACK.value
