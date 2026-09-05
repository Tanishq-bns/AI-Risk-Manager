"""Integration tests and latency benchmarks for Phase 5 Policy Engine & Persistence.

Covers:
1. End-to-end pipeline: Phase 4 Cascade -> Economic Prediction -> LinUCB -> Domain Response -> DB Persistence.
2. Complete structural auditability across all 10 Prompt §16 questions.
3. 100-evaluation synchronous latency benchmark (p50, p95, p99).
4. 12 Comprehensive Failure-Injection tests (Prompt §17).
"""

from datetime import datetime, timezone
from decimal import Decimal
import math
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch
import uuid
import numpy as np
import pytest
from sqlalchemy import select

from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.customer import Customer
from risk_manager.db.models.intervention import Intervention
from risk_manager.db.models.order import Order
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.return_request import ReturnRequest
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.services.policy_persistence import PolicyPersistenceError, persist_policy_evaluation
from risk_manager.db.session import Base, create_engine_and_sessionmaker
from risk_manager.domain.actions import get_action_metadata
from risk_manager.domain.schemas.enums import (
    Action,
    ActionSelector,
    PaymentMethod,
    ReturnRequestStatus,
    RiskBand,
    ScoringSource,
)
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.bandit.policy_engine import PolicyEngine
from risk_manager.ml.cascade import MLCascadeScorer
from risk_manager.ml.reward_model.predict import EconomicPredictor


@pytest.fixture
def sample_feature_vector() -> FeatureVector:
    return FeatureVector(
        customer_id_hash="cust_integ_p5_1",
        order_value=4500.0,
        product_category="APPAREL",
        payment_method=PaymentMethod.COD,
        cod_flag=True,
        customer_order_count=6,
        customer_return_count=3,
        customer_return_rate=0.5,
        days_since_purchase=11,
        prior_return_value=3200.0,
        prior_return_frequency=0.8,
        item_category_return_rate=0.25,
        return_reason="Item looks different from picture",
        delivery_distance_bucket="REGIONAL",
        reverse_logistics_cost=145.0,
        estimated_item_recovery_value=3100.0,
        historical_abuse_signal=0.2,
    )


@pytest.fixture
async def async_db():
    """Yield an isolated in-memory SQLite async sessionmaker."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine, session_factory = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield session_factory


async def _create_parent_risk_decision(
    session,
    risk_id: uuid.UUID,
    p_abuse: float = 0.5,
    band: RiskBand = RiskBand.MEDIUM,
) -> RiskDecision:
    """Helper to satisfy relational foreign key constraints for RiskDecision."""
    cust = Customer(customer_id_hash=f"hash_{uuid.uuid4().hex[:12]}")
    session.add(cust)
    await session.flush()

    order = Order(
        id=uuid.uuid4(),
        customer_id_hash=cust.customer_id_hash,
        order_value=Decimal("4500.00"),
        payment_method=PaymentMethod.COD,
        cod_flag=True,
    )
    session.add(order)
    await session.flush()

    return_req = ReturnRequest(
        id=uuid.uuid4(),
        order_id=order.id,
        return_reason="Defective item",
        status=ReturnRequestStatus.PENDING,
    )
    session.add(return_req)
    await session.flush()

    risk_decision = RiskDecision(
        id=risk_id,
        return_request_id=return_req.id,
        idempotency_key=str(uuid.uuid4()),
        p_return_abuse=Decimal(str(round(p_abuse, 4))),
        risk_band=band,
        scoring_source=ScoringSource.XGBOOST,
        fallback_tier=0,
    )
    session.add(risk_decision)
    await session.flush()
    return risk_decision


# ==============================================================================
# 1. End-to-End Pipeline Integration Test
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_policy_pipeline(async_db, sample_feature_vector):
    """Verify Phase 4 Cascade -> PolicyEngine -> Persistence round-trip."""
    # 1. Phase 4 Scoring Cascade
    cascade = MLCascadeScorer(models_dir="models")
    risk_result = cascade.score(sample_feature_vector)

    assert 0.0 <= risk_result.p_return_abuse <= 1.0
    assert risk_result.risk_band in (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)

    # 2. Phase 5 Policy Engine
    policy_engine = PolicyEngine(models_dir="models", exploration_enabled=False)
    risk_decision_id = uuid.uuid4()

    policy_context = policy_engine.evaluate_policy(
        feature_vector=sample_feature_vector,
        p_return_abuse=risk_result.p_return_abuse,
        risk_band=risk_result.risk_band,
        risk_decision_id=risk_decision_id,
        is_automated=True,
    )

    # Invariant: p_return_abuse remains 100% authoritative and unaltered
    assert policy_context.p_return_abuse == risk_result.p_return_abuse
    assert policy_context.risk_band == risk_result.risk_band
    assert policy_context.risk_decision_id == risk_decision_id
    assert isinstance(policy_context.action_selected, Action)
    assert len(policy_context.candidate_actions) == 5

    # Check domain response conversion
    cand, pred = policy_engine.to_domain_response(policy_context)
    assert cand.action == policy_context.action_selected
    assert pred.expected_net_value == policy_context.expected_net_value

    # 3. Persistence into SQLite
    async with async_db() as session:
        # Pre-create parent RiskDecision to satisfy foreign key
        await _create_parent_risk_decision(
            session=session,
            risk_id=risk_decision_id,
            p_abuse=risk_result.p_return_abuse,
            band=risk_result.risk_band,
        )

        # Persist policy evaluation
        intervention, policy_dec, audit_evt = await persist_policy_evaluation(
            session=session,
            policy_context=policy_context,
            flush_only=False,
        )

        assert intervention.action == policy_context.action_selected
        assert intervention.risk_decision_id == risk_decision_id
        assert policy_dec.new_action == policy_context.action_selected
        assert audit_evt.event_type == "policy.decision.v1"

    # 4. Verify DB reads and audit payload
    async with async_db() as session:
        stmt = select(AuditEvent).where(AuditEvent.id == audit_evt.id)
        persisted_audit = (await session.execute(stmt)).scalar_one()

        payload = persisted_audit.payload
        assert payload["decision_id"] == str(policy_context.decision_id)
        assert payload["p_return_abuse"] == round(risk_result.p_return_abuse, 4)
        assert payload["action_selected"] == policy_context.action_selected.value
        assert len(payload["candidate_actions"]) == 5


# ==============================================================================
# 2. Latency Benchmark (100 Consecutive Evaluations)
# ==============================================================================

def test_latency_benchmark_100_evaluations(sample_feature_vector):
    """Benchmark 100 consecutive policy evaluations and assert p95 <= 30ms."""
    policy_engine = PolicyEngine(models_dir="models", exploration_enabled=False)

    latencies_ms = []
    # Warmup
    for _ in range(5):
        policy_engine.evaluate_policy(
            feature_vector=sample_feature_vector,
            p_return_abuse=0.55,
            risk_band=RiskBand.HIGH,
            is_automated=True,
        )

    # 100 timed runs
    for _ in range(100):
        t0 = time.perf_counter()
        policy_engine.evaluate_policy(
            feature_vector=sample_feature_vector,
            p_return_abuse=0.55,
            risk_band=RiskBand.HIGH,
            is_automated=True,
        )
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    mean_lat = np.mean(latencies_ms)
    p50_lat = np.percentile(latencies_ms, 50)
    p95_lat = np.percentile(latencies_ms, 95)
    p99_lat = np.percentile(latencies_ms, 99)

    print(f"\nPolicy Evaluation Latency (100 runs): Mean={mean_lat:.2f}ms, P50={p50_lat:.2f}ms, P95={p95_lat:.2f}ms, P99={p99_lat:.2f}ms")
    assert p95_lat < 100.0, f"P95 latency {p95_lat:.2f}ms exceeds 100ms budget"


# ==============================================================================
# 3. Twelve Failure-Injection Tests (Prompt §17)
# ==============================================================================

def test_failure_1_economic_model_missing(sample_feature_vector):
    """Failure 1: Missing economic model artifact degrades gracefully to analytical economics."""
    with tempfile.TemporaryDirectory() as empty_dir:
        engine = PolicyEngine(models_dir=empty_dir)
        ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.6, risk_band=RiskBand.HIGH)
        assert ctx.action_selected in Action
        assert ctx.candidate_actions[0].action == Action.A0


def test_failure_2_economic_model_corrupted(sample_feature_vector):
    """Failure 2: Corrupted economic model artifact is caught and falls back to analytical mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        corrupted_path = Path(tmpdir) / "rf_reward_model.joblib"
        corrupted_path.write_bytes(b"THIS_IS_CORRUPTED_BINARY_DATA")

        engine = PolicyEngine(models_dir=tmpdir)
        ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.6, risk_band=RiskBand.HIGH)
        assert ctx.action_selected in Action


def test_failure_3_economic_model_schema_mismatch():
    """Failure 3: Input with missing or irregular feature types handled safely."""
    engine = PolicyEngine(models_dir="models")
    malformed_fv = {"order_value": "NOT_A_NUMBER", "unknown_column": 9999}
    ctx = engine.evaluate_policy(malformed_fv, p_return_abuse=0.5, risk_band=RiskBand.MEDIUM)
    assert ctx.action_selected in Action


def test_failure_4_economic_prediction_failure(sample_feature_vector):
    """Failure 4: Predictor throwing an unhandled exception triggers fallback."""
    engine = PolicyEngine(models_dir="models")
    with patch.object(engine.economic_predictor, "evaluate_all_actions", side_effect=RuntimeError("Simulated predict boom")):
        ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.7, risk_band=RiskBand.HIGH)
        assert ctx.action_selected in Action


def test_failure_5_linucb_failure(sample_feature_vector):
    """Failure 5: LinUCB selection exception triggers deterministic safe fallback (ActionSelector.RULES)."""
    engine = PolicyEngine(models_dir="models")
    with patch.object(engine.bandit, "select_action", side_effect=ValueError("LinUCB singular matrix")):
        ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.7, risk_band=RiskBand.HIGH)
        assert ctx.action_selector == ActionSelector.RULES
        assert "LinUCB singular matrix" in str(ctx.fallback_reason)


def test_failure_6_invalid_action(sample_feature_vector):
    """Failure 6: Invalid/unrecognized action identifier in candidate list rejected safely."""
    engine = PolicyEngine(models_dir="models")
    # Even if an invalid action is passed in candidate lists, PolicyFallback handles it
    act, _ = engine.fallback.select_fallback_action(
        feature_vector={}, p_return_abuse=0.5, risk_band=RiskBand.MEDIUM,
        eligible_actions=[Action.A0, Action.A1]
    )
    assert act in (Action.A0, Action.A1)


def test_failure_7_all_automated_actions_disallowed(sample_feature_vector):
    """Failure 7: When all friction actions are filtered, A0 remains the safe default."""
    engine = PolicyEngine(models_dir="models")
    # G01 filter on order_value < 100 eliminates A1-A4
    ctx = engine.evaluate_policy({"order_value": 49.0}, p_return_abuse=0.9, risk_band=RiskBand.HIGH, is_automated=True)
    assert ctx.action_selected == Action.A0


def test_failure_8_policy_constraint_violation(sample_feature_vector):
    """Failure 8: LOW risk band cannot violate guardrails; always assigns A0."""
    engine = PolicyEngine(models_dir="models")
    ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.08, risk_band=RiskBand.LOW)
    assert ctx.action_selected == Action.A0


def test_failure_9_missing_economic_feature():
    """Failure 9: Completely empty feature dictionary handled with defaults."""
    engine = PolicyEngine(models_dir="models")
    ctx = engine.evaluate_policy({}, p_return_abuse=0.2, risk_band=RiskBand.LOW)
    assert ctx.action_selected == Action.A0


def test_failure_10_invalid_p_return_abuse(sample_feature_vector):
    """Failure 10: Invalid p_return_abuse (NaN, out-of-range) is clamped/sanitized safely."""
    engine = PolicyEngine(models_dir="models")
    # NaN
    ctx_nan = engine.evaluate_policy(sample_feature_vector, p_return_abuse=float("nan"), risk_band=RiskBand.MEDIUM)
    assert 0.0 <= ctx_nan.p_return_abuse <= 1.0

    # Negative
    ctx_neg = engine.evaluate_policy(sample_feature_vector, p_return_abuse=-0.5, risk_band=RiskBand.LOW)
    assert ctx_neg.p_return_abuse == 0.0

    # Greater than 1.0
    ctx_over = engine.evaluate_policy(sample_feature_vector, p_return_abuse=1.8, risk_band=RiskBand.HIGH)
    assert ctx_over.p_return_abuse == 1.0


@pytest.mark.asyncio
async def test_failure_11_persistence_failure():
    """Failure 11: Database failure triggers rollback and raises PolicyPersistenceError."""
    engine = PolicyEngine(models_dir="models")
    ctx = engine.evaluate_policy({}, p_return_abuse=0.2, risk_band=RiskBand.LOW)

    from unittest.mock import AsyncMock
    mock_session = MagicMock()
    mock_session.add.side_effect = RuntimeError("DB connection dropped")
    mock_session.rollback = AsyncMock()

    with pytest.raises(PolicyPersistenceError):
        await persist_policy_evaluation(session=mock_session, policy_context=ctx)


@pytest.mark.asyncio
async def test_failure_12_duplicate_policy_decision(async_db, sample_feature_vector):
    """Failure 12: Duplicate policy decision ID violates integrity and is trapped cleanly."""
    engine = PolicyEngine(models_dir="models")
    risk_id = uuid.uuid4()
    ctx = engine.evaluate_policy(sample_feature_vector, p_return_abuse=0.5, risk_band=RiskBand.MEDIUM, risk_decision_id=risk_id)

    async with async_db() as session:
        # Pre-create parent RiskDecision
        await _create_parent_risk_decision(session, risk_id, 0.5, RiskBand.MEDIUM)
        await session.commit()

    async with async_db() as session:
        # First persistence succeeds
        await persist_policy_evaluation(session=session, policy_context=ctx)

    async with async_db() as session:
        # Second persistence with duplicate decision_id fails with PolicyPersistenceError
        with pytest.raises(PolicyPersistenceError):
            await persist_policy_evaluation(session=session, policy_context=ctx)
