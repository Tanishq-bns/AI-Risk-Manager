"""Unit tests for Phase 7 API endpoints.

Covers:
1. Health endpoint
2. Real-time risk scoring
3. Invalid request handling
4. Decision retrieval
5. Agent workflow execution endpoint
6. Agent results inspection
7. Chronological audit timeline
8. Human review queue
9. Manual operator override & audit recording
10. Idempotency guarantees
11. PII protection
12. Demo presets
"""

from __future__ import annotations

import uuid
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from risk_manager.api.app import app
from risk_manager.db.session import (
    Base,
    create_engine_and_sessionmaker,
    get_db_session,
    init_db,
)
from risk_manager.domain.schemas.enums import Action, RiskBand


@pytest.fixture
async def api_client(monkeypatch):
    """Async test client configured with an isolated in-memory SQLite database."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    test_engine, session_maker = create_engine_and_sessionmaker(database_url=test_db_url, echo=False)
    await init_db(test_engine)

    # Ensure background tasks and dependency both use this test database
    monkeypatch.setattr("risk_manager.db.session.engine", test_engine)
    monkeypatch.setattr("risk_manager.db.session.async_session_factory", session_maker)

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()



@pytest.mark.asyncio
async def test_health_endpoint(api_client: httpx.AsyncClient):
    """GET /api/v1/health returns 200 with structured component diagnostics."""
    res = await api_client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["service"] == "ai-risk-manager"
    assert "dependencies" in data
    assert "database" in data["dependencies"]
    assert "ml_models" in data["dependencies"]
    assert "agent_layer" in data["dependencies"]


@pytest.mark.asyncio
async def test_risk_scoring_success(api_client: httpx.AsyncClient):
    """POST /api/v1/risk/score scores return risk and returns authoritative decision."""
    payload = {
        "customer_id_hash": "cust_test_001",
        "idempotency_key": "idemp_test_001",
        "order_value": 2500.0,
        "product_category": "APPAREL",
        "payment_method": "PREPAID",
        "cod_flag": False,
        "return_reason": "Item was damaged on arrival",
        "days_since_purchase": 3,
        "customer_order_count": 15,
        "customer_return_count": 1,
        "customer_return_rate": 0.067,
        "prior_return_value": 450.0,
        "prior_return_frequency": 0.2,
        "delivery_distance_bucket": "LOCAL",
        "historical_abuse_signal": 0.0,
        "estimated_item_recovery_value": 1800.0,
    }

    res = await api_client.post("/api/v1/risk/score", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "decision_id" in data
    assert "risk_decision_id" in data
    assert 0.0 <= data["p_return_abuse"] <= 1.0
    assert data["risk_band"] in [b.value for b in RiskBand]
    assert "selected_action" in data
    assert "economic" in data
    assert "expected_loss" in data["economic"]
    assert "expected_net_value" in data["economic"]
    assert data["agent_status"] in ("PENDING", "DISABLED")
    assert len(data["candidate_actions"]) == 5


@pytest.mark.asyncio
async def test_risk_scoring_invalid_payload(api_client: httpx.AsyncClient):
    """POST /api/v1/risk/score rejects invalid payloads with 422 Unprocessable Entity."""
    # Missing mandatory idempotency_key
    invalid_payload = {
        "customer_id_hash": "cust_test_002",
        "order_value": 2000.0,
    }
    res = await api_client.post("/api/v1/risk/score", json=invalid_payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_idempotency_scoring_returns_same_decision(api_client: httpx.AsyncClient):
    """POST /api/v1/risk/score with duplicate idempotency_key returns cached decision."""
    idemp_key = f"idemp_dup_{uuid.uuid4().hex[:8]}"
    payload = {
        "customer_id_hash": "cust_dup_001",
        "idempotency_key": idemp_key,
        "order_value": 3000.0,
        "product_category": "ELECTRONICS",
        "payment_method": "PREPAID",
        "return_reason": "Broken screen",
    }

    # 1. First scoring request
    res1 = await api_client.post("/api/v1/risk/score", json=payload)
    assert res1.status_code == 200
    d1 = res1.json()

    # 2. Second identical scoring request with duplicate key
    res2 = await api_client.post("/api/v1/risk/score", json=payload)
    assert res2.status_code == 200
    d2 = res2.json()

    # Assert exact same decision ID and values returned
    assert d1["risk_decision_id"] == d2["risk_decision_id"]
    assert d1["p_return_abuse"] == d2["p_return_abuse"]
    assert d1["risk_band"] == d2["risk_band"]
    assert d1["selected_action"] == d2["selected_action"]


@pytest.mark.asyncio
async def test_decision_retrieval(api_client: httpx.AsyncClient):
    """GET /api/v1/risk/decisions/{id} returns full decision view."""
    # First create a decision
    payload = {
        "customer_id_hash": "cust_lookup_001",
        "idempotency_key": f"idemp_lookup_{uuid.uuid4().hex[:8]}",
        "order_value": 1500.0,
        "product_category": "FOOTWEAR",
        "payment_method": "COD",
        "cod_flag": True,
        "return_reason": "Too large",
    }
    score_res = await api_client.post("/api/v1/risk/score", json=payload)
    score_data = score_res.json()
    risk_id = score_data["risk_decision_id"]

    # Retrieve decision
    get_res = await api_client.get(f"/api/v1/risk/decisions/{risk_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()

    assert get_data["risk_decision_id"] == risk_id
    assert get_data["p_return_abuse"] == score_data["p_return_abuse"]
    assert get_data["risk_band"] == score_data["risk_band"]
    assert get_data["selected_action"] == score_data["selected_action"]


@pytest.mark.asyncio
async def test_decision_retrieval_not_found(api_client: httpx.AsyncClient):
    """GET /api/v1/risk/decisions/{id} returns 404 for unknown UUID."""
    fake_id = uuid.uuid4()
    res = await api_client.get(f"/api/v1/risk/decisions/{fake_id}")
    assert res.status_code == 404
    data = res.json()
    assert "detail" in data
    assert data["detail"]["code"] == "DECISION_NOT_FOUND"


@pytest.mark.asyncio
async def test_agent_workflow_and_results(api_client: httpx.AsyncClient):
    """POST /api/v1/agents/run/{id} executes workflow and GET /api/v1/agents/{id} inspects it."""
    # Create decision
    payload = {
        "customer_id_hash": "cust_agent_001",
        "idempotency_key": f"idemp_agent_{uuid.uuid4().hex[:8]}",
        "order_value": 2200.0,
        "product_category": "APPAREL",
        "payment_method": "PREPAID",
        "return_reason": "Wrong item delivered",
    }
    score_res = await api_client.post("/api/v1/risk/score", json=payload)
    risk_id = score_res.json()["risk_decision_id"]

    # Run agents explicitly
    agent_run_res = await api_client.post(f"/api/v1/agents/run/{risk_id}")
    assert agent_run_res.status_code == 200
    run_data = agent_run_res.json()

    assert run_data["agent_status"] in ("COMPLETED", "DEGRADED")
    assert "provider" in run_data
    assert "is_llm_generated" in run_data
    assert "requires_human_review" in run_data

    # Inspect results
    inspect_res = await api_client.get(f"/api/v1/agents/{risk_id}")
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()

    assert inspect_data["status"] == "COMPLETED"
    assert inspect_data["investigator"] is not None
    assert inspect_data["verifier"] is not None
    assert inspect_data["orchestrator"] is not None
    assert "provenance" in inspect_data
    assert inspect_data["provenance"]["provider"] in ("GEMINI", "DETERMINISTIC_FALLBACK")


@pytest.mark.asyncio
async def test_audit_timeline(api_client: httpx.AsyncClient):
    """GET /api/v1/audit/{id} returns chronological state transition events."""
    payload = {
        "customer_id_hash": "cust_audit_001",
        "idempotency_key": f"idemp_audit_{uuid.uuid4().hex[:8]}",
        "order_value": 3500.0,
        "product_category": "ELECTRONICS",
        "payment_method": "PREPAID",
        "return_reason": "Not working",
    }
    score_res = await api_client.post("/api/v1/risk/score", json=payload)
    risk_id = score_res.json()["risk_decision_id"]

    # Run agents to add agent audit event
    await api_client.post(f"/api/v1/agents/run/{risk_id}")

    # Fetch audit timeline
    audit_res = await api_client.get(f"/api/v1/audit/{risk_id}")
    assert audit_res.status_code == 200
    audit_data = audit_res.json()

    assert audit_data["risk_decision_id"] == risk_id
    assert len(audit_data["timeline"]) >= 2
    event_types = [e["event_type"] for e in audit_data["timeline"]]
    assert "risk.scored.v1" in event_types
    assert "policy.decision.v1" in event_types


@pytest.mark.asyncio
async def test_manual_override_flow(api_client: httpx.AsyncClient):
    """POST /api/v1/review/{id}/override records authorized human change with audit event."""
    # 1. Create decision
    payload = {
        "customer_id_hash": "cust_review_001",
        "idempotency_key": f"idemp_rev_{uuid.uuid4().hex[:8]}",
        "order_value": 4500.0,
        "product_category": "FOOTWEAR",
        "payment_method": "COD",
        "cod_flag": True,
        "return_reason": "Defective soul",
    }
    score_res = await api_client.post("/api/v1/risk/score", json=payload)
    risk_id = score_res.json()["risk_decision_id"]
    original_action = score_res.json()["selected_action"]

    # 2. Check review queue endpoint
    q_res = await api_client.get("/api/v1/review/queue")
    assert q_res.status_code == 200

    # 3. Apply authorized manual override
    override_payload = {
        "operator_id": "operator_sarah_102",
        "reason": "Customer provided photos of shipping damage; approved one-time zero friction exception.",
        "new_action": "A0",
    }
    override_res = await api_client.post(f"/api/v1/review/{risk_id}/override", json=override_payload)
    assert override_res.status_code == 200
    over_data = override_res.json()

    assert over_data["decision_id"] == risk_id
    assert over_data["new_action"] == "A0"
    assert "audit_event_id" in over_data

    # 4. Verify decision now reflects overridden action
    dec_res = await api_client.get(f"/api/v1/risk/decisions/{risk_id}")
    assert dec_res.status_code == 200
    assert dec_res.json()["selected_action"] == "A0"

    # 5. Verify audit timeline includes policy.override.v1
    audit_res = await api_client.get(f"/api/v1/audit/{risk_id}")
    assert audit_res.status_code == 200
    types = [e["event_type"] for e in audit_res.json()["timeline"]]
    assert "policy.override.v1" in types


@pytest.mark.asyncio
async def test_manual_override_missing_reason_rejected(api_client: httpx.AsyncClient):
    """POST /api/v1/review/{id}/override requires mandatory reason and operator."""
    fake_id = uuid.uuid4()
    bad_override = {
        "operator_id": "",
        "reason": "",
        "new_action": "A0",
    }
    res = await api_client.post(f"/api/v1/review/{fake_id}/override", json=bad_override)
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_demo_presets_endpoint(api_client: httpx.AsyncClient):
    """GET /api/v1/demo/presets returns the 5 standardized scenarios."""
    res = await api_client.get("/api/v1/demo/presets")
    assert res.status_code == 200
    presets = res.json()

    required_presets = [
        "legitimate_low_risk",
        "suspicious_returner",
        "serial_returner",
        "critical_human_review",
        "prompt_injection_defense",
    ]
    for p in required_presets:
        assert p in presets
        assert "name" in presets[p]
        assert "payload" in presets[p]
        assert "customer_id_hash" in presets[p]["payload"]


@pytest.mark.asyncio
async def test_no_sensitive_pii_in_responses(api_client: httpx.AsyncClient):
    """Ensure response envelopes do not expose raw passwords, cards, or unhashed identifiers."""
    payload = {
        "customer_id_hash": "cust_hash_secure_999",
        "idempotency_key": f"idemp_pii_{uuid.uuid4().hex[:8]}",
        "order_value": 1200.0,
        "product_category": "APPAREL",
        "payment_method": "PREPAID",
        "return_reason": "Fit issue",
    }
    res = await api_client.post("/api/v1/risk/score", json=payload)
    assert res.status_code == 200
    text_content = res.text

    assert "password" not in text_content.lower()
    assert "credit_card" not in text_content.lower()
    assert "cvv" not in text_content.lower()


@pytest.mark.asyncio
async def test_policy_actions_endpoint(api_client: httpx.AsyncClient):
    """GET /api/v1/policy/actions returns candidate intervention catalog with guardrails."""
    res = await api_client.get("/api/v1/policy/actions")
    assert res.status_code == 200
    actions = res.json()
    assert len(actions) == 5
    codes = [a["code"] for a in actions]
    assert codes == ["A0", "A1", "A2", "A3", "A4"]


@pytest.mark.asyncio
async def test_policy_decision_retrieval(api_client: httpx.AsyncClient):
    """GET /api/v1/policy/{id} retrieves authoritative policy action state."""
    payload = {
        "customer_id_hash": "cust_pol_001",
        "idempotency_key": f"idemp_pol_{uuid.uuid4().hex[:8]}",
        "order_value": 2400.0,
        "product_category": "APPAREL",
        "payment_method": "PREPAID",
        "return_reason": "Size too small",
    }
    score_res = await api_client.post("/api/v1/risk/score", json=payload)
    risk_id = score_res.json()["risk_decision_id"]

    pol_res = await api_client.get(f"/api/v1/policy/{risk_id}")
    assert pol_res.status_code == 200
    pol_data = pol_res.json()
    assert pol_data["risk_decision_id"] == risk_id
    assert pol_data["selected_action"] in ["A0", "A1", "A2", "A3", "A4"]


@pytest.mark.asyncio
async def test_metrics_endpoint(api_client: httpx.AsyncClient):
    """GET /metrics returns Prometheus format exposition text."""
    res = await api_client.get("/metrics")
    assert res.status_code == 200
    assert "ai_risk_manager_up" in res.text

