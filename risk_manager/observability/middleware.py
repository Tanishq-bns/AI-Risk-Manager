"""ASGI and FastAPI middleware for HTTP request tracing, latency tracking, and metrics.

Implements Phase 8 correlation requirements:
- Binds X-Request-ID and distributed trace_id to request state.
- Instruments HTTP request duration histograms and request/error counters.
- Enforces safe span attributes with zero PII.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from risk_manager.observability.metrics import (
    HTTP_ERRORS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)
from risk_manager.observability.tracer import (
    get_current_trace_id,
    trace_span,
)

logger = logging.getLogger("risk_manager.observability.middleware")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware combining correlation tracing, latency measurement, and Prometheus counters."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Normalize endpoint path for low-cardinality metrics (e.g. collapse UUIDs)
        path = request.url.path
        route_path = self._normalize_path(path)

        start_time = time.perf_counter()
        method = request.method

        span_attrs = {
            "http.method": method,
            "http.target": route_path,
            "request_id": request_id,
        }

        with trace_span("http.request", span_attrs) as span:
            try:
                response = await call_next(request)
                status_code = response.status_code
            except Exception as exc:
                duration_sec = time.perf_counter() - start_time
                if HTTP_REQUEST_DURATION_SECONDS is not None:
                    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=route_path).observe(duration_sec)
                if HTTP_ERRORS_TOTAL is not None:
                    HTTP_ERRORS_TOTAL.labels(endpoint=route_path, error_code=type(exc).__name__).inc()
                if HTTP_REQUESTS_TOTAL is not None:
                    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=route_path, status_code=500).inc()
                raise exc

            duration_sec = time.perf_counter() - start_time
            duration_ms = round(duration_sec * 1000.0, 2)

            # Record metrics
            if HTTP_REQUEST_DURATION_SECONDS is not None:
                HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=route_path).observe(duration_sec)
            if HTTP_REQUESTS_TOTAL is not None:
                HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=route_path, status_code=status_code).inc()
            if status_code >= 400 and HTTP_ERRORS_TOTAL is not None:
                HTTP_ERRORS_TOTAL.labels(endpoint=route_path, error_code=f"HTTP_{status_code}").inc()

            # Stamping response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-Ms"] = str(duration_ms)

            trace_id = get_current_trace_id() or request.headers.get("X-Trace-ID") or uuid.uuid4().hex
            response.headers["X-Trace-ID"] = trace_id
            span.set_attribute("trace_id", trace_id)

            span.set_attribute("http.status_code", status_code)
            span.set_attribute("http.duration_ms", duration_ms)

            return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Collapse dynamic UUID path parameters into low-cardinality path patterns."""
        parts = path.strip("/").split("/")
        normalized = []
        for part in parts:
            if len(part) == 36 and "-" in part:
                normalized.append("{id}")
            elif part.startswith("idemp_") or part.startswith("cust_"):
                normalized.append("{param}")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized) if normalized else "/"
