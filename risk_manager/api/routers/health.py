"""Health check router implementing Part 2 requirements.

Provides structured readiness and dependency diagnostics without crashing
if optional services are unavailable.
"""

from __future__ import annotations

import os
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.core.config import settings
from risk_manager.db.session import get_db_session

router = APIRouter(prefix="/api/v1", tags=["Health"])


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_db_session)) -> dict:
    """Service health and component dependency status."""
    # 1. Database check
    db_status = "healthy"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "degraded"

    # 2. ML model artifacts check
    ml_status = "healthy"
    required_models = ["xgboost_model.joblib", "isotonic_calibrator.joblib", "isolation_forest.joblib"]
    for m in required_models:
        if not os.path.exists(os.path.join("models", m)):
            ml_status = "degraded"
            break

    # 3. Agent layer check
    if not settings.AGENTS_ENABLED:
        agent_status = "disabled"
    elif not settings.GEMINI_API_KEY:
        agent_status = "degraded"  # Running deterministic fallback
    else:
        agent_status = "enabled"

    # 4. Observability layer check (Phase 8)
    otel_status = "enabled" if settings.OTEL_ENABLED else "disabled"
    prom_status = "enabled" if settings.PROMETHEUS_METRICS_ENABLED else "disabled"
    exporter_status = "configured" if settings.OTEL_EXPORTER_OTLP_ENDPOINT else "unconfigured"

    overall_status = "healthy" if db_status == "healthy" and ml_status == "healthy" else "degraded"

    return {
        "status": overall_status,
        "service": "ai-risk-manager",
        "version": "0.1.0",
        "dependencies": {
            "database": db_status,
            "ml_models": ml_status,
            "agent_layer": agent_status,
        },
        "observability": {
            "opentelemetry": otel_status,
            "prometheus": prom_status,
            "tracing_exporter": exporter_status,
        },
    }
