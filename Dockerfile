# ==============================================================================
# AI Risk Manager — Multi-Stage Production Dockerfile (Phase 8 Optional Deployment)
# ==============================================================================

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install ".[all]" && \
    pip install prometheus-client opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi

# Copy application source, models, static dashboard assets, and documentation
COPY risk_manager /app/risk_manager
COPY models /app/models
COPY docs /app/docs
COPY README.md /app/README.md

# Non-root security user
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "risk_manager.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
