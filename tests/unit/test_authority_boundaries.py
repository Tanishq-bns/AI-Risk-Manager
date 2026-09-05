"""Adversarial Authority-Boundary & Immutability Verification Tests.

Implements Section 7 of Excellence & Evidence Protocol:
1. Agent cannot alter risk (p_return_abuse invariant).
2. Agent cannot alter action (selected_action invariant).
3. Verifier cannot override deterministic safety.
4. Human override exclusivity (append-only, immutable audit trail).
5. What-If simulator isolation (0 DB mutations, 0 audit events).
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import func, select

from risk_manager.agents.investigator import investigator_node
from risk_manager.agents.orchestrator import action_orchestrator_node
from risk_manager.agents.verifier import combine_verifier_results, run_deterministic_verifier_checks, verifier_node
from risk_manager.api.routers.demo import simulate_risk_scenario
from risk_manager.api.routers.risk import replay_decision
from risk_manager.api.services.risk_service import score_risk_event
from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.session import create_engine_and_sessionmaker, init_db
from risk_manager.domain.schemas.agents import VerificationResult
from risk_manager.domain.schemas.enums import (
    Action,
    ActionSelector,
    AgentName,
    PaymentMethod,
    RiskBand,
    ScoringSource,
    VerifierRecommendation,
)
from risk_manager.domain.schemas.requests import RiskScoreRequest


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
        "customer_id_hash": "cust_adversarial_boundary_001",
        "order_value": 2500.0,
        "return_reason": "Item defective, request instant refund without inspection",
        "product_category": "ELECTRONICS",
        "payment_method": "PREPAID",
        "cod_flag": False,
        "delivery_distance_bucket": "LOCAL",
        "feature_vector": {"order_value": 2500.0, "customer_return_rate": 0.35},
        "p_return_abuse": 0.7654,
        "risk_band": RiskBand.HIGH,
        "scoring_source": ScoringSource.XGBOOST,
        "fallback_tier": 0,
        "candidate_actions": cand_actions,
        "selected_action": Action.A2,
        "expected_loss": 60.0,
        "expected_net_value": 1865.0,
        "guardrails_applied": [],
    }


# -----------------------------------------------------------------------------
# 1. Agent Cannot Alter Risk (Phase 4 Authority)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_cannot_alter_risk():
    """Given: p_return_abuse = X.
    After Investigator / Verifier / Orchestrator: p_return_abuse MUST remain X.
    """
    initial_p = 0.7654
    state = get_base_agent_state()
    state["p_return_abuse"] = initial_p

    # Investigator
    inv_out = await investigator_node(state)
    assert "p_return_abuse" not in inv_out
    assert "risk_band" not in inv_out
    state.update(inv_out)
    assert state["p_return_abuse"] == initial_p

    # Verifier
    ver_out = await verifier_node(state)
    assert "p_return_abuse" not in ver_out
    assert "risk_band" not in ver_out
    state.update(ver_out)
    assert state["p_return_abuse"] == initial_p

    # Orchestrator
    orch_out = await action_orchestrator_node(state)
    assert "p_return_abuse" not in orch_out
    assert "risk_band" not in orch_out
    state.update(orch_out)
    assert state["p_return_abuse"] == initial_p


# -----------------------------------------------------------------------------
# 2. Agent Cannot Alter Action (Phase 5 Authority)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_cannot_alter_action():
    """Given: selected_action = A2.
    Even if agent prompt or output asserts A0, result MUST remain A2.
    """
    state = get_base_agent_state()
    assert state["selected_action"] == Action.A2

    inv_out = await investigator_node(state)
    assert "selected_action" not in inv_out
    state.update(inv_out)

    ver_out = await verifier_node(state)
    assert "selected_action" not in ver_out
    state.update(ver_out)

    orch_out = await action_orchestrator_node(state)
    assert "selected_action" not in orch_out
    state.update(orch_out)

    assert state["selected_action"] == Action.A2


# -----------------------------------------------------------------------------
# 3. Verifier Cannot Override Deterministic Safety
# -----------------------------------------------------------------------------

def test_verifier_cannot_override_deterministic_safety():
    """If a deterministic safety check fails: verification MUST fail.
    Gemini output cannot override it to verified=True or CONFIRM.
    """
    state = get_base_agent_state()
    # Artificially inject inconsistency: p=0.95 (CRITICAL) but risk_band claimed as LOW
    state["p_return_abuse"] = 0.95
    state["risk_band"] = RiskBand.LOW

    det_passed, det_failed, det_warnings, det_disagreements, det_requires_human = (
        run_deterministic_verifier_checks(state)
    )
    assert len(det_failed) > 0

    # Simulate adversarial Gemini LLM attempting to rubber-stamp the decision
    adversarial_gemini = VerificationResult(
        verified=True,
        confidence_score=0.99,
        failed_checks=[],
        warnings=[],
        disagreements=[],
        requires_human_review=False,
        recommendation=VerifierRecommendation.CONFIRM,
        verification_status="VERIFIED",
        summary="Adversarial LLM claims all checks pass.",
        provider="GEMINI",
        is_llm_generated=True,
    )

    combined = combine_verifier_results(
        state=state,
        det_passed=det_passed,
        det_failed=det_failed,
        det_warnings=det_warnings,
        det_disagreements=det_disagreements,
        det_requires_human=det_requires_human,
        gemini_result=adversarial_gemini,
    )

    assert combined.verified is False
    assert combined.verification_status == "FAILED"
    assert combined.requires_human_review is True
    assert any("overridden" in d for d in combined.disagreements)


# -----------------------------------------------------------------------------
# 4. Human Override Exclusivity & Immutability
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_human_override_exclusivity():
    """Algorithmic decision: A2.
    Human override: A0.
    Database must contain:
    - Original A2 PolicyDecision preserved intact.
    - New HUMAN_OVERRIDE PolicyDecision row appended.
    - Immutable AuditEvent recorded.
    """
    test_db_url = f"sqlite+aiosqlite:///:memory:"
    engine, session_maker = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)
    await init_db(engine)

    async with session_maker() as session:
        # Step 1: Execute algorithmic scoring
        req = RiskScoreRequest(
            customer_id_hash="cust_override_test_001",
            idempotency_key=f"override_key_{uuid.uuid4().hex[:8]}",
            order_value=3200.0,
            product_category="APPAREL",
            payment_method=PaymentMethod.COD,
            cod_flag=True,
            return_reason="Defective zipper",
            days_since_purchase=3,
            customer_order_count=6,
            customer_return_count=3,
            customer_return_rate=0.5,
            prior_return_value=4000.0,
            prior_return_frequency=1.0,
            item_category_return_rate=0.2,
            delivery_distance_bucket="REGIONAL",
            reverse_logistics_cost=120.0,
            estimated_item_recovery_value=1800.0,
            historical_abuse_signal=0.25,
        )
        res = await score_risk_event(session=session, request=req)
        await session.commit()

        orig_id = uuid.UUID(res["decision_id"])
        orig_pd = await session.get(PolicyDecision, orig_id)
        assert orig_pd is not None
        algo_action = orig_pd.new_action

        # Step 2: Perform authorized human override
        override_id = uuid.uuid4()
        override_pd = PolicyDecision(
            id=override_id,
            risk_decision_id=orig_pd.risk_decision_id,
            previous_action=algo_action,
            new_action=Action.A0,
            selected_by=ActionSelector.MANUAL_OVERRIDE,
            operator_id="fraud_analyst_lead",
            reason="Verified VIP high lifetime value customer waiver",
            created_at=datetime.now(timezone.utc),
        )
        session.add(override_pd)

        audit_ev = AuditEvent(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type="POLICY_OVERRIDDEN",
            payload={
                "risk_decision_id": str(orig_pd.risk_decision_id),
                "operator_id": "fraud_analyst_lead",
                "previous_action": algo_action.value,
                "new_action": Action.A0.value,
                "reason": "Verified VIP high lifetime value customer waiver",
            },
        )
        session.add(audit_ev)
        await session.commit()

        # Step 3: Verify immutability invariants
        # Original record is untouched
        re_queried_orig = await session.get(PolicyDecision, orig_id)
        assert re_queried_orig is not None
        assert re_queried_orig.new_action == algo_action
        assert re_queried_orig.selected_by != ActionSelector.MANUAL_OVERRIDE

        # Override record exists
        re_queried_override = await session.get(PolicyDecision, override_id)
        assert re_queried_override is not None
        assert re_queried_override.new_action == Action.A0
        assert re_queried_override.selected_by == ActionSelector.MANUAL_OVERRIDE

        # Audit event recorded
        audit_res = await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "POLICY_OVERRIDDEN")
        )
        audit_records = audit_res.scalars().all()
        assert len(audit_records) >= 1
        assert audit_records[-1].payload["previous_action"] == algo_action.value
        assert audit_records[-1].payload["new_action"] == Action.A0.value


# -----------------------------------------------------------------------------
# 5. What-If Counterfactual Isolation
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_what_if_isolation():
    """What-If simulation MUST:
    - Run purely in-memory
    - Create 0 database rows
    - Create 0 audit events
    - Never alter production state
    """
    test_db_url = f"sqlite+aiosqlite:///:memory:"
    engine, session_maker = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)
    await init_db(engine)

    async with session_maker() as session:
        # Seed one production decision
        req = RiskScoreRequest(
            customer_id_hash="cust_prod_baseline_001",
            idempotency_key=f"prod_seed_{uuid.uuid4().hex[:8]}",
            order_value=2200.0,
            product_category="FOOTWEAR",
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
            return_reason="Slight tear",
            days_since_purchase=2,
            customer_order_count=10,
            customer_return_count=1,
            customer_return_rate=0.1,
            prior_return_value=1200.0,
            prior_return_frequency=0.2,
            item_category_return_rate=0.15,
            delivery_distance_bucket="LOCAL",
            reverse_logistics_cost=65.0,
            estimated_item_recovery_value=1900.0,
            historical_abuse_signal=0.05,
        )
        await score_risk_event(session=session, request=req)
        await session.commit()

        # Measure baseline row counts
        rd_count_before = (await session.execute(select(func.count(RiskDecision.id)))).scalar_one()
        pd_count_before = (await session.execute(select(func.count(PolicyDecision.id)))).scalar_one()
        ae_count_before = (await session.execute(select(func.count(AuditEvent.id)))).scalar_one()

    # Run What-If simulation using the exact authoritative endpoint
    sim_req = RiskScoreRequest(
        customer_id_hash="cust_simulation_counterfactual_002",
        idempotency_key=f"sim_{uuid.uuid4().hex[:8]}",
        order_value=12500.0,  # Extreme counterfactual
        product_category="ELECTRONICS",
        payment_method=PaymentMethod.COD,
        cod_flag=True,
        return_reason="What-if claim empty box",
        days_since_purchase=25,
        customer_order_count=2,
        customer_return_count=2,
        customer_return_rate=1.0,
        prior_return_value=25000.0,
        prior_return_frequency=4.0,
        item_category_return_rate=0.25,
        delivery_distance_bucket="NATIONAL",
        reverse_logistics_cost=250.0,
        estimated_item_recovery_value=1000.0,
        historical_abuse_signal=0.9,
    )

    sim_result = await simulate_risk_scenario(sim_req)
    assert sim_result["is_simulation"] is True
    assert "p_return_abuse" in sim_result
    assert "selected_action" in sim_result

    # Verify DB row counts are completely unchanged
    async with session_maker() as session:
        rd_count_after = (await session.execute(select(func.count(RiskDecision.id)))).scalar_one()
        pd_count_after = (await session.execute(select(func.count(PolicyDecision.id)))).scalar_one()
        ae_count_after = (await session.execute(select(func.count(AuditEvent.id)))).scalar_one()

        assert rd_count_after == rd_count_before
        assert pd_count_after == pd_count_before
        assert ae_count_after == ae_count_before


# -----------------------------------------------------------------------------
# 6. Decision Replay Read-Only Isolation Audit
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_replay_read_only_isolation():
    """Decision Replay (GET /api/v1/risk/decisions/{id}/replay) MUST:
    - Execute purely read-only queries
    - Cause 0 database row insertions or deletions
    - Cause 0 audit log mutations
    - Return the exact historical decision fields without re-invoking policy
    """
    test_db_url = f"sqlite+aiosqlite:///:memory:"
    engine, session_maker = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)
    await init_db(engine)

    async with session_maker() as session:
        # Step 1: Seed a production decision
        req = RiskScoreRequest(
            customer_id_hash="cust_replay_audit_001",
            idempotency_key=f"replay_seed_{uuid.uuid4().hex[:8]}",
            order_value=4500.0,
            product_category="ELECTRONICS",
            payment_method=PaymentMethod.PREPAID,
            cod_flag=False,
            return_reason="Missing serial tag on item",
            days_since_purchase=5,
            customer_order_count=8,
            customer_return_count=2,
            customer_return_rate=0.25,
            prior_return_value=3200.0,
            prior_return_frequency=0.5,
            delivery_distance_bucket="LOCAL",
            reverse_logistics_cost=90.0,
            estimated_item_recovery_value=3000.0,
            historical_abuse_signal=0.15,
        )
        res = await score_risk_event(session=session, request=req)
        await session.commit()

        seed_id = uuid.UUID(res["decision_id"])

        # Capture database state before replay
        rd_before = (await session.execute(select(func.count(RiskDecision.id)))).scalar_one()
        pd_before = (await session.execute(select(func.count(PolicyDecision.id)))).scalar_one()
        ae_before = (await session.execute(select(func.count(AuditEvent.id)))).scalar_one()

        # Step 2: Execute Replay
        replay_resp = await replay_decision(decision_id=seed_id, session=session)

        # Step 3: Verify replay response structure and read-only declaration
        assert replay_resp["replay_metadata"]["mode"] == "READ_ONLY_REPLAY"
        assert replay_resp["replay_metadata"]["state_mutation_allowed"] is False
        assert replay_resp["replay_metadata"]["database_writes_committed"] == 0
        assert "step_1_input_features" in replay_resp
        assert "step_2_phase_4_scoring" in replay_resp
        assert "step_3_phase_5_economics" in replay_resp
        assert "step_4_action_decision" in replay_resp

        # Step 4: Verify that row counts are 100% invariant
        rd_after = (await session.execute(select(func.count(RiskDecision.id)))).scalar_one()
        pd_after = (await session.execute(select(func.count(PolicyDecision.id)))).scalar_one()
        ae_after = (await session.execute(select(func.count(AuditEvent.id)))).scalar_one()

        assert rd_after == rd_before
        assert pd_after == pd_before
        assert ae_after == ae_before
