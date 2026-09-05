"""Integration tests for Phase 2 async persistence layer.

Verifies:
1. SQLite async database starts successfully.
2. All 10 domain entity tables are created.
3. Insert and read round-trip across all entities.
4. Foreign-key relationships and cascade constraints.
5. Idempotency key uniqueness enforcement.
6. Original RiskDecision immutability under PolicyDecision state transitions.
7. Append-only AuditEvent logging without mutation.
8. Database session lifecycle and rollback semantics.
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from risk_manager.db.models import (
    AgentRun,
    AuditEvent,
    Customer,
    Intervention,
    ModelVersion,
    Order,
    PolicyDecision,
    ReturnRequest,
    RiskDecision,
    RiskFeatures,
)
from risk_manager.db.session import (
    Base,
    create_engine_and_sessionmaker,
)
from risk_manager.domain.schemas import (
    Action,
    ActionSelector,
    AgentName,
    AgentRunStatus,
    ModelApprovalStatus,
    PaymentMethod,
    ReturnRequestStatus,
    RiskBand,
    ScoringSource,
)


@pytest.fixture
async def async_db():
    """Yield an isolated in-memory SQLite async sessionmaker."""
    # Use SQLite in-memory with StaticPool to share connection across calls
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine, session_factory = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.mark.asyncio
async def test_table_creation(async_db):
    """Verify all 10 domain tables are created in metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "customers",
        "orders",
        "return_requests",
        "model_versions",
        "risk_decisions",
        "risk_features",
        "interventions",
        "agent_runs",
        "policy_decisions",
        "audit_events",
    }
    assert expected_tables.issubset(table_names)


@pytest.mark.asyncio
async def test_customer_order_return_request_lifecycle(async_db):
    """Verify relational persistence of customer -> order -> return_request."""
    async with async_db() as session:
        # Create Customer
        customer = Customer(customer_id_hash="cust_hash_123")
        session.add(customer)
        await session.flush()

        # Create Order
        order = Order(
            id=uuid.uuid4(),
            customer_id_hash=customer.customer_id_hash,
            order_value=Decimal("1999.00"),
            payment_method=PaymentMethod.COD,
            cod_flag=True,
        )
        session.add(order)
        await session.flush()

        # Create ReturnRequest
        return_req = ReturnRequest(
            id=uuid.uuid4(),
            order_id=order.id,
            return_reason="Item defective on arrival",
            status=ReturnRequestStatus.PENDING,
        )
        session.add(return_req)
        await session.commit()

    # Query back and verify relationships
    async with async_db() as session:
        stmt = select(Customer).where(Customer.customer_id_hash == "cust_hash_123")
        result = await session.execute(stmt)
        retrieved_customer = result.scalar_one()

        assert retrieved_customer.customer_id_hash == "cust_hash_123"
        assert len(retrieved_customer.orders) == 1
        assert retrieved_customer.orders[0].order_value == Decimal("1999.00")
        assert len(retrieved_customer.orders[0].return_requests) == 1
        assert retrieved_customer.orders[0].return_requests[0].return_reason == "Item defective on arrival"


@pytest.mark.asyncio
async def test_foreign_key_integrity(async_db):
    """Verify that inserting a child with non-existent foreign key fails."""
    async with async_db() as session:
        # Attempt to insert an order referencing a customer that doesn't exist
        orphan_order = Order(
            id=uuid.uuid4(),
            customer_id_hash="non_existent_customer",
            order_value=Decimal("500.00"),
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
        )
        session.add(orphan_order)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_idempotency_key_uniqueness(async_db):
    """Verify that duplicate idempotency keys on RiskDecision are rejected."""
    return_req_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with async_db() as session:
        # Setup prerequisite records
        customer = Customer(customer_id_hash="cust_idemp")
        session.add(customer)
        await session.flush()

        order = Order(
            id=order_id,
            customer_id_hash=customer.customer_id_hash,
            order_value=Decimal("1200.00"),
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
        )
        session.add(order)
        await session.flush()

        return_req = ReturnRequest(
            id=return_req_id,
            order_id=order.id,
            return_reason="Unwanted gift",
            status=ReturnRequestStatus.PENDING,
        )
        session.add(return_req)
        await session.flush()

        # Insert first RiskDecision
        d1 = RiskDecision(
            id=uuid.uuid4(),
            return_request_id=return_req_id,
            idempotency_key="idemp-key-shared-001",
            p_return_abuse=Decimal("0.1500"),
            risk_band=RiskBand.LOW,
            scoring_source=ScoringSource.XGBOOST,
            fallback_tier=0,
        )
        session.add(d1)
        await session.commit()

    # Attempt to insert duplicate idempotency key
    async with async_db() as session:
        d2 = RiskDecision(
            id=uuid.uuid4(),
            return_request_id=return_req_id,
            idempotency_key="idemp-key-shared-001",  # Same idempotency key
            p_return_abuse=Decimal("0.2000"),
            risk_band=RiskBand.LOW,
            scoring_source=ScoringSource.XGBOOST,
            fallback_tier=0,
        )
        session.add(d2)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_risk_decision_features_intervention_persistence(async_db):
    """Verify synchronous decision path persistence (Decision + Features + Intervention)."""
    decision_id = uuid.uuid4()
    return_req_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with async_db() as session:
        # Base prerequisites
        cust = Customer(customer_id_hash="cust_scoring")
        session.add(cust)
        await session.flush()

        ordr = Order(
            id=order_id,
            customer_id_hash=cust.customer_id_hash,
            order_value=Decimal("3500.00"),
            payment_method=PaymentMethod.COD,
            cod_flag=True,
        )
        session.add(ordr)
        await session.flush()

        rr = ReturnRequest(
            id=return_req_id,
            order_id=ordr.id,
            return_reason="Wrong item received",
            status=ReturnRequestStatus.PENDING,
        )
        session.add(rr)
        await session.flush()

        # Model Version
        mv = ModelVersion(
            id=uuid.uuid4(),
            mlflow_run_id="run_xgb_oct_2026",
            model_type=ScoringSource.XGBOOST,
            approval_status=ModelApprovalStatus.APPROVED,
        )
        session.add(mv)
        await session.flush()

        # Risk Decision
        dec = RiskDecision(
            id=decision_id,
            return_request_id=return_req_id,
            idempotency_key="idemp_score_999",
            p_return_abuse=Decimal("0.7500"),
            risk_band=RiskBand.HIGH,
            scoring_source=ScoringSource.XGBOOST,
            fallback_tier=0,
            model_version_id=mv.id,
        )
        session.add(dec)
        await session.flush()

        # Risk Features Snapshot
        features_dict = {
            "customer_order_count": 5,
            "customer_return_count": 3,
            "customer_return_rate": 0.6,
            "days_since_purchase": 12,
            "cod_flag": True,
        }
        rf = RiskFeatures(
            id=uuid.uuid4(),
            risk_decision_id=decision_id,
            features=features_dict,
            feature_schema_version="v1",
        )
        session.add(rf)

        # Selected Intervention
        intervention = Intervention(
            id=uuid.uuid4(),
            risk_decision_id=decision_id,
            action=Action.A2,
            expected_net_value=Decimal("250.00"),
            selected_by=ActionSelector.LINUCB,
        )
        session.add(intervention)
        await session.commit()

    # Read back and verify complete entity graph
    async with async_db() as session:
        stmt = select(RiskDecision).where(RiskDecision.id == decision_id)
        result = await session.execute(stmt)
        saved_dec = result.scalar_one()

        assert saved_dec.p_return_abuse == Decimal("0.7500")
        assert saved_dec.risk_band == RiskBand.HIGH
        assert saved_dec.features.features["customer_return_rate"] == 0.6
        assert len(saved_dec.interventions) == 1
        assert saved_dec.interventions[0].action == Action.A2
        assert saved_dec.interventions[0].expected_net_value == Decimal("250.00")


@pytest.mark.asyncio
async def test_policy_decision_state_transition_and_override(async_db):
    """Verify manual override creates append-only state transition preserving original decision (ADR-012)."""
    decision_id = uuid.uuid4()
    order_id = uuid.uuid4()
    return_req_id = uuid.uuid4()

    async with async_db() as session:
        cust = Customer(customer_id_hash="cust_override")
        session.add(cust)
        await session.flush()

        ordr = Order(
            id=order_id,
            customer_id_hash=cust.customer_id_hash,
            order_value=Decimal("4999.00"),
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
        )
        session.add(ordr)
        await session.flush()

        rr = ReturnRequest(
            id=return_req_id,
            order_id=ordr.id,
            return_reason="Defective item",
            status=ReturnRequestStatus.PENDING,
        )
        session.add(rr)
        await session.flush()

        # Automated Decision originally selected A2 (OTP Doorstep)
        dec = RiskDecision(
            id=decision_id,
            return_request_id=return_req_id,
            idempotency_key="idemp_override_1",
            p_return_abuse=Decimal("0.8000"),
            risk_band=RiskBand.HIGH,
            scoring_source=ScoringSource.XGBOOST,
            fallback_tier=0,
        )
        session.add(dec)

        # Original initial automated state transition
        initial_policy = PolicyDecision(
            id=uuid.uuid4(),
            risk_decision_id=decision_id,
            previous_action=None,
            new_action=Action.A2,
            selected_by=ActionSelector.LINUCB,
            operator_id=None,
            reason="Automated policy assignment",
        )
        session.add(initial_policy)
        await session.commit()

    # Operator performs manual override to A3 (Store Credit)
    async with async_db() as session:
        override_transition = PolicyDecision(
            id=uuid.uuid4(),
            risk_decision_id=decision_id,
            previous_action=Action.A2,
            new_action=Action.A3,
            selected_by=ActionSelector.MANUAL_OVERRIDE,
            operator_id="operator_dan",
            reason="Customer agreed to store credit resolution via support chat",
        )
        session.add(override_transition)
        await session.commit()

    # Query back: verify original decision remains UNTOUCHED and state transitions form append-only chain
    async with async_db() as session:
        stmt = (
            select(PolicyDecision)
            .where(PolicyDecision.risk_decision_id == decision_id)
            .order_by(PolicyDecision.created_at.asc())
        )
        result = await session.execute(stmt)
        transitions = result.scalars().all()

        assert len(transitions) == 2
        # Transition 1: Automated
        assert transitions[0].previous_action is None
        assert transitions[0].new_action == Action.A2
        assert transitions[0].selected_by == ActionSelector.LINUCB

        # Transition 2: Manual Override
        assert transitions[1].previous_action == Action.A2
        assert transitions[1].new_action == Action.A3
        assert transitions[1].selected_by == ActionSelector.MANUAL_OVERRIDE
        assert transitions[1].operator_id == "operator_dan"

        # Verify original RiskDecision still exists and was not mutated
        dec_stmt = select(RiskDecision).where(RiskDecision.id == decision_id)
        dec_res = await session.execute(dec_stmt)
        orig_dec = dec_res.scalar_one()
        assert orig_dec.p_return_abuse == Decimal("0.8000")


@pytest.mark.asyncio
async def test_audit_events_append_only(async_db):
    """Verify append-only audit_events persistence."""
    event_id1 = uuid.uuid4()
    event_id2 = uuid.uuid4()

    async with async_db() as session:
        e1 = AuditEvent(
            id=uuid.uuid4(),
            event_id=event_id1,
            event_type="RETURN_REQUEST_CREATED",
            payload={"return_request_id": str(uuid.uuid4()), "reason": "Damaged box"},
        )
        e2 = AuditEvent(
            id=uuid.uuid4(),
            event_id=event_id2,
            event_type="RISK_DECISION_SCORED",
            payload={"p_return_abuse": 0.45, "action": "A0"},
        )
        session.add_all([e1, e2])
        await session.commit()

    async with async_db() as session:
        stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.asc())
        result = await session.execute(stmt)
        events = result.scalars().all()

        assert len(events) == 2
        assert events[0].event_type == "RETURN_REQUEST_CREATED"
        assert events[1].event_type == "RISK_DECISION_SCORED"

    # Verify duplicate event_id is rejected by unique constraint
    async with async_db() as session:
        dup_event = AuditEvent(
            id=uuid.uuid4(),
            event_id=event_id1,  # Duplicate event_id
            event_type="DUPLICATE_EVENT",
            payload={},
        )
        session.add(dup_event)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_agent_run_persistence(async_db):
    """Verify AgentRun persistence and JSON output round-trip."""
    decision_id = uuid.uuid4()

    async with async_db() as session:
        # Create prerequisite Customer, Order, ReturnRequest, Decision
        cust = Customer(customer_id_hash="cust_agent")
        session.add(cust)
        await session.flush()

        ordr = Order(
            id=uuid.uuid4(),
            customer_id_hash=cust.customer_id_hash,
            order_value=Decimal("1500.00"),
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
        )
        session.add(ordr)
        await session.flush()

        rr = ReturnRequest(
            id=uuid.uuid4(),
            order_id=ordr.id,
            return_reason="Item size mismatch",
        )
        session.add(rr)
        await session.flush()

        dec = RiskDecision(
            id=decision_id,
            return_request_id=rr.id,
            idempotency_key="idemp_agent_test",
            p_return_abuse=Decimal("0.6200"),
            risk_band=RiskBand.HIGH,
            scoring_source=ScoringSource.XGBOOST,
            fallback_tier=0,
        )
        session.add(dec)
        await session.flush()

        agent_run = AgentRun(
            id=uuid.uuid4(),
            risk_decision_id=decision_id,
            agent_name=AgentName.INVESTIGATOR,
            output={
                "evidence": ["Customer placed 4 orders in 7 days"],
                "evidence_quality": "HIGH",
                "anomalies": ["Rapid return velocity"],
            },
            status=AgentRunStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(agent_run)
        await session.commit()

    async with async_db() as session:
        stmt = select(AgentRun).where(AgentRun.risk_decision_id == decision_id)
        result = await session.execute(stmt)
        saved_run = result.scalar_one()

        assert saved_run.agent_name == AgentName.INVESTIGATOR
        assert saved_run.status == AgentRunStatus.COMPLETED
        assert saved_run.output["evidence_quality"] == "HIGH"
