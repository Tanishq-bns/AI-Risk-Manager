"""Unit and regression tests for Phase 3: Feature Engineering and Dataset Pipeline.

Covers:
1. Synthetic dataset generation and determinism with fixed seed.
2. Temporal split chronological guarantees (Train < Val < Test).
3. Ground-truth label presence and non-trivial class balance.
4. Schema separation: zero field overlap between FeatureVector and OutcomeLabel.
5. Point-in-time calculation respecting decision_timestamp.
6. Non-leakage regression: post-decision mutations cannot alter decision-time features.
7. Absence of protected attributes or raw PII.
8. Feature completeness evaluation and range validation.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import uuid
import pytest

from risk_manager.domain.schemas.enums import PaymentMethod
from risk_manager.features.completeness import evaluate_feature_completeness
from risk_manager.features.pipeline import (
    HistoricalOrderContext,
    HistoricalReturnContext,
    calculate_feature_vector,
)
from risk_manager.features.schema import FeatureVector, OutcomeLabel
from scripts.generate_synthetic_data import generate_synthetic_dataset


def test_feature_vector_outcome_label_separation():
    """Verify zero overlap between decision-time inputs and post-outcome labels (PLAN T-FE-01)."""
    feature_fields = set(FeatureVector.model_fields.keys())
    outcome_fields = set(OutcomeLabel.model_fields.keys())

    overlap = feature_fields & outcome_fields
    assert overlap == set(), f"Target leakage! Fields present in both schemas: {overlap}"


def test_no_protected_attributes_or_raw_pii():
    """Verify no protected demographic characteristics or raw PII in feature schema (SPEC §7)."""
    prohibited_substrings = [
        "gender", "sex", "religion", "caste", "race", "ethnicity", "marital",
        "name", "email", "phone", "mobile", "address", "pincode", "zipcode",
        "aadhaar", "pan", "ssn", "credit_card", "age"
    ]

    for field in FeatureVector.model_fields.keys():
        lower_field = field.lower()
        for bad_word in prohibited_substrings:
            assert bad_word not in lower_field, f"Prohibited attribute detected: '{field}' contains '{bad_word}'"


def test_feature_completeness_evaluator():
    """Verify completeness ratio, NaN/Inf handling, and logical range validations."""
    # 1. Valid complete feature vector
    valid_vec = FeatureVector(
        customer_id_hash="cust_comp_1",
        order_value=1299.0,
        product_category="APPAREL",
        payment_method=PaymentMethod.PREPAID,
        cod_flag=False,
        customer_order_count=5,
        customer_return_count=1,
        customer_return_rate=0.2,
        days_since_purchase=4,
        prior_return_value=850.0,
        prior_return_frequency=0.5,
        item_category_return_rate=0.28,
        return_reason="Size slightly small",
        delivery_distance_bucket="LOCAL",
        reverse_logistics_cost=75.0,
        estimated_item_recovery_value=834.3,
        historical_abuse_signal=0.0,
    )
    report = evaluate_feature_completeness(valid_vec)
    assert report.is_sufficient is True
    assert report.completeness_ratio == 1.0
    assert len(report.missing_fields) == 0
    assert len(report.range_violations) == 0

    # 2. Incomplete dictionary
    sparse_data = {
        "customer_id_hash": "cust_sparse",
        "order_value": 500.0,
        "product_category": "HOME",
    }
    sparse_report = evaluate_feature_completeness(sparse_data, min_ratio=0.85)
    assert sparse_report.is_sufficient is False
    assert sparse_report.completeness_ratio < 0.5
    assert "payment_method" in sparse_report.missing_fields

    # 3. Range and logical violation (return count > order count)
    invalid_data = valid_vec.model_dump()
    invalid_data["customer_order_count"] = 2
    invalid_data["customer_return_count"] = 5  # Impossible: returns > orders
    invalid_report = evaluate_feature_completeness(invalid_data)
    assert invalid_report.is_sufficient is False
    assert any("customer_return_count" in v for v in invalid_report.range_violations)

    # 4. NaN detection
    nan_data = valid_vec.model_dump()
    nan_data["customer_return_rate"] = float("nan")
    nan_report = evaluate_feature_completeness(nan_data)
    assert nan_report.is_sufficient is False
    assert any("NaN/Inf" in inv for inv in nan_report.invalid_fields)


def test_point_in_time_respects_decision_timestamp():
    """Verify historical features calculate only from events strictly before decision time (PLAN T-FE-02)."""
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=5)   # Return 1 requested
    t2 = t0 + timedelta(days=10)  # Order 2 placed
    t3 = t0 + timedelta(days=15)  # Return 2 requested

    order1 = HistoricalOrderContext(
        id=uuid.uuid4(),
        order_value=1000.0,
        payment_method="PREPAID",
        cod_flag=False,
        created_at=t0,
    )
    return1 = HistoricalReturnContext(
        id=uuid.uuid4(),
        order_id=order1.id,
        return_reason="Size defect",
        requested_at=t1,
        order_value=1000.0,
    )

    order2 = HistoricalOrderContext(
        id=uuid.uuid4(),
        order_value=2000.0,
        payment_method="COD",
        cod_flag=True,
        created_at=t2,
    )
    return2 = HistoricalReturnContext(
        id=uuid.uuid4(),
        order_id=order2.id,
        return_reason="Color mismatch",
        requested_at=t3,
        order_value=2000.0,
    )

    # Calculate features for Return 1 at T1
    # At T1, only order1 exists, and return1 is current (NOT historical)
    v1 = calculate_feature_vector(
        customer_id_hash="cust_test_pit",
        current_order=order1,
        current_return=return1,
        prior_orders=[order1, order2],  # order2 is in history list but occurred at T2 > T1
        prior_returns=[return1, return2],
        decision_timestamp=t1,
    )

    assert v1.customer_order_count == 1, "Order 2 occurred after T1 and must not be counted"
    assert v1.customer_return_count == 0, "Current return 1 must NOT be counted in prior return count"
    assert v1.customer_return_rate == 0.0
    assert v1.days_since_purchase == 5

    # Calculate features for Return 2 at T3
    # At T3, order1, return1, and order2 are strictly prior; return2 is current
    v2 = calculate_feature_vector(
        customer_id_hash="cust_test_pit",
        current_order=order2,
        current_return=return2,
        prior_orders=[order1, order2],
        prior_returns=[return1, return2],
        decision_timestamp=t3,
    )

    assert v2.customer_order_count == 2
    assert v2.customer_return_count == 1, "Return 1 should be in prior returns"
    assert v2.customer_return_rate == 0.5  # 1 return / 2 orders
    assert v2.prior_return_value == 1000.0
    assert v2.days_since_purchase == 5     # T3 (15) - T2 (10) = 5 days


def test_post_decision_outcome_leakage_regression():
    """Demonstrate that mutating a post-decision outcome does NOT alter decision-time features."""
    t_order = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    t_decision = t_order + timedelta(days=4)

    order = HistoricalOrderContext(
        id=uuid.uuid4(),
        order_value=3000.0,
        payment_method="COD",
        cod_flag=True,
        created_at=t_order,
    )
    ret = HistoricalReturnContext(
        id=uuid.uuid4(),
        order_id=order.id,
        return_reason="Wrong size",
        requested_at=t_decision,
        order_value=3000.0,
        status="PENDING",
        confirmed_abuse=False,
    )

    # Initial decision-time features
    features_before = calculate_feature_vector(
        customer_id_hash="cust_regression",
        current_order=order,
        current_return=ret,
        prior_orders=[order],
        prior_returns=[],
        decision_timestamp=t_decision,
    )

    # Simulate post-decision outcome occurring 3 days later
    # e.g., inspector confirms abuse and logs actual loss
    ret_after_outcome = HistoricalReturnContext(
        id=ret.id,
        order_id=order.id,
        return_reason=ret.return_reason,
        requested_at=t_decision,
        order_value=3000.0,
        status="COMPLETED",
        confirmed_abuse=True,  # Changed post-decision
    )
    outcome_label = OutcomeLabel(
        confirmed_abuse=True,
        actual_loss=2800.0,
        refund_completed_at=t_decision + timedelta(days=3),
    )

    # Recompute features at original decision timestamp
    features_after = calculate_feature_vector(
        customer_id_hash="cust_regression",
        current_order=order,
        current_return=ret_after_outcome,
        prior_orders=[order],
        prior_returns=[],
        decision_timestamp=t_decision,
    )

    # Assert 100% equivalence: post-decision label cannot alter decision-time inputs
    assert features_before.model_dump() == features_after.model_dump()
    assert outcome_label.confirmed_abuse is True


def test_synthetic_generator_deterministic():
    """Verify dataset generation is 100% reproducible for the same random seed."""
    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        path1 = Path(tmpdir1)
        path2 = Path(tmpdir2)

        s1 = generate_synthetic_dataset(num_customers=50, seed=123, output_dir=path1, simulation_days=90)
        s2 = generate_synthetic_dataset(num_customers=50, seed=123, output_dir=path2, simulation_days=90)

        assert s1["total_orders"] == s2["total_orders"]
        assert s1["total_returns"] == s2["total_returns"]
        assert s1["abuse_count"] == s2["abuse_count"]
        assert s1["train_count"] == s2["train_count"]

        # Byte-by-byte file content equality
        content1 = (path1 / "returns_full.csv").read_bytes()
        content2 = (path2 / "returns_full.csv").read_bytes()
        assert content1 == content2, "Generated CSV outputs diverged for identical seed!"


def test_synthetic_dataset_temporal_splits():
    """Verify temporal train/val/test ordering: Train strictly precedes Val strictly precedes Test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        summary = generate_synthetic_dataset(
            num_customers=100, seed=99, output_dir=output_dir, simulation_days=120
        )

        assert summary["total_returns"] > 0
        assert summary["abuse_count"] > 0
        assert summary["legitimate_count"] > 0

        # Verify temporal boundaries from summary
        t_windows = summary["temporal_windows"]
        train_cutoff = datetime.fromisoformat(t_windows["train_cutoff"])
        val_cutoff = datetime.fromisoformat(t_windows["val_cutoff"])
        test_start = datetime.fromisoformat(t_windows["test_start"])

        assert train_cutoff <= val_cutoff, f"Train cutoff {train_cutoff} after val cutoff {val_cutoff}"
        assert val_cutoff <= test_start, f"Val cutoff {val_cutoff} after test start {test_start}"


def test_deterministic_feature_column_ordering():
    """Verify FeatureVector.model_feature_names() returns an ordered, stable list."""
    names1 = FeatureVector.model_feature_names()
    names2 = FeatureVector.model_feature_names()
    assert names1 == names2
    assert len(names1) == 16
    assert "order_value" in names1
    assert "cod_flag" in names1
    assert "return_reason" in names1
    assert "customer_id_hash" not in names1
    assert "is_return_abuse" not in names1


def test_dataset_relationships_and_data_quality():
    """Verify customer/order/return relationships, pseudonymity, and quality constraints in generated dataset."""
    import csv

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        summary = generate_synthetic_dataset(
            num_customers=50, seed=42, output_dir=output_dir, simulation_days=90
        )
        assert summary["total_returns"] > 0

        csv_path = output_dir / "returns_full.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for row in rows:
            # 1. Pseudonymous customer IDs (hex hash, 16 chars)
            assert len(row["customer_id_hash"]) == 16
            assert all(c in "0123456789abcdef" for c in row["customer_id_hash"])

            # 2. Non-negative monetary values
            assert float(row["order_value"]) > 0.0
            assert float(row["reverse_logistics_cost"]) >= 0.0
            assert float(row["estimated_item_recovery_value"]) >= 0.0
            assert float(row["prior_return_value"]) >= 0.0

            # 3. Logical count consistency: returns <= orders
            order_count = int(row["customer_order_count"])
            return_count = int(row["customer_return_count"])
            assert order_count >= 1
            assert return_count <= order_count

            # 4. Valid rate ranges [0.0, 1.0]
            ret_rate = float(row["customer_return_rate"])
            cat_rate = float(row["item_category_return_rate"])
            abuse_sig = float(row["historical_abuse_signal"])
            assert 0.0 <= ret_rate <= 1.0
            assert 0.0 <= cat_rate <= 1.0
            assert 0.0 <= abuse_sig <= 1.0

            # 5. Timing
            assert int(row["days_since_purchase"]) >= 0

            # 6. Label values
            assert int(row["is_return_abuse"]) in {0, 1}

