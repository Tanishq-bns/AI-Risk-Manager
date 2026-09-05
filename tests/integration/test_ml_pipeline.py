"""Integration tests and latency benchmarks for Phase 4 ML Scoring Subsystem.

Covers:
1. End-to-end training pipeline and artifact generation.
2. Training reproducibility with fixed seed.
3. 100-call inference latency benchmark asserting p95 <= 100ms.
4. Model governance promotion gates verification.
"""

from pathlib import Path
import tempfile
import time
import numpy as np
import pytest

from risk_manager.domain.schemas.enums import FallbackTier, PaymentMethod, ScoringSource
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.cascade import MLCascadeScorer
from risk_manager.ml.isolation_forest.model import train_isolation_forest
from risk_manager.ml.xgboost_model.train import train_tier0_model


@pytest.fixture
def benchmark_feature_vector() -> FeatureVector:
    return FeatureVector(
        customer_id_hash="cust_bench_1",
        order_value=2499.0,
        product_category="APPAREL",
        payment_method=PaymentMethod.COD,
        cod_flag=True,
        customer_order_count=3,
        customer_return_count=1,
        customer_return_rate=0.3333,
        days_since_purchase=2,
        prior_return_value=1500.0,
        prior_return_frequency=0.6,
        item_category_return_rate=0.25,
        return_reason="Delivery was delayed",
        delivery_distance_bucket="LOCAL",
        reverse_logistics_cost=95.0,
        estimated_item_recovery_value=1654.3,
        historical_abuse_signal=0.0,
    )


def test_end_to_end_training_and_promotion_gates():
    """Verify training runs end-to-end and satisfies target promotion gates (TRD.md §335-338)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir)
        result = train_tier0_model(data_dir="data", output_dir=out_path, random_seed=42)

        m = result["metrics"]
        # Promotion gates from TRD.md §J
        assert m["primary_metric_pr_auc"] >= 0.65, f"PR-AUC {m['primary_metric_pr_auc']} below target 0.65"
        assert m["brier_score"] <= 0.15, f"Brier score {m['brier_score']} above target 0.15"
        assert m["precision"] >= 0.70
        assert m["recall"] >= 0.60

        # Verify artifacts exist
        assert (out_path / "xgboost_model.joblib").exists()
        assert (out_path / "preprocessor.joblib").exists()
        assert (out_path / "isotonic_calibrator.joblib").exists()
        assert (out_path / "metrics.json").exists()
        assert (out_path / "model_metadata.json").exists()


def test_training_reproducibility_with_fixed_seed():
    """Verify training twice with the same seed produces identical evaluation metrics."""
    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        r1 = train_tier0_model(data_dir="data", output_dir=Path(tmpdir1), random_seed=123)
        r2 = train_tier0_model(data_dir="data", output_dir=Path(tmpdir2), random_seed=123)

        assert r1["metrics"]["primary_metric_pr_auc"] == r2["metrics"]["primary_metric_pr_auc"]
        assert r1["metrics"]["roc_auc"] == r2["metrics"]["roc_auc"]
        assert r1["metrics"]["brier_score"] == r2["metrics"]["brier_score"]
        assert r1["metrics"]["confusion_matrix"] == r2["metrics"]["confusion_matrix"]


def test_inference_latency_benchmark_100_calls(benchmark_feature_vector):
    """Benchmark 100 consecutive scoring calls through MLCascadeScorer.

    Target: Tier 0 model inference <= 100ms (TRD.md MODEL_INFERENCE_TIMEOUT_MS).
    """
    cascade = MLCascadeScorer(models_dir="models")
    assert cascade.tier0.is_loaded is True

    latencies_ms: list[float] = []

    # Warmup
    for _ in range(5):
        cascade.score(benchmark_feature_vector)

    # 100 benchmark iterations
    for _ in range(100):
        t0 = time.perf_counter()
        res = cascade.score(benchmark_feature_vector)
        lat = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(lat)
        assert res.scoring_source == ScoringSource.XGBOOST

    mean_lat = float(np.mean(latencies_ms))
    p50_lat = float(np.percentile(latencies_ms, 50))
    p95_lat = float(np.percentile(latencies_ms, 95))
    p99_lat = float(np.percentile(latencies_ms, 99))

    print(f"\n[Latency Benchmark - 100 calls] Mean: {mean_lat:.2f}ms | p50: {p50_lat:.2f}ms | p95: {p95_lat:.2f}ms | p99: {p99_lat:.2f}ms")

    # Assert SLA compliance (≤ 100ms)
    assert mean_lat <= 50.0, f"Mean latency {mean_lat}ms exceeds 50ms"
    assert p95_lat <= 100.0, f"p95 latency {p95_lat}ms exceeds 100ms timeout budget"
