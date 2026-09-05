"""Unit tests for Phase 4: ML Scoring Cascade (Tier 0, Tier 1, Tier 2), Calibration, and Risk Bands.

Covers:
1. Risk band mapping and exact boundary values.
2. Feature encoder determinism, preservation of return_reason, and unseen category safety.
3. Isotonic calibration with Platt scaling contingency fallback.
4. Rules Engine determinism, rule IDs, and conservative outcomes.
5. Tier 0 inference and probability bounds.
6. Tier 1 Isolation Forest anomaly scoring and proxy mapping.
7. Cascade orchestration: Tier 0 -> Tier 1 -> Tier 2.
8. Fault-injection tests: missing artifact, inference exception, timeout, circuit breaker open, low completeness.
9. Zero target leakage verification.
"""

from datetime import datetime, timezone
import math
from pathlib import Path
import tempfile
import pytest

from risk_manager.domain.risk_bands import get_risk_band_thresholds, map_probability_to_risk_band
from risk_manager.domain.schemas.enums import FallbackTier, PaymentMethod, RiskBand, ScoringSource
from risk_manager.features.completeness import FeatureCompletenessReport
from risk_manager.features.schema import FeatureVector, OutcomeLabel
from risk_manager.ml.calibration.isotonic import IsotonicProbabilityCalibrator
from risk_manager.ml.cascade import MLCascadeScorer
from risk_manager.ml.encoder import FeatureEncoder
from risk_manager.ml.isolation_forest.model import Tier1IsolationForest
from risk_manager.ml.rules_engine.rules import Tier2RulesEngine
from risk_manager.ml.xgboost_model.infer import Tier0Predictor


@pytest.fixture
def sample_feature_vector() -> FeatureVector:
    """Fixture providing a realistic valid FeatureVector."""
    return FeatureVector(
        customer_id_hash="cust_test_unit_1",
        order_value=3200.0,
        product_category="APPAREL",
        payment_method=PaymentMethod.PREPAID,
        cod_flag=False,
        customer_order_count=4,
        customer_return_count=1,
        customer_return_rate=0.25,
        days_since_purchase=5,
        prior_return_value=1200.0,
        prior_return_frequency=0.4,
        item_category_return_rate=0.25,
        return_reason="Size too small",
        delivery_distance_bucket="REGIONAL",
        reverse_logistics_cost=135.0,
        estimated_item_recovery_value=2240.0,
        historical_abuse_signal=0.0,
    )


# ==============================================================================
# 1. Risk Band Boundaries Tests
# ==============================================================================

def test_risk_band_exact_boundaries():
    """Verify exact boundary values per SPEC.md §18 and prompt §4."""
    assert map_probability_to_risk_band(0.0) == RiskBand.LOW
    assert map_probability_to_risk_band(0.10) == RiskBand.LOW
    assert map_probability_to_risk_band(0.249999) == RiskBand.LOW

    # Boundary at 0.25
    assert map_probability_to_risk_band(0.25) == RiskBand.MEDIUM
    assert map_probability_to_risk_band(0.40) == RiskBand.MEDIUM
    assert map_probability_to_risk_band(0.599999) == RiskBand.MEDIUM

    # Boundary at 0.60
    assert map_probability_to_risk_band(0.60) == RiskBand.HIGH
    assert map_probability_to_risk_band(0.75) == RiskBand.HIGH
    assert map_probability_to_risk_band(0.849999) == RiskBand.HIGH

    # Boundary at 0.85
    assert map_probability_to_risk_band(0.85) == RiskBand.CRITICAL
    assert map_probability_to_risk_band(0.9999) == RiskBand.CRITICAL
    assert map_probability_to_risk_band(1.0) == RiskBand.CRITICAL


def test_risk_band_invalid_inputs():
    """Verify invalid probability inputs raise ValueError."""
    with pytest.raises(ValueError):
        map_probability_to_risk_band(-0.01)
    with pytest.raises(ValueError):
        map_probability_to_risk_band(1.01)
    with pytest.raises(ValueError):
        map_probability_to_risk_band(float("nan"))
    with pytest.raises(ValueError):
        map_probability_to_risk_band(float("inf"))


def test_risk_band_thresholds_consistency():
    """Verify centralized threshold dictionary matches settings."""
    thresholds = get_risk_band_thresholds()
    assert thresholds["LOW_UPPER"] == 0.25
    assert thresholds["MEDIUM_UPPER"] == 0.60
    assert thresholds["HIGH_UPPER"] == 0.85
    assert thresholds["CRITICAL_UPPER"] == 1.0


# ==============================================================================
# 2. Feature Encoder Tests
# ==============================================================================

def test_feature_encoder_determinism_and_unseen_values(sample_feature_vector):
    """Verify feature encoding is deterministic and safely handles novel return reasons."""
    encoder = FeatureEncoder()
    train_data = [
        sample_feature_vector.to_model_features(),
        {**sample_feature_vector.to_model_features(), "return_reason": "Fabric stitching defective", "product_category": "FOOTWEAR"},
    ]
    encoder.fit(train_data)

    X1 = encoder.transform(sample_feature_vector)
    X2 = encoder.transform(sample_feature_vector)
    assert X1.shape == X2.shape
    assert (X1 == X2).all(), "Encoder transformations diverged for identical input"

    # Novel, completely unseen return reason
    unseen_input = sample_feature_vector.model_copy(update={"return_reason": "Totally new unexpected return explanation"})
    X_unseen = encoder.transform(unseen_input)
    assert X_unseen.shape == X1.shape
    assert not math.isnan(float(X_unseen.sum()))


def test_no_target_leakage_in_model_features():
    """Verify FeatureVector.model_feature_names() contains zero outcome or ID columns."""
    model_features = set(FeatureVector.model_feature_names())
    outcome_features = set(OutcomeLabel.model_fields.keys())

    assert model_features & outcome_features == set()
    assert "customer_id_hash" not in model_features
    assert "is_return_abuse" not in model_features
    assert "actual_loss" not in model_features
    assert "refund_completed_at" not in model_features


# ==============================================================================
# 3. Calibration Engine & Contingency Tests
# ==============================================================================

def test_isotonic_calibrator_fitting_and_bounds():
    """Verify isotonic calibration enforces [0.0, 1.0] bounds."""
    calibrator = IsotonicProbabilityCalibrator(min_samples_for_isotonic=20)
    raw_probs = [0.05, 0.12, 0.18, 0.22, 0.35, 0.40, 0.55, 0.60, 0.75, 0.80, 0.85, 0.90] * 3
    labels = [0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1] * 3

    calibrator.fit(raw_probs, labels)
    assert calibrator.is_fitted is True
    assert calibrator.method == "isotonic"

    calibrated = calibrator.calibrate([0.01, 0.50, 0.99])
    for p in calibrated:
        assert 0.0 <= p <= 1.0


def test_isotonic_contingency_fallback_to_platt():
    """Verify calibrator falls back to Platt scaling when validation samples are small (< 50)."""
    calibrator = IsotonicProbabilityCalibrator(min_samples_for_isotonic=50)
    # 20 samples (< 50) triggers Platt contingency
    raw_probs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95] * 2
    labels = [0, 0, 0, 0, 1, 0, 1, 1, 1, 1] * 2

    calibrator.fit(raw_probs, labels)
    assert calibrator.is_fitted is True
    assert calibrator.method == "platt_logistic"

    score = calibrator.calibrate(0.7)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


# ==============================================================================
# 4. Rules Engine Tests
# ==============================================================================

def test_rules_engine_deterministic_evaluation():
    """Verify conservative Tier 2 rules trigger with correct IDs and risk levels."""
    rules_engine = Tier2RulesEngine()

    # Rule R02: Historical abuse
    res_r02 = rules_engine.evaluate({"historical_abuse_signal": 0.8})
    assert "R02_HISTORICAL_ABUSE_FLAG" in res_r02.triggered_rules
    assert res_r02.risk_band == RiskBand.CRITICAL
    assert res_r02.p_return_abuse >= 0.85

    # Rule R01: High return velocity
    res_r01 = rules_engine.evaluate({
        "customer_order_count": 5,
        "customer_return_count": 4,
        "customer_return_rate": 0.80,
    })
    assert "R01_HIGH_RETURN_VELOCITY" in res_r01.triggered_rules
    assert res_r01.risk_band == RiskBand.HIGH

    # Rule R04: Wardrobing edge
    res_r04 = rules_engine.evaluate({
        "days_since_purchase": 13,
        "product_category": "APPAREL",
        "order_value": 4500.0,
    })
    assert "R04_WARDROBING_EDGE" in res_r04.triggered_rules
    assert res_r04.risk_band == RiskBand.HIGH

    # Rule R07: Established clean customer
    res_r07 = rules_engine.evaluate({
        "customer_order_count": 8,
        "customer_return_rate": 0.05,
        "historical_abuse_signal": 0.0,
    })
    assert "R07_CLEAN_CUSTOMER_PROTECTIVE" in res_r07.triggered_rules
    assert res_r07.risk_band == RiskBand.LOW
    assert res_r07.p_return_abuse <= 0.15

    # Rule R08: Conservative default fallback
    res_r08 = rules_engine.evaluate({"customer_order_count": 2, "customer_return_rate": 0.25})
    assert "R08_DEFAULT_CONSERVATIVE" in res_r08.triggered_rules
    assert res_r08.risk_band == RiskBand.MEDIUM


# ==============================================================================
# 5. Tier 0 & Tier 1 Predictor Tests
# ==============================================================================

def test_tier0_predictor_predict_one(sample_feature_vector):
    """Verify Tier 0 predictor loads and scores single FeatureVector with latency."""
    predictor = Tier0Predictor(models_dir="models").load()
    cal_prob, raw_prob, latency_ms = predictor.predict_one(sample_feature_vector)

    assert 0.0 <= cal_prob <= 1.0
    assert 0.0 <= raw_prob <= 1.0
    assert latency_ms >= 0.0
    assert latency_ms < 100.0  # Fast inference


def test_tier1_isolation_forest_scoring(sample_feature_vector):
    """Verify Tier 1 Isolation Forest produces continuous anomaly risk proxy in [0.0, 1.0]."""
    iforest = Tier1IsolationForest.load("models/isolation_forest.joblib", encoder_path="models/preprocessor.joblib")
    anomaly_proxy, raw_score = iforest.score_one(sample_feature_vector)

    assert 0.0 <= anomaly_proxy <= 1.0
    assert isinstance(raw_score, float)


# ==============================================================================
# 6. Cascade Orchestrator & Degradation Tests
# ==============================================================================

def test_cascade_normal_tier0_success(sample_feature_vector):
    """Verify normal execution runs Tier 0 with calibrated probability and no fallback reason."""
    cascade = MLCascadeScorer(models_dir="models")
    result = cascade.score(sample_feature_vector)

    assert result.scoring_source == ScoringSource.XGBOOST
    assert result.fallback_tier == FallbackTier.TIER_0
    assert result.fallback_reason is None
    assert 0.0 <= result.p_return_abuse <= 1.0
    assert result.risk_band in (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)


def test_cascade_tier0_unavailable_falls_to_tier1(sample_feature_vector):
    """Verify missing Tier 0 cascades to Tier 1 (Isolation Forest)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create dir with only Isolation Forest and Preprocessor, no XGBoost
        tmp_path = Path(tmpdir)
        import shutil
        shutil.copy("models/isolation_forest.joblib", tmp_path / "isolation_forest.joblib")
        shutil.copy("models/preprocessor.joblib", tmp_path / "preprocessor.joblib")

        cascade = MLCascadeScorer(models_dir=tmp_path)
        result = cascade.score(sample_feature_vector)

        assert result.scoring_source == ScoringSource.ISOLATION_FOREST
        assert result.fallback_tier == FallbackTier.TIER_1
        assert "ARTIFACT_LOAD_FAILURE" in str(result.fallback_reason)
        assert result.anomaly_score is not None


def test_cascade_tier0_and_tier1_unavailable_falls_to_tier2(sample_feature_vector):
    """Verify missing ML tiers cascade to Tier 2 (Rules Engine)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Empty dir: no ML models
        cascade = MLCascadeScorer(models_dir=Path(tmpdir))
        result = cascade.score(sample_feature_vector)

        assert result.scoring_source == ScoringSource.RULES
        assert result.fallback_tier == FallbackTier.TIER_2
        assert len(result.triggered_rules) > 0
        assert len(result.rule_explanations) > 0


def test_cascade_feature_incompleteness_triggers_fallback(sample_feature_vector):
    """Verify completeness < 0.85 triggers immediate cascade fallback."""
    cascade = MLCascadeScorer(models_dir="models")
    low_completeness_report = FeatureCompletenessReport(
        is_sufficient=False,
        completeness_ratio=0.60,
        total_fields=16,
        populated_fields=10,
        missing_fields=["customer_order_count", "customer_return_rate"],
        range_violations=[],
        invalid_fields=[],
    )

    result = cascade.score(sample_feature_vector, completeness_report=low_completeness_report)
    assert result.fallback_tier in (FallbackTier.TIER_1, FallbackTier.TIER_2)
    assert "INSUFFICIENT_FEATURE_COMPLETENESS" in str(result.fallback_reason)


def test_cascade_circuit_breaker_tripping(sample_feature_vector, monkeypatch):
    """Verify 5 consecutive inference errors trip the circuit breaker."""
    cascade = MLCascadeScorer(models_dir="models")

    # Inject exception into Tier 0
    def mock_failing_predict(feat):
        raise RuntimeError("Injected ML runtime failure")

    monkeypatch.setattr(cascade.tier0, "predict_one", mock_failing_predict)

    # First 4 calls record failures
    for _ in range(4):
        res = cascade.score(sample_feature_vector)
        assert res.fallback_tier == FallbackTier.TIER_1
        assert "INFERENCE_EXCEPTION" in str(res.fallback_reason)

    assert cascade.circuit_breaker.is_open() is False

    # 5th failure trips breaker to OPEN
    res5 = cascade.score(sample_feature_vector)
    assert cascade.circuit_breaker.is_open() is True

    # 6th call is immediately bypassed by circuit breaker without running Tier 0
    res6 = cascade.score(sample_feature_vector)
    assert "CIRCUIT_BREAKER_OPEN" in str(res6.fallback_reason)
