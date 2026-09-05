"""Application configuration using Pydantic Settings.

Implements T-CONFIG-01 and T-CONFIG-02 per PLAN.md / TRD.md §Q.
Supports zero-docker local execution with sensible defaults while enforcing
strict validation when ENVIRONMENT=production.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --------------------------------------------------------------------------
    # Environment & Application Metadata
    # --------------------------------------------------------------------------
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    APP_NAME: str = "AI Risk Manager"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --------------------------------------------------------------------------
    # Database Configuration (PostgreSQL / SQLite fallback)
    # Default to async SQLite for zero-docker local development.
    # --------------------------------------------------------------------------
    DATABASE_URL: str = "sqlite+aiosqlite:///./risk_manager.db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --------------------------------------------------------------------------
    # Redis & Caching Configuration
    # --------------------------------------------------------------------------
    REDIS_URL: str | None = None  # None = use in-process LRU cache directly
    REDIS_TTL_SECONDS: int = 300
    LRU_CACHE_MAX_SIZE: int = 10_000

    # --------------------------------------------------------------------------
    # Event Bus / Redpanda Configuration
    # --------------------------------------------------------------------------
    REDPANDA_BROKERS: str = "localhost:19092"
    USE_IN_MEMORY_EVENT_BUS: bool = True  # Fallback when Redpanda broker is absent
    EVENT_TOPIC_CHECKOUT: str = "checkout.events.v1"
    EVENT_TOPIC_RETURN: str = "return.events.v1"
    EVENT_TOPIC_RISK_DECISIONS: str = "risk.decisions.v1"
    EVENT_TOPIC_INTERVENTIONS: str = "interventions.decisions.v1"
    EVENT_TOPIC_AUDIT: str = "risk.audit.v1"
    EVENT_TOPIC_MODEL: str = "model.events.v1"

    # --------------------------------------------------------------------------
    # Machine Learning & Model Registry
    # --------------------------------------------------------------------------
    ML_MODELS_DIR: Path = Path("models")
    MODEL_INFERENCE_TIMEOUT_MS: int = 100
    FEATURE_COMPLETENESS_MIN_RATIO: float = 0.85
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_OPEN_SECONDS: int = 30
    LINUCB_ALPHA: float = 0.25

    # --------------------------------------------------------------------------
    # Risk Bands & Economic Thresholds (TRD.md §Q)
    # --------------------------------------------------------------------------
    RISK_MEDIUM_THRESHOLD: float = 0.25
    RISK_HIGH_THRESHOLD: float = 0.60
    RISK_CRITICAL_THRESHOLD: float = 0.85
    MIN_INTERVENTION_EXPECTED_VALUE_INR: float = 100.0
    MIN_INTERVENTION_VALUE_MULTIPLIER: float = 2.0
    P95_SYNC_LATENCY_TARGET_MS: int = 150

    # --------------------------------------------------------------------------
    # Gemini / Agentic AI Configuration
    # --------------------------------------------------------------------------
    AGENTS_ENABLED: bool = True
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    AGENT_ASYNC_TARGET_LATENCY_MS: int = 5000
    AGENT_TIMEOUT_MS: int = 15000
    AGENT_TOTAL_TIMEOUT_MS: int = 60000
    AGENT_MAX_RETRIES: int = 2
    AGENT_TEMPERATURE: float = 0.1

    # --------------------------------------------------------------------------
    # LangSmith & Tracing Configuration (Optional)
    # --------------------------------------------------------------------------
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_PROJECT: str = "ai-risk-manager"
    LANGSMITH_TRACING: bool = False

    # --------------------------------------------------------------------------
    # Observability, Distributed Tracing & Prometheus Metrics (Phase 8)
    # --------------------------------------------------------------------------
    PROMETHEUS_METRICS_ENABLED: bool = True
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "ai-risk-manager"
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "http/protobuf"
    OTEL_TRACES_SAMPLER: str = "parentbased_traceidratio"
    OTEL_TRACES_SAMPLER_ARG: float = 1.0
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = True

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Settings":
        """Enforce strict configuration rules for production environments (T-CONFIG-02)."""
        if self.ENVIRONMENT == "production":
            errors: list[str] = []
            if not self.GEMINI_API_KEY or not self.GEMINI_API_KEY.strip():
                errors.append("GEMINI_API_KEY must be set in production environment")
            if self.DATABASE_URL.startswith("sqlite"):
                errors.append("SQLite is not permitted in production; set a PostgreSQL DATABASE_URL")
            if not self.REDIS_URL:
                errors.append("REDIS_URL must be configured in production environment")
            if errors:
                raise ValueError("; ".join(errors))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton getter for application settings."""
    return Settings()


# Exported singleton instance
settings: Settings = get_settings()
