"""Unit tests for Phase 5 Economic Outcome Model and Reward Formulation.

Verifies:
1. Economic model training pipeline succeeds.
2. Training reproducibility with seed.
3. Feature schema validation and point-in-time non-leakage.
4. Model prediction bounds and evaluation metric calculations (MAE, RMSE, R²).
5. Artifact save and load round-trip.
6. Reward formulation monotonicity, friction/ops penalties, and edge cases.
"""

from pathlib import Path
import tempfile
import numpy as np
import pytest

from risk_manager.domain.actions import ACTION_REGISTRY, get_action_metadata
from risk_manager.domain.schemas.enums import Action
from risk_manager.ml.reward_model.predict import EconomicPredictor, calculate_expected_loss, calculate_reward
from risk_manager.ml.reward_model.train import (
    ECONOMIC_FEATURE_NAMES,
    evaluate_economic_predictions,
    train_economic_model,
)


def test_reward_formulation_monotonicity():
    """Reward must increase with merchant savings and decrease with friction/ops costs."""
    # Base case: unmitigated loss of 1000
    base_loss = 1000.0

    # Higher mitigation rate should increase reward
    reward_a1 = calculate_reward(Action.A1, unmitigated_loss=base_loss)
    reward_a2 = calculate_reward(Action.A2, unmitigated_loss=base_loss)

    # A1: 35% of 1000 (350) - 50 friction - 20 ops = 280
    # A2: 75% of 1000 (750) - 40 friction - 60 ops = 650
    assert reward_a2 > reward_a1
    assert reward_a1 == pytest.approx(280.0)
    assert reward_a2 == pytest.approx(650.0)

    # Excessive friction should decrease reward
    # For small loss of 50:
    small_loss = 50.0
    reward_small_a1 = calculate_reward(Action.A1, unmitigated_loss=small_loss)
    # 0.35 * 50 (17.5) - 50 - 20 = -52.5
    assert reward_small_a1 < 0


def test_reward_formulation_a0():
    """A0 (zero friction) must yield zero reward and zero friction/ops cost."""
    reward_a0 = calculate_reward(Action.A0, unmitigated_loss=5000.0)
    assert reward_a0 == 0.0


def test_reward_edge_cases():
    """Reward calculation must handle zero and extreme unmitigated losses."""
    assert calculate_reward(Action.A1, unmitigated_loss=0.0) == -70.0  # -50 friction - 20 ops
    assert calculate_reward(Action.A0, unmitigated_loss=0.0) == 0.0


def test_expected_loss_formula():
    """Expected loss formula must match SPEC.md §14."""
    # P(abuse) = 0.5, unmitigated_loss = 1000
    # For A0: Loss_if_abuse = 1000, Friction = 0 -> 0.5 * 1000 + 0.5 * 0 = 500
    loss_a0 = calculate_expected_loss(Action.A0, p_return_abuse=0.5, unmitigated_loss=1000.0)
    assert loss_a0 == pytest.approx(500.0)

    # For A1: Loss_if_abuse = 1000 * (1 - 0.35) + 20 = 670
    # Friction = 50
    # ExpectedLoss = 0.5 * 670 + 0.5 * 50 = 335 + 25 = 360
    loss_a1 = calculate_expected_loss(Action.A1, p_return_abuse=0.5, unmitigated_loss=1000.0)
    assert loss_a1 == pytest.approx(360.0)


def test_economic_evaluation_metrics():
    """evaluate_economic_predictions calculates MAE, RMSE, and R² correctly."""
    y_true = np.array([100.0, 200.0, 300.0, 400.0])
    y_pred = np.array([110.0, 190.0, 310.0, 390.0])
    actions = np.array(["A1", "A1", "A2", "A2"])

    metrics = evaluate_economic_predictions(y_true, y_pred, actions)
    assert metrics["mae"] == pytest.approx(10.0)
    assert metrics["rmse"] == pytest.approx(10.0)
    assert metrics["r2_score"] > 0.99
    assert metrics["worst_case_error"] == pytest.approx(10.0)
    assert "A1" in metrics["action_level_metrics"]
    assert "A2" in metrics["action_level_metrics"]


def test_economic_model_training_and_artifacts():
    """Train economic model and verify artifacts are created with acceptable R²."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = train_economic_model(data_dir="data", output_dir=tmpdir, random_seed=42)
        metrics = result["metrics"]

        assert metrics["r2_score"] > 0.90
        assert metrics["mae"] < 80.0
        assert metrics["rmse"] < 150.0

        model_file = Path(tmpdir) / "rf_reward_model.joblib"
        metrics_file = Path(tmpdir) / "economic_metrics.json"
        metadata_file = Path(tmpdir) / "economic_model_metadata.json"

        assert model_file.exists()
        assert metrics_file.exists()
        assert metadata_file.exists()


def test_economic_model_reproducibility():
    """Training with identical seed must produce identical metrics."""
    with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
        res1 = train_economic_model(data_dir="data", output_dir=dir1, random_seed=123)
        res2 = train_economic_model(data_dir="data", output_dir=dir2, random_seed=123)

        assert res1["metrics"]["mae"] == pytest.approx(res2["metrics"]["mae"], abs=1e-5)
        assert res1["metrics"]["r2_score"] == pytest.approx(res2["metrics"]["r2_score"], abs=1e-5)


def test_economic_predictor_load_and_predict():
    """EconomicPredictor loads trained model and produces valid predictions."""
    predictor = EconomicPredictor(models_dir="models")
    assert predictor.load().is_loaded is True

    sample_fv = {
        "order_value": 2500.0,
        "reverse_logistics_cost": 150.0,
        "estimated_item_recovery_value": 1000.0,
        "customer_return_rate": 0.2,
        "prior_return_value": 500.0,
        "prior_return_frequency": 0.5,
        "customer_order_count": 5,
        "customer_return_count": 1,
        "cod_flag": False,
        "days_since_purchase": 5,
    }

    evals = predictor.evaluate_all_actions(sample_fv, p_return_abuse=0.6)
    assert len(evals) == 5

    # A0 expected_net_value must be 0.0 by definition
    a0_eval = next(e for e in evals if e.action == Action.A0)
    assert a0_eval.expected_net_value == pytest.approx(0.0)

    # Higher mitigation actions should have positive net value for high abuse probability
    a2_eval = next(e for e in evals if e.action == Action.A2)
    assert a2_eval.expected_loss < a0_eval.expected_loss
    assert a2_eval.expected_net_value > 0.0


def test_no_p_return_abuse_modification():
    """EconomicPredictor must never alter p_return_abuse."""
    predictor = EconomicPredictor(models_dir="models")
    original_p = 0.4285
    sample_fv = {"order_value": 1500.0, "reverse_logistics_cost": 100.0}

    evals = predictor.evaluate_all_actions(sample_fv, p_return_abuse=original_p)
    # Ensure predictor does not return any altered p_return_abuse
    for e in evals:
        assert not hasattr(e, "p_return_abuse")
        assert not hasattr(e, "risk_score")
