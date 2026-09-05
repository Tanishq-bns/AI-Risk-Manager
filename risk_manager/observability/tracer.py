"""OpenTelemetry distributed tracing setup, context managers, and correlation utilities.

Implements Phase 8 tracing requirements:
- Clean integration with opentelemetry-api and opentelemetry-sdk.
- Configurable sampling (parentbased_traceidratio) and exporter endpoints.
- Safe zero-overhead no-op behavior when OTEL_ENABLED=false or when collectors are absent.
- Bounded trace attributes with automated PII and credential scrubbing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import functools
import logging
from typing import Any, Callable, Generator
import uuid

from risk_manager.core.config import settings
from risk_manager.observability.scrubber import scrub_trace_attributes

logger = logging.getLogger("risk_manager.observability.tracer")

# Try importing OpenTelemetry components
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, StatusCode, Tracer
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )
    from opentelemetry.sdk.resources import Resource
    _OTEL_AVAILABLE = True
except ImportError:
    trace = None
    Tracer = Any
    Span = Any
    StatusCode = None

_tracer: Any = None
_is_initialized: bool = False


class NoOpSpan:
    """Safe fallback span when OpenTelemetry is disabled or unavailable."""

    def set_attribute(self, key: str, value: Any) -> NoOpSpan:
        return self

    def set_attributes(self, attributes: dict[str, Any]) -> NoOpSpan:
        return self

    def record_exception(self, exception: BaseException) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def init_tracer() -> None:
    """Initialize OpenTelemetry TracerProvider based on configuration settings."""
    global _tracer, _is_initialized
    if _is_initialized:
        return

    if not _OTEL_AVAILABLE or not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry tracing is disabled or not installed; running in zero-overhead no-op mode.")
        _tracer = None
        _is_initialized = True
        return

    try:
        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})

        # Configure Sampler
        sample_arg = float(settings.OTEL_TRACES_SAMPLER_ARG)
        if sample_arg >= 1.0:
            sampler = ALWAYS_ON
        elif sample_arg <= 0.0:
            sampler = ALWAYS_OFF
        else:
            sampler = ParentBased(TraceIdRatioBased(sample_arg))

        provider = TracerProvider(resource=resource, sampler=sampler)

        # Configure Exporter
        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info("Configured OTLP HTTP trace exporter to %s", settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            except Exception as e:
                logger.warning("Could not initialize OTLPSpanExporter (%s); continuing with in-memory provider.", e)
        
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.OTEL_SERVICE_NAME)
        _is_initialized = True
        logger.info("OpenTelemetry distributed tracer initialized successfully.")
    except Exception as e:
        logger.warning("Failed to initialize OpenTelemetry tracer: %s. Using no-op tracer.", e)
        _tracer = None
        _is_initialized = True


def get_tracer(instrumenting_module_name: str | None = None):
    """Get active OpenTelemetry tracer or None if disabled."""
    global _tracer, _is_initialized
    if not _is_initialized:
        init_tracer()
    if _tracer and instrumenting_module_name and _OTEL_AVAILABLE and trace:
        try:
            return trace.get_tracer(instrumenting_module_name)
        except Exception:
            return _tracer
    return _tracer


def get_current_trace_id() -> str:
    """Retrieve 32-char hex string representing current trace ID, or empty string."""
    if not _OTEL_AVAILABLE or not trace:
        return ""
    try:
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except Exception:
        pass
    return ""


def get_current_span_id() -> str:
    """Retrieve 16-char hex string representing current span ID, or empty string."""
    if not _OTEL_AVAILABLE or not trace:
        return ""
    try:
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, "016x")
    except Exception:
        pass
    return ""


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Context manager for distributed trace spans with automated PII scrubbing.
    
    # ponytail: No-op fallback when disabled ensures zero latency penalty on scoring.
    """
    tracer = get_tracer()
    if tracer is None:
        yield NoOpSpan()
        return

    safe_attrs = scrub_trace_attributes(attributes or {})
    with tracer.start_as_current_span(name, attributes=safe_attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            if StatusCode:
                span.set_status(StatusCode.ERROR, str(exc))
            raise


def traced(
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable:
    """Decorator for tracing synchronous or asynchronous functions."""
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(span_name, attributes):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(span_name, attributes):
                return func(*args, **kwargs)

        import inspect
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

    return decorator
