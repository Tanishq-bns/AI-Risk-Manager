"""Core risk decisioning, scoring, and workflow orchestration service.

Implements TRD.md §E/L, SPEC.md §14/16, and Phase 7 End-to-End API requirements.
Integrates Phase 4 ML Cascade, Phase 5 Policy Engine, and triggers Phase 6 LangGraph
as an asynchronous non-blocking task without compromising the synchronous scoring path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Any
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.agents.graph import run_agent_workflow
from risk_manager.agents.persistence import persist_agent_workflow_result
from risk_manager.agents.state import AgentGraphState
from risk_manager.core.config import settings
from risk_manager.db.models.agent_run import AgentRun
from risk_manager.db.models.audit_event import AuditEvent
from risk_manager.db.models.customer import Customer
from risk_manager.db.models.intervention import Intervention
from risk_manager.db.models.order import Order
from risk_manager.db.models.policy_decision import PolicyDecision
from risk_manager.db.models.return_request import ReturnRequest
from risk_manager.db.models.risk_decision import RiskDecision
from risk_manager.db.models.risk_features import RiskFeatures
from risk_manager.db.services.policy_persistence import persist_policy_evaluation
from risk_manager.db.session import get_db_context
from risk_manager.domain.schemas.enums import (
    Action,
    ActionSelector,
    AgentName,
    AgentRunStatus,
    PaymentMethod,
    PersistenceStatus,
    ReturnRequestStatus,
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
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.cascade import MLCascadeScorer
from risk_manager.ml.bandit.policy_engine import PolicyEngine
from risk_manager.observability import (
    AGENT_FAILURES_TOTAL,
    AGENT_FALLBACK_TOTAL,
    AGENT_HUMAN_REVIEW_TOTAL,
    AGENT_WORKFLOW_DURATION_SECONDS,
    AGENT_WORKFLOW_TOTAL,
    HUMAN_REVIEW_REQUIRED_TOTAL,
    INTERVENTION_ACTION_TOTAL,
    PERSISTENCE_FAILURE_TOTAL,
    PERSISTENCE_OPERATION_TOTAL,
    POLICY_DECISIONS_TOTAL,
    POLICY_DECISION_DURATION_SECONDS,
    PROMPT_INJECTION_DETECTED_TOTAL,
    RISK_BAND_TOTAL,
    RISK_DECISIONS_TOTAL,
    RISK_DECISION_DURATION_SECONDS,
    RISK_FALLBACK_TOTAL,
    trace_span,
)

logger = logging.getLogger(__name__)

# Singletons for fast inference
_cascade_scorer: MLCascadeScorer | None = None
_policy_engine: PolicyEngine | None = None


def get_cascade_scorer() -> MLCascadeScorer:
    global _cascade_scorer
    if _cascade_scorer is None:
        _cascade_scorer = MLCascadeScorer(models_dir="models")
        if _cascade_scorer.tier0.is_loaded:
            try:
                dummy_feat = {
                    "customer_id_hash": "warmup_cust",
                    "order_value": 1500.0,
                    "product_category": "APPAREL",
                    "payment_method": "PREPAID",
                    "cod_flag": False,
                    "customer_order_count": 5,
                    "customer_return_count": 1,
                    "customer_return_rate": 0.20,
                    "days_since_purchase": 3,
                    "prior_return_value": 300.0,
                    "prior_return_frequency": 0.20,
                    "item_category_return_rate": 0.15,
                    "return_reason": "Defective item",
                    "delivery_distance_bucket": "REGIONAL",
                    "reverse_logistics_cost": 120.0,
                    "estimated_item_recovery_value": 800.0,
                    "historical_abuse_signal": 0.0,
                    "feature_schema_version": "v1",
                }
                _cascade_scorer.tier0.predict_one(dummy_feat)
            except Exception:
                pass
    return _cascade_scorer


def get_policy_engine() -> PolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine(models_dir="models", exploration_enabled=False)
    return _policy_engine


def build_feature_vector_from_request(request: RiskScoreRequest) -> FeatureVector:
    """Build a deterministic FeatureVector from request parameters and simulator defaults."""
    order_val = float(request.order_value or 1500.0)
    category = (request.product_category or "APPAREL").upper()
    pm = request.payment_method or (PaymentMethod.COD if request.cod_flag else PaymentMethod.PREPAID)
    cod = bool(request.cod_flag if request.cod_flag is not None else (pm == PaymentMethod.COD))

    return FeatureVector(
        customer_id_hash=request.customer_id_hash,
        order_value=order_val,
        product_category=category,
        payment_method=pm,
        cod_flag=cod,
        customer_order_count=request.customer_order_count if request.customer_order_count is not None else 1,
        customer_return_count=request.customer_return_count if request.customer_return_count is not None else 0,
        customer_return_rate=request.customer_return_rate if request.customer_return_rate is not None else 0.0,
        days_since_purchase=request.days_since_purchase if request.days_since_purchase is not None else 3,
        prior_return_value=request.prior_return_value if request.prior_return_value is not None else 0.0,
        prior_return_frequency=request.prior_return_frequency if request.prior_return_frequency is not None else 0.0,
        item_category_return_rate=request.item_category_return_rate if request.item_category_return_rate is not None else 0.15,
        return_reason=request.return_reason or "Defective item",
        delivery_distance_bucket=(request.delivery_distance_bucket or "REGIONAL").upper(),
        reverse_logistics_cost=request.reverse_logistics_cost if request.reverse_logistics_cost is not None else 135.0,
        estimated_item_recovery_value=request.estimated_item_recovery_value if request.estimated_item_recovery_value is not None else 900.0,
        historical_abuse_signal=request.historical_abuse_signal if request.historical_abuse_signal is not None else 0.0,
        feature_schema_version="v1",
    )


async def ensure_db_dependencies(
    session: AsyncSession,
    request: RiskScoreRequest,
    feature_vector: FeatureVector,
) -> tuple[Customer, Order, ReturnRequest]:
    """Ensure prerequisite Customer, Order, and ReturnRequest records exist to satisfy foreign keys."""
    # 1. Customer
    cust_res = await session.execute(
        select(Customer).where(Customer.customer_id_hash == request.customer_id_hash)
    )
    customer = cust_res.scalar_one_or_none()
    if not customer:
        customer = Customer(
            customer_id_hash=request.customer_id_hash,
            created_at=datetime.now(timezone.utc),
        )
        session.add(customer)

    # 2. Order
    order_id = request.order_id or uuid.uuid4()
    order_res = await session.execute(
        select(Order).where(Order.id == order_id)
    )
    order = order_res.scalar_one_or_none()
    if not order:
        order = Order(
            id=order_id,
            customer_id_hash=customer.customer_id_hash,
            order_value=Decimal(str(round(feature_vector.order_value, 2))),
            payment_method=feature_vector.payment_method,
            cod_flag=feature_vector.cod_flag,
            created_at=datetime.now(timezone.utc),
        )
        session.add(order)

    # 3. ReturnRequest
    return_req_id = request.return_request_id or uuid.uuid4()
    return_res = await session.execute(
        select(ReturnRequest).where(ReturnRequest.id == return_req_id)
    )
    return_req = return_res.scalar_one_or_none()
    if not return_req:
        return_req = ReturnRequest(
            id=return_req_id,
            order_id=order.id,
            return_reason=feature_vector.return_reason,
            status=ReturnRequestStatus.PENDING,
            requested_at=datetime.now(timezone.utc),
        )
        session.add(return_req)

    await session.flush()

    return customer, order, return_req


async def score_risk_event(
    session: AsyncSession,
    request: RiskScoreRequest,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Execute end-to-end real-time scoring and intervention assignment.

    Synchronous path: Feature Vector -> Phase 4 ML -> Phase 5 Policy -> Persistence -> Response.
    Asynchronous path: Phase 6 LangGraph Agent Workflow triggered via BackgroundTasks.
    """
    start_time = time.perf_counter()

    with trace_span("risk.score", {"idempotency_key": request.idempotency_key}) as score_span:
        # 1. Idempotency Check
        existing_stmt = (
            select(RiskDecision)
            .where(RiskDecision.idempotency_key == request.idempotency_key)
        )
        existing_res = await session.execute(existing_stmt)
        existing_decision = existing_res.scalar_one_or_none()

        if existing_decision is not None:
            logger.info(
                "Idempotent hit for key '%s', returning decision %s",
                request.idempotency_key,
                existing_decision.id,
            )
            score_span.set_attribute("is_idempotent_hit", True)
            return await format_decision_response(session, existing_decision, is_cached=True)

        # 2. Build Feature Vector & Ensure DB Context
        with trace_span("feature_engineering") as fe_span:
            feature_vector = build_feature_vector_from_request(request)
            customer, order, return_req = await ensure_db_dependencies(session, request, feature_vector)
            fe_span.set_attribute("customer_id_hash", request.customer_id_hash)

        # 3. Run Phase 4 Cascade Scorer
        p4_start = time.perf_counter()
        with trace_span("phase4.risk_cascade") as p4_span:
            cascade = get_cascade_scorer()
            risk_result = cascade.score(feature_vector)
            p4_duration = time.perf_counter() - p4_start
            
            src_val = risk_result.scoring_source.value if hasattr(risk_result.scoring_source, "value") else str(risk_result.scoring_source)
            tier_val = str(risk_result.fallback_tier.value if hasattr(risk_result.fallback_tier, "value") else risk_result.fallback_tier)
            band_val = risk_result.risk_band.value if hasattr(risk_result.risk_band, "value") else str(risk_result.risk_band)

            if RISK_DECISION_DURATION_SECONDS is not None:
                RISK_DECISION_DURATION_SECONDS.labels(scoring_source=src_val).observe(p4_duration)
            if RISK_DECISIONS_TOTAL is not None:
                RISK_DECISIONS_TOTAL.labels(scoring_source=src_val, fallback_tier=tier_val).inc()
            if RISK_BAND_TOTAL is not None:
                RISK_BAND_TOTAL.labels(risk_band=band_val).inc()
            if int(tier_val) > 0 and RISK_FALLBACK_TOTAL is not None:
                RISK_FALLBACK_TOTAL.labels(from_tier="0", to_tier=tier_val, reason=str(risk_result.fallback_reason or "CASCADE_DEGRADATION")).inc()

            p4_span.set_attribute("p_return_abuse", float(risk_result.p_return_abuse))
            p4_span.set_attribute("risk_band", band_val)
            p4_span.set_attribute("scoring_source", src_val)
            p4_span.set_attribute("fallback_tier", tier_val)

        risk_decision_id = uuid.uuid4()
        score_span.set_attribute("risk_decision_id", str(risk_decision_id))

        # 4. Run Phase 5 Economic & Policy Engine
        p5_start = time.perf_counter()
        with trace_span("phase5.policy_engine") as p5_span:
            policy_engine = get_policy_engine()
            policy_context = policy_engine.evaluate_policy(
                feature_vector=feature_vector,
                p_return_abuse=risk_result.p_return_abuse,
                risk_band=risk_result.risk_band,
                risk_decision_id=risk_decision_id,
                is_automated=True,
            )
            p5_duration = time.perf_counter() - p5_start

            selector_val = policy_context.action_selector.value if hasattr(policy_context.action_selector, "value") else str(policy_context.action_selector)
            action_val = policy_context.action_selected.value if hasattr(policy_context.action_selected, "value") else str(policy_context.action_selected)

            if POLICY_DECISION_DURATION_SECONDS is not None:
                POLICY_DECISION_DURATION_SECONDS.labels(selector=selector_val).observe(p5_duration)
            if POLICY_DECISIONS_TOTAL is not None:
                POLICY_DECISIONS_TOTAL.labels(selector=selector_val, action=action_val).inc()
            if INTERVENTION_ACTION_TOTAL is not None:
                for candidate in policy_context.candidate_actions:
                    c_act = candidate.action.value if hasattr(candidate.action, "value") else str(candidate.action)
                    INTERVENTION_ACTION_TOTAL.labels(action=c_act, is_eligible=str(candidate.is_eligible).lower()).inc()

            p5_span.set_attribute("selected_action", action_val)
            p5_span.set_attribute("action_selector", selector_val)
            p5_span.set_attribute("expected_net_value", float(policy_context.expected_net_value))

        # 5. Persist RiskDecision & RiskFeatures
        try:
            with trace_span("persistence") as persist_span:
                p_abuse_dec = Decimal(str(round(risk_result.p_return_abuse, 4)))
                risk_decision = RiskDecision(
                    id=risk_decision_id,
                    return_request_id=return_req.id,
                    idempotency_key=request.idempotency_key,
                    p_return_abuse=p_abuse_dec,
                    risk_band=risk_result.risk_band,
                    scoring_source=risk_result.scoring_source,
                    fallback_tier=risk_result.fallback_tier,
                    fallback_reason=risk_result.fallback_reason,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(risk_decision)

                features_snapshot = RiskFeatures(
                    id=uuid.uuid4(),
                    risk_decision_id=risk_decision_id,
                    features=feature_vector.model_dump(mode="json"),
                    feature_schema_version="v1",
                )
                session.add(features_snapshot)

                # 6. Persist Policy Evaluation (Intervention, PolicyDecision, AuditEvent)
                with trace_span("audit.event"):
                    intervention, policy_decision, audit_event = await persist_policy_evaluation(
                        session=session,
                        policy_context=policy_context,
                        flush_only=False,
                    )

                if PERSISTENCE_OPERATION_TOTAL is not None:
                    PERSISTENCE_OPERATION_TOTAL.labels(entity="risk_decision", operation="insert").inc()
                    PERSISTENCE_OPERATION_TOTAL.labels(entity="policy_decision", operation="insert").inc()
        except Exception as p_exc:
            if PERSISTENCE_FAILURE_TOTAL is not None:
                PERSISTENCE_FAILURE_TOTAL.labels(entity="risk_persistence", error_code=type(p_exc).__name__).inc()
            raise p_exc

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        score_span.set_attribute("duration_ms", latency_ms)

        # 7. Asynchronously trigger Phase 6 Agent Workflow
        if background_tasks is not None and settings.AGENTS_ENABLED:
            background_tasks.add_task(run_agent_workflow_background, risk_decision_id)
            agent_status = "PENDING"
        else:
            agent_status = "DISABLED" if not settings.AGENTS_ENABLED else "PENDING"

    # 8. Structure Authoritative Immediate Response
    cand, pred = policy_engine.to_domain_response(policy_context)
    evidence_signals = []
    if feature_vector.customer_return_rate > 0.30:
        evidence_signals.append(f"Elevated customer return rate: {feature_vector.customer_return_rate:.1%}")
    if feature_vector.historical_abuse_signal > 0.0:
        evidence_signals.append(f"Prior abuse signal: {feature_vector.historical_abuse_signal:.2f}")
    if feature_vector.order_value > 3000.0:
        evidence_signals.append(f"High order value: INR {feature_vector.order_value:,.2f}")
    if feature_vector.cod_flag:
        evidence_signals.append("Cash On Delivery payment")
    if not evidence_signals:
        evidence_signals.append("Standard transaction profile")

    return {
        "decision_id": str(policy_context.decision_id),
        "risk_decision_id": str(risk_decision_id),
        "p_return_abuse": float(risk_result.p_return_abuse),
        "risk_band": risk_result.risk_band.value,
        "scoring_source": risk_result.scoring_source.value,
        "fallback_tier": risk_result.fallback_tier,
        "selected_action": policy_context.action_selected.value,
        "action_name": cand.action.name if hasattr(cand.action, "name") else str(cand.action),
        "economic": {
            "expected_loss": round(float(pred.expected_loss_with_action), 2),
            "expected_net_value": round(float(policy_context.expected_net_value), 2),
            "expected_loss_no_action": round(float(pred.expected_loss_no_action), 2),
            "expected_loss_with_action": round(float(pred.expected_loss_with_action), 2),
        },

        "guardrails_applied": policy_context.guardrails_applied,
        "agent_status": agent_status,
        "evidence": {
            "top_signals": evidence_signals,
            "feature_completeness": 1.0,
        },
        "model_metadata": {
            "model_version": "v1.0.0-xgb",
            "model_type": risk_result.scoring_source.value,
        },
        "fallback_metadata": {
            "fallback_tier": risk_result.fallback_tier,
            "fallback_reason": risk_result.fallback_reason,
        },
        "candidate_actions": [
            {
                "action": a.action.value,
                "action_name": a.action_name,
                "expected_loss": round(float(a.expected_loss), 2),
                "expected_net_value": round(float(a.expected_net_value), 2),
                "is_eligible": a.is_eligible,
                "ineligibility_reason": a.ineligibility_reason,
            }
            for a in policy_context.candidate_actions
        ],
        "latency_ms": latency_ms,
        "persistence_status": PersistenceStatus.PERSISTED.value,
    }



async def format_decision_response(
    session: AsyncSession,
    risk_decision: RiskDecision,
    is_cached: bool = False,
) -> dict[str, Any]:
    """Format an existing RiskDecision record into a full response dictionary."""
    p_abuse = float(risk_decision.p_return_abuse)
    band = risk_decision.risk_band.value

    # Fetch latest policy decision
    policy_stmt = (
        select(PolicyDecision)
        .where(PolicyDecision.risk_decision_id == risk_decision.id)
        .order_by(desc(PolicyDecision.created_at))
    )
    pol_res = await session.execute(policy_stmt)
    latest_pd = pol_res.scalars().first()

    # Fetch latest intervention
    int_stmt = (
        select(Intervention)
        .where(Intervention.risk_decision_id == risk_decision.id)
        .order_by(desc(Intervention.created_at))
    )
    int_res = await session.execute(int_stmt)
    latest_int = int_res.scalars().first()


    selected_action = latest_pd.new_action if latest_pd else (latest_int.action if latest_int else Action.A0)
    net_val = float(latest_int.expected_net_value) if latest_int else 0.0

    # Fetch agent run status
    agent_stmt = (
        select(AgentRun)
        .where(AgentRun.risk_decision_id == risk_decision.id)
    )
    agent_res = await session.execute(agent_stmt)
    runs = agent_res.scalars().all()
    agent_status = "COMPLETED" if runs else "PENDING"
    requires_human = False
    for r in runs:
        if r.agent_name == AgentName.VERIFIER and r.output:
            if r.output.get("requires_human_review"):
                requires_human = True

    # Fetch features
    features_dict = {}
    if risk_decision.features and risk_decision.features.features:
        features_dict = risk_decision.features.features

    # Fetch stored expected_loss from policy audit event if available
    act_str = selected_action.value if hasattr(selected_action, "value") else str(selected_action)
    exp_loss = round(p_abuse * float(features_dict.get("order_value", 1500.0)), 2)
    guardrails = []
    candidates = []

    audit_stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_type == "policy.decision.v1")
        .order_by(desc(AuditEvent.occurred_at))
    )
    audit_res = await session.execute(audit_stmt)
    for a in audit_res.scalars().all():
        if a.payload and a.payload.get("risk_decision_id") == str(risk_decision.id):
            guardrails = a.payload.get("guardrails_applied", [])
            candidates = a.payload.get("candidate_actions", [])
            for cand in candidates:
                if cand.get("action") == act_str:
                    exp_loss = round(float(cand.get("expected_loss", exp_loss)), 2)
                    break
            break

    return {
        "decision_id": str(latest_pd.id if latest_pd else risk_decision.id),
        "risk_decision_id": str(risk_decision.id),
        "p_return_abuse": p_abuse,
        "risk_band": band,
        "scoring_source": risk_decision.scoring_source.value,
        "fallback_tier": risk_decision.fallback_tier,
        "selected_action": act_str,
        "economic": {
            "expected_loss": exp_loss,
            "expected_net_value": round(net_val, 2),
        },
        "guardrails_applied": guardrails,
        "candidate_actions": candidates,
        "agent_status": agent_status,
        "requires_human_review": requires_human,
        "is_cached": is_cached,
        "features": features_dict,
        "created_at": risk_decision.created_at.isoformat() if risk_decision.created_at else None,
    }



async def build_agent_graph_state_for_decision(
    session: AsyncSession,
    risk_decision_id: uuid.UUID,
) -> AgentGraphState:
    """Construct an AgentGraphState from database records for Phase 6 execution."""
    stmt = (
        select(RiskDecision)
        .where(RiskDecision.id == risk_decision_id)
    )
    res = await session.execute(stmt)
    dec = res.scalar_one_or_none()
    if not dec:
        raise ValueError(f"Risk decision {risk_decision_id} not found")

    p_abuse = float(dec.p_return_abuse)
    band = dec.risk_band.value

    # Policy decision
    pol_stmt = (
        select(PolicyDecision)
        .where(PolicyDecision.risk_decision_id == risk_decision_id)
        .order_by(desc(PolicyDecision.created_at))
    )
    pol_res = await session.execute(pol_stmt)
    latest_pd = pol_res.scalars().first()

    # Intervention
    int_stmt = (
        select(Intervention)
        .where(Intervention.risk_decision_id == risk_decision_id)
        .order_by(desc(Intervention.created_at))
    )
    int_res = await session.execute(int_stmt)
    latest_int = int_res.scalars().first()


    selected_act = latest_pd.new_action if latest_pd else (latest_int.action if latest_int else Action.A0)
    selector_str = latest_pd.selected_by.value if latest_pd else (latest_int.selected_by.value if latest_int else "RULES")
    net_val = float(latest_int.expected_net_value) if latest_int else 0.0

    features_map = {}
    if dec.features and dec.features.features:
        features_map = dec.features.features

    order_val = float(features_map.get("order_value", 1500.0))
    exp_loss = round(p_abuse * order_val, 2)

    # Construct state
    return AgentGraphState(
        decision_id=latest_pd.id if latest_pd else dec.id,
        risk_decision_id=dec.id,
        policy_decision_id=latest_pd.id if latest_pd else dec.id,
        trace_id=str(uuid.uuid4()),
        p_return_abuse=p_abuse,
        risk_band=band,
        scoring_source=dec.scoring_source.value,
        fallback_tier=dec.fallback_tier,
        selected_action=selected_act,
        action_selector=selector_str,
        expected_loss=exp_loss,
        expected_net_value=net_val,
        candidate_actions=[
            {"action": "A0", "action_name": "ZERO_FRICTION_APPROVAL", "expected_loss": exp_loss, "expected_net_value": 0.0, "is_eligible": True},
            {"action": "A1", "action_name": "DYNAMIC_RETURN_FEE", "expected_loss": exp_loss * 0.8, "expected_net_value": 20.0, "is_eligible": True},
            {"action": "A2", "action_name": "OTP_DOORSTEP_INSPECTION", "expected_loss": exp_loss * 0.5, "expected_net_value": 50.0, "is_eligible": True},
            {"action": "A3", "action_name": "STORE_CREDIT_DEFAULT", "expected_loss": exp_loss * 0.3, "expected_net_value": 70.0, "is_eligible": True},
            {"action": "A4", "action_name": "MANUAL_REVIEW_REJECT", "expected_loss": 0.0, "expected_net_value": exp_loss, "is_eligible": True},
        ],
        guardrails_applied=[],
        feature_evidence={
            "completeness_ratio": 1.0,
            "top_signals": ["risk_score_evaluated"],
        },
        customer_history={
            "order_value": order_val,
            "payment_method": features_map.get("payment_method", "PREPAID"),
            "order_count": features_map.get("customer_order_count", 1),
            "return_count": features_map.get("customer_return_count", 0),
            "return_reason": features_map.get("return_reason", "Defective item"),
        },
        model_metadata={"model_version": "v1.0.0-xgb"},
        timestamps={},
    )


async def run_agent_workflow_background(risk_decision_id: uuid.UUID) -> None:
    """Asynchronous background task executing Phase 6 LangGraph workflow."""
    with trace_span("agent.workflow", {"risk_decision_id": str(risk_decision_id)}) as agent_span:
        try:
            async with get_db_context() as session:
                state = await build_agent_graph_state_for_decision(session, risk_decision_id)
                result = await run_agent_workflow(state)
                await persist_agent_workflow_result(session, result)
                logger.info("Asynchronous agent workflow completed for %s", risk_decision_id)

                agent_span.set_attribute("agent_status", result.agent_status.value)
                agent_span.set_attribute("provider", result.provider)
                agent_span.set_attribute("requires_human_review", result.requires_human_review)

                if AGENT_WORKFLOW_TOTAL is not None:
                    AGENT_WORKFLOW_TOTAL.labels(provider=result.provider, status=result.agent_status.value).inc()
                if AGENT_WORKFLOW_DURATION_SECONDS is not None:
                    AGENT_WORKFLOW_DURATION_SECONDS.labels(provider=result.provider).observe(result.latency_ms / 1000.0)
                if result.fallback_reason and AGENT_FALLBACK_TOTAL is not None:
                    AGENT_FALLBACK_TOTAL.labels(reason=str(result.fallback_reason)).inc()
                if result.requires_human_review:
                    if AGENT_HUMAN_REVIEW_TOTAL is not None:
                        AGENT_HUMAN_REVIEW_TOTAL.labels(reason="verifier_or_policy").inc()
                    if HUMAN_REVIEW_REQUIRED_TOTAL is not None:
                        act_val = result.selected_action.value if hasattr(result.selected_action, "value") else str(result.selected_action)
                        HUMAN_REVIEW_REQUIRED_TOTAL.labels(trigger_source="agent_sentinel", action=act_val).inc()

                # Check prompt injection classification
                if result.investigator_result and PROMPT_INJECTION_DETECTED_TOTAL is not None:
                    contra_and_risks = (result.investigator_result.contradictions or []) + (result.investigator_result.key_risk_factors or [])
                    if any("adversarial" in str(x).lower() or "injection" in str(x).lower() for x in contra_and_risks):
                        routing = result.orchestrator_result.execution_mode if result.orchestrator_result else "UNKNOWN"
                        PROMPT_INJECTION_DETECTED_TOTAL.labels(agent_name="investigator", routing_status=str(routing)).inc()
                        agent_span.set_attribute("prompt_injection_detected", True)

        except Exception as e:
            logger.error("Background agent workflow failed for %s: %s", risk_decision_id, e, exc_info=True)
            if AGENT_FAILURES_TOTAL is not None:
                AGENT_FAILURES_TOTAL.labels(agent_name="workflow", error_type=type(e).__name__).inc()
