"""Unit tests for Phase 2 Pydantic domain schemas and enums.

Verifies:
1. All major Pydantic DTOs can be instantiated with valid data.
2. Invalid DTO data is rejected via Pydantic ValidationError.
3. Action enum consistency across DTOs and models.
4. Risk band and fallback tier validation.
"""

from datetime import datetime, timezone
import uuid
import pytest
from pydantic import ValidationError

from risk_manager.domain.schemas import (
    Action,
    ActionDecision,
    ActionSelector,
    AgentName,
    AgentRunStatus,
    AgentVerificationResult,
    CheckoutEvent,
    EconomicPrediction,
    EventEnvelope,
    EvidenceQuality,
    FallbackMetadata,
    FallbackTier,
    InvestigationResult,
    InterventionCandidate,
    ManualOverrideRequest,
    ManualOverrideResponse,
    ModelApprovalStatus,
    ModelMetadata,
    PaymentMethod,
    PersistenceStatus,
    PolicyDecision,
    ReturnRequestEvent,
    ReturnRequestStatus,
    RiskBand,
    RiskEvidence,
    RiskScoreRequest,
    RiskScoreResponse,
    ScoringSource,
    VerificationResult,
    VerifierRecommendation,
)


def test_action_enum_consistency():
    """Verify Action enum values, labels, and string equality."""
    assert Action.A0 == "A0"
    assert Action.A1 == "A1"
    assert Action.A2 == "A2"
    assert Action.A3 == "A3"
    assert Action.A4 == "A4"

    assert Action.A0.label == "ZERO_FRICTION_APPROVAL"
    assert Action.A1.label == "DYNAMIC_RETURN_FEE"
    assert Action.A2.label == "OTP_DOORSTEP_INSPECTION"
    assert Action.A3.label == "STORE_CREDIT"
    assert Action.A4.label == "MANUAL_REVIEW"

    # Verify membership
    assert "A0" in Action.__members__
    assert len(Action) == 5


def test_risk_band_enum():
    """Verify RiskBand enum values."""
    assert RiskBand.LOW == "LOW"
    assert RiskBand.MEDIUM == "MEDIUM"
    assert RiskBand.HIGH == "HIGH"
    assert RiskBand.CRITICAL == "CRITICAL"


def test_checkout_event_valid_and_invalid():
    """Verify CheckoutEvent validation and field constraints."""
    now = datetime.now(timezone.utc)
    order_id = uuid.uuid4()

    valid_event = CheckoutEvent(
        order_id=order_id,
        customer_id_hash="sha256_hash_value_abc",
        order_value=1499.50,
        payment_method=PaymentMethod.COD,
        cod_flag=True,
        occurred_at=now,
    )
    assert valid_event.order_value == 1499.50
    assert valid_event.payment_method == PaymentMethod.COD

    # Rejection of zero or negative order_value
    with pytest.raises(ValidationError):
        CheckoutEvent(
            order_id=order_id,
            customer_id_hash="hash",
            order_value=0.0,  # Field(gt=0)
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
            occurred_at=now,
        )


def test_return_request_event():
    """Verify ReturnRequestEvent schema."""
    req_id = uuid.uuid4()
    order_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    event = ReturnRequestEvent(
        return_request_id=req_id,
        order_id=order_id,
        return_reason="Item size too small",
        requested_at=now,
    )
    assert event.return_reason == "Item size too small"
    data = event.model_dump()
    assert data["return_request_id"] == req_id


def test_event_envelope_generic():
    """Verify generic EventEnvelope round-trip serialization."""
    event_id = uuid.uuid4()
    order_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    checkout = CheckoutEvent(
        order_id=order_id,
        customer_id_hash="cust123",
        order_value=999.0,
        payment_method=PaymentMethod.PREPAID,
        cod_flag=False,
        occurred_at=now,
    )

    envelope = EventEnvelope[CheckoutEvent](
        event_id=event_id,
        event_type="CHECKOUT_COMPLETED",
        event_version="v1",
        occurred_at=now,
        producer="checkout-service",
        correlation_id="corr-123",
        entity_id=str(order_id),
        payload=checkout,
    )

    json_str = envelope.model_dump_json()
    restored = EventEnvelope[CheckoutEvent].model_validate_json(json_str)
    assert restored.event_id == event_id
    assert restored.payload.order_value == 999.0


def test_risk_score_request():
    """Verify RiskScoreRequest validation and inline context."""
    req_id = uuid.uuid4()
    order_id = uuid.uuid4()

    req = RiskScoreRequest(
        return_request_id=req_id,
        order_id=order_id,
        customer_id_hash="cust_abc",
        idempotency_key="idemp_key_001",
        order_value=2500.0,
        payment_method=PaymentMethod.COD,
        cod_flag=True,
        return_reason="Defective zipper",
    )
    assert req.idempotency_key == "idemp_key_001"
    assert req.order_value == 2500.0

    # Missing idempotency key rejected
    with pytest.raises(ValidationError):
        RiskScoreRequest(
            return_request_id=req_id,
            order_id=order_id,
            customer_id_hash="cust_abc",
            idempotency_key="",
        )


def test_risk_score_response_full_instantiation():
    """Verify full RiskScoreResponse structure matching TRD.md §E."""
    decision_id = uuid.uuid4()

    resp = RiskScoreResponse(
        decision_id=decision_id,
        p_return_abuse=0.7250,
        risk_band=RiskBand.HIGH,
        model_metadata=ModelMetadata(
            model_version="xgb_v1.0.0",
            model_type=ScoringSource.XGBOOST,
            trained_at=datetime.now(timezone.utc),
        ),
        fallback_metadata=FallbackMetadata(
            fallback_tier=FallbackTier.TIER_0,
            fallback_reason=None,
        ),
        economic_prediction=EconomicPrediction(
            expected_loss_no_action=450.0,
            expected_loss_with_action=120.0,
            expected_net_value=330.0,
        ),
        intervention=InterventionCandidate(
            action=Action.A2,
            selected_by=ActionSelector.LINUCB,
            rationale="High abuse risk with recoverable logistics cost",
        ),
        evidence=RiskEvidence(
            top_signals=["high prior_return_frequency", "COD return pattern"],
            feature_completeness=0.95,
        ),
        latency_ms=42.5,
        persistence_status=PersistenceStatus.PERSISTED,
    )

    assert resp.p_return_abuse == 0.7250
    assert resp.risk_band == RiskBand.HIGH
    assert resp.intervention.action == Action.A2
    assert resp.persistence_status == PersistenceStatus.PERSISTED

    # Probability bounds enforcement (must be <= 1.0)
    with pytest.raises(ValidationError):
        bad_data = resp.model_dump()
        bad_data["p_return_abuse"] = 1.5
        RiskScoreResponse.model_validate(bad_data)


def test_agent_structured_contracts():
    """Verify LangGraph agent structured schemas."""
    case_id = uuid.uuid4()

    inv = InvestigationResult(
        case_id=case_id,
        evidence=["Customer has 3 returns in last 14 days", "COD order history"],
        evidence_quality=EvidenceQuality.HIGH,
        anomalies=["Return initiated within 2 hours of delivery"],
        investigator_confidence=0.88,
    )
    assert inv.evidence_quality == EvidenceQuality.HIGH

    ver = VerificationResult(
        case_id=case_id,
        verified=True,
        contradictions=[],
        missing_evidence=[],
        verifier_confidence=0.92,
        recommendation=VerifierRecommendation.CONFIRM,
    )
    assert ver.verified is True

    act = ActionDecision(
        action=Action.A1,
        rationale="Dynamic fee offsets return logistics without rejecting legitimate customer",
        expected_net_value=150.0,
        policy_constraints_satisfied=True,
        requires_manual_review=False,
    )
    assert act.action == Action.A1


def test_manual_override_contracts():
    """Verify ManualOverrideRequest and ManualOverrideResponse schemas."""
    decision_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Valid override request
    req = ManualOverrideRequest(
        operator_id="operator_sarah",
        reason="VIP customer complaint with verified legitimate defect",
        new_action=Action.A0,
    )
    assert req.new_action == Action.A0

    # Missing reason rejected
    with pytest.raises(ValidationError):
        ManualOverrideRequest(
            operator_id="operator_sarah",
            reason="",
            new_action=Action.A0,
        )

    # Response contract
    res = ManualOverrideResponse(
        decision_id=decision_id,
        previous_action=Action.A2,
        new_action=Action.A0,
        overridden_at=now,
        audit_event_id=audit_id,
    )
    assert res.previous_action == Action.A2
    assert res.new_action == Action.A0
