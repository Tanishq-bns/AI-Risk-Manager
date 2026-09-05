"""Unit tests for Phase 5 LinUCB Contextual Bandit, Guardrails, and Fallback.

Verifies:
1. LinUCB action initialization and ridge regularization.
2. Context vector construction (d=10) and boundary normalization.
3. Deterministic action selection when exploration is disabled.
4. Exploration bonus calculation when exploration is enabled.
5. Online update modifies parameters in the expected direction.
6. Guardrail rules (G01-G05) enforcement.
7. Deterministic safe fallback behavior under failures.
"""

from pathlib import Path
import tempfile
import numpy as np
import pytest

from risk_manager.domain.schemas.economics import ActionEvaluation
from risk_manager.domain.schemas.enums import Action, ActionSelector, RiskBand
from risk_manager.ml.bandit.fallback import DeterministicPolicyFallback
from risk_manager.ml.bandit.guardrails import PolicyGuardrails
from risk_manager.ml.bandit.linucb import LinUCBPolicy


def test_linucb_initialization():
    """LinUCB initializes A_a as identity (d=10) and b_a as zeros for all actions."""
    bandit = LinUCBPolicy(dimension=10, alpha=0.25, exploration_enabled=False)
    assert len(bandit.A) == 5
    assert len(bandit.b) == 5

    for action in Action:
        np.testing.assert_array_equal(bandit.A[action], np.identity(10))
        np.testing.assert_array_equal(bandit.b[action], np.zeros((10, 1)))


def test_context_vector_construction():
    """Context vector must be strictly 10-dimensional with all elements bounded."""
    bandit = LinUCBPolicy(dimension=10)

    fv = {
        "order_value": 5000.0,
        "customer_return_rate": 0.35,
        "days_since_purchase": 7,
        "cod_flag": True,
        "reverse_logistics_cost": 120.0,
        "customer_return_count": 3,
    }

    ctx = bandit.construct_context_vector(fv, p_return_abuse=0.45, risk_band=RiskBand.MEDIUM).flatten()
    assert ctx.shape == (10,)
    assert ctx[0] == pytest.approx(0.45)  # p_return_abuse
    assert 0.0 <= ctx[2] <= 1.0  # order_value_norm
    assert ctx[3] == pytest.approx(0.35)  # customer_return_rate
    assert ctx[6] == 1.0  # cod_flag
    assert ctx[9] == 1.0  # bias intercept


def test_deterministic_action_selection():
    """When exploration is disabled, bonus must be exactly 0.0 and selection is deterministic."""
    bandit = LinUCBPolicy(dimension=10, alpha=0.5, exploration_enabled=False)
    ctx = np.zeros((10, 1))
    ctx[0, 0] = 0.5

    priors = {
        Action.A0: 0.0,
        Action.A1: 150.0,
        Action.A2: 300.0,
        Action.A3: 200.0,
        Action.A4: 400.0,
    }

    # All eligible: A4 has highest prior
    chosen, reward, bonus = bandit.select_action(
        ctx, eligible_actions=[Action.A0, Action.A1, Action.A2, Action.A3, Action.A4],
        fallback_economic_priors=priors
    )
    assert chosen == Action.A4
    assert bonus == 0.0

    # If A4 is not eligible, A2 should be selected
    chosen_filtered, _, bonus = bandit.select_action(
        ctx, eligible_actions=[Action.A0, Action.A1, Action.A2],
        fallback_economic_priors=priors
    )
    assert chosen_filtered == Action.A2
    assert bonus == 0.0


def test_exploration_bonus():
    """When exploration is enabled, bonus is non-zero and accounts for uncertainty."""
    bandit = LinUCBPolicy(dimension=10, alpha=0.5, exploration_enabled=True)
    ctx = np.ones((10, 1)) / np.sqrt(10)

    chosen, reward, bonus = bandit.select_action(
        ctx, eligible_actions=[Action.A0, Action.A1],
        fallback_economic_priors={Action.A0: 0.0, Action.A1: 10.0}
    )
    # Uncertainty bonus = alpha * sqrt(x^T A^-1 x) = 0.5 * sqrt(1.0) = 0.5
    assert bonus == pytest.approx(0.5)


def test_linucb_online_update():
    """Updating action model increases theta in direction of context and reward."""
    bandit = LinUCBPolicy(dimension=10, exploration_enabled=False)
    ctx = np.zeros((10, 1))
    ctx[0, 0] = 1.0  # High risk feature

    # Prior theta is 0
    np.testing.assert_array_equal(bandit.b[Action.A2], np.zeros((10, 1)))

    # Update with positive reward 500
    bandit.update(Action.A2, ctx, reward=500.0)

    # b_a should have updated
    assert bandit.b[Action.A2][0, 0] == 500.0
    # A_a should have updated: A += ctx @ ctx^T
    assert bandit.A[Action.A2][0, 0] == 2.0  # 1.0 (identity) + 1.0*1.0


def test_linucb_save_load():
    """LinUCB state can be saved and reloaded accurately."""
    bandit = LinUCBPolicy(dimension=10, alpha=0.3, exploration_enabled=True)
    ctx = np.ones((10, 1))
    bandit.update(Action.A1, ctx, reward=100.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "bandit.joblib"
        bandit.save(save_path)

        loaded = LinUCBPolicy.load(save_path)
        assert loaded.dimension == 10
        assert loaded.alpha == pytest.approx(0.3)
        assert loaded.exploration_enabled is True
        np.testing.assert_array_equal(loaded.b[Action.A1], bandit.b[Action.A1])
        np.testing.assert_array_equal(loaded.A[Action.A1], bandit.A[Action.A1])


def test_guardrails_g01_low_order_value():
    """G01: Orders under INR 100 must disallow all friction actions and force A0."""
    guardrails = PolicyGuardrails()
    evals = [
        ActionEvaluation(action=a, action_name=a.value, expected_loss=10.0, expected_net_value=10.0,
                         friction_cost=0.0, operational_cost=0.0)
        for a in Action
    ]

    eligible = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 85.0},
        p_return_abuse=0.8,
        risk_band=RiskBand.HIGH,
        evaluations=evals,
    )
    assert eligible == [Action.A0]


def test_guardrails_g02_low_risk_band():
    """G02: LOW risk band customers must receive zero friction (only A0)."""
    guardrails = PolicyGuardrails()
    evals = [
        ActionEvaluation(action=a, action_name=a.value, expected_loss=100.0, expected_net_value=50.0,
                         friction_cost=10.0, operational_cost=10.0)
        for a in Action
    ]

    eligible = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 2000.0},
        p_return_abuse=0.05,
        risk_band=RiskBand.LOW,
        evaluations=evals,
    )
    assert eligible == [Action.A0]


def test_guardrails_g03_automated_execution():
    """G03: Automated mode must disallow manual review (A4)."""
    guardrails = PolicyGuardrails()
    evals = [
        ActionEvaluation(action=a, action_name=a.value, expected_loss=100.0, expected_net_value=50.0,
                         friction_cost=10.0, operational_cost=10.0)
        for a in Action
    ]

    eligible_auto = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 2000.0},
        p_return_abuse=0.6,
        risk_band=RiskBand.HIGH,
        evaluations=evals,
        is_automated=True,
    )
    assert Action.A4 not in eligible_auto

    eligible_manual = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 2000.0},
        p_return_abuse=0.6,
        risk_band=RiskBand.HIGH,
        evaluations=evals,
        is_automated=False,
    )
    assert Action.A4 in eligible_manual


def test_guardrails_g04_negative_net_value():
    """G04: Interventions with negative expected net value must be disqualified."""
    guardrails = PolicyGuardrails()
    evals = [
        ActionEvaluation(action=Action.A0, action_name="A0", expected_loss=200.0, expected_net_value=0.0,
                         friction_cost=0.0, operational_cost=0.0),
        ActionEvaluation(action=Action.A1, action_name="A1", expected_loss=250.0, expected_net_value=-50.0,
                         friction_cost=50.0, operational_cost=20.0),
        ActionEvaluation(action=Action.A2, action_name="A2", expected_loss=150.0, expected_net_value=50.0,
                         friction_cost=40.0, operational_cost=60.0),
    ]

    eligible = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 2000.0},
        p_return_abuse=0.4,
        risk_band=RiskBand.MEDIUM,
        evaluations=evals,
        is_automated=True,
    )
    assert Action.A1 not in eligible
    assert Action.A2 in eligible
    assert Action.A0 in eligible


def test_guardrails_g05_product_category():
    """G05: Non-restockable categories (BEAUTY) cannot receive doorstep inspection (A2)."""
    guardrails = PolicyGuardrails()
    evals = [
        ActionEvaluation(action=Action.A0, action_name="A0", expected_loss=200.0, expected_net_value=0.0,
                         friction_cost=0.0, operational_cost=0.0),
        ActionEvaluation(action=Action.A2, action_name="A2", expected_loss=100.0, expected_net_value=100.0,
                         friction_cost=40.0, operational_cost=60.0),
    ]

    eligible = guardrails.filter_eligible_actions(
        feature_vector={"order_value": 2000.0, "product_category": "BEAUTY"},
        p_return_abuse=0.7,
        risk_band=RiskBand.HIGH,
        evaluations=evals,
        is_automated=True,
    )
    assert Action.A2 not in eligible
    assert Action.A0 in eligible


def test_deterministic_fallback():
    """DeterministicPolicyFallback correctly assigns conservative actions based on risk band."""
    fallback = DeterministicPolicyFallback()

    # LOW risk -> A0
    act_low, _ = fallback.select_fallback_action(
        feature_vector={"order_value": 1500.0}, p_return_abuse=0.1, risk_band=RiskBand.LOW,
        eligible_actions=[Action.A0, Action.A1, Action.A2]
    )
    assert act_low == Action.A0

    # MEDIUM risk -> A1
    act_med, _ = fallback.select_fallback_action(
        feature_vector={"order_value": 1500.0}, p_return_abuse=0.4, risk_band=RiskBand.MEDIUM,
        eligible_actions=[Action.A0, Action.A1, Action.A2]
    )
    assert act_med == Action.A1

    # HIGH risk -> A2
    act_high, _ = fallback.select_fallback_action(
        feature_vector={"order_value": 1500.0}, p_return_abuse=0.8, risk_band=RiskBand.HIGH,
        eligible_actions=[Action.A0, Action.A1, Action.A2]
    )
    assert act_high == Action.A2
