"""FastAPI application factory and middleware configuration.

Implements TRD.md §L and Phase 7 Application Architecture.
Mounts routers, provides CORS support, serves static dashboard assets,
and enforces uniform structured error handling and correlation tracking.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
import time
import uuid
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from risk_manager.api.routers.agents import router as agents_router
from risk_manager.api.routers.audit import router as audit_router
from risk_manager.api.routers.demo import router as demo_router
from risk_manager.api.routers.health import router as health_router
from risk_manager.api.routers.policy import router as policy_router
from risk_manager.api.routers.review import router as review_router
from risk_manager.api.routers.risk import router as risk_router
from risk_manager.core.config import settings
from risk_manager.core.logging import get_logger, setup_logging
from risk_manager.db.session import init_db
from risk_manager.observability import (
    ObservabilityMiddleware,
    get_metrics_payload,
    init_tracer,
)

logger = get_logger("risk_manager.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initializes database schema and telemetry on startup."""
    setup_logging(level=settings.LOG_LEVEL, json_format=settings.LOG_JSON)
    init_tracer()
    logger.info("Initializing application schema and ML dependencies...")
    try:
        await init_db()
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.warning("Database auto-initialization deferred or failed: %s", e)
    yield
    logger.info("Shutting down AI Risk Manager API...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AI Risk Manager: Real-Time Return-Risk Scorer & Intervention Sentinel",
        description="Production risk scoring, economic intervention policy, and multi-agent sentinel platform.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT == "development" else ["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    # 2. Observability & Correlation Middleware (Phase 8)
    app.add_middleware(ObservabilityMiddleware)

    # 3. Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected internal server error occurred.",
                    "request_id": req_id,
                }
            },
        )

    # 4. Include Routers
    app.include_router(health_router)
    app.include_router(risk_router)
    app.include_router(policy_router)
    app.include_router(agents_router)
    app.include_router(audit_router)
    app.include_router(review_router)
    app.include_router(demo_router)

    # 5. Dynamic Prometheus Metrics Endpoint (Phase 8)
    @app.get("/metrics", tags=["Observability"])
    async def get_metrics():
        """Expose dynamic Prometheus metrics if enabled."""
        if not settings.PROMETHEUS_METRICS_ENABLED:
            return Response(
                content="# Prometheus metrics disabled\n",
                status_code=status.HTTP_404_NOT_FOUND,
                media_type="text/plain",
            )
        payload, content_type = get_metrics_payload()
        return Response(content=payload, media_type=content_type)

    # 5. Static Files & Root Dashboard
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse({"status": "healthy", "service": "AI Risk Manager API"})

    return app


# Default app instance
app = create_app()
