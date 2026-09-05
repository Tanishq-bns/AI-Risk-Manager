"""Phase 1 Foundation Smoke & Configuration Unit Tests.

Verifies:
1. The risk_manager package and core modules import cleanly.
2. Settings load correctly with zero-docker defaults matching TRD.md §Q.
3. Production environment validation enforces required secrets (T-CONFIG-02).
4. Error hierarchy correctly categorizes and formats application errors (TRD.md §R).
5. Logging initializes and redacts sensitive information.
6. System is fully functional without Docker or pre-configured secrets.
"""

import json
import logging
import pytest
from pydantic import ValidationError as PydanticValidationError

import risk_manager
from risk_manager.core.config import Settings, get_settings
from risk_manager.core.errors import (
    AppError,
    ValidationError,
    EntityNotFoundError,
    AuthorizationError,
    IdempotencyConflictError,
    PolicyViolationError,
    EconomicGuardrailError,
    ModelUnavailableError,
    InferenceTimeoutError,
    CircuitBreakerOpenError,
    CascadeExhaustedError,
    DatabaseUnavailableError,
    CacheUnavailableError,
    BrokerUnavailableError,
    AgentExecutionError,
    AgentTimeoutError,
)
from risk_manager.core.logging import JSONFormatter, get_logger, setup_logging


def test_package_import():
    """Verify that root package and metadata load properly."""
    assert risk_manager.__version__ == "0.1.0"


def test_settings_zero_docker_defaults(monkeypatch):
    """Verify Settings initializes with zero external dependencies (T-CONFIG-01)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    # Environment
    assert settings.ENVIRONMENT == "development"
    assert settings.APP_NAME == "AI Risk Manager"

    # Zero-docker database & cache defaults
    assert settings.DATABASE_URL == "sqlite+aiosqlite:///./risk_manager.db"
    assert settings.REDIS_URL is None
    assert settings.USE_IN_MEMORY_EVENT_BUS is True

    # TRD.md §Q exact threshold contracts
    assert settings.RISK_MEDIUM_THRESHOLD == 0.25
    assert settings.RISK_HIGH_THRESHOLD == 0.60
    assert settings.RISK_CRITICAL_THRESHOLD == 0.85
    assert settings.MODEL_INFERENCE_TIMEOUT_MS == 100
    assert settings.REDIS_TTL_SECONDS == 300
    assert settings.LINUCB_ALPHA == 0.25
    assert settings.MIN_INTERVENTION_EXPECTED_VALUE_INR == 100.0
    assert settings.MIN_INTERVENTION_VALUE_MULTIPLIER == 2.0
    assert settings.FEATURE_COMPLETENESS_MIN_RATIO == 0.85
    assert settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD == 5
    assert settings.CIRCUIT_BREAKER_OPEN_SECONDS == 30
    assert settings.P95_SYNC_LATENCY_TARGET_MS == 150
    assert settings.AGENT_ASYNC_TARGET_LATENCY_MS == 5000

    # No secrets required for local development
    assert settings.GEMINI_API_KEY is None
    assert settings.LANGSMITH_API_KEY is None


def test_singleton_get_settings():
    """Verify cached get_settings returns the same instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_production_environment_validation(monkeypatch):
    """Verify startup validation fails if required production variables are missing (T-CONFIG-02)."""
    # Missing GEMINI_API_KEY and using SQLite in production must raise validation error
    with pytest.raises(PydanticValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            GEMINI_API_KEY=None,
        )
    errors = str(exc_info.value)
    assert "GEMINI_API_KEY must be set in production environment" in errors
    assert "SQLite is not permitted in production" in errors

    # Valid production settings pass validation
    prod_settings = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/prod_db",
        REDIS_URL="redis://localhost:6379/0",
        GEMINI_API_KEY="valid-secret-key",
    )
    assert prod_settings.ENVIRONMENT == "production"
    assert prod_settings.DATABASE_URL.startswith("postgresql")


def test_error_hierarchy():
    """Verify application error taxonomy mappings, status codes, and serialization."""
    # Validation error
    val_err = ValidationError("Field missing", details={"field": "order_id"})
    assert isinstance(val_err, AppError)
    assert val_err.status_code == 400
    assert val_err.code == "VALIDATION_ERROR"
    assert val_err.to_dict()["error"]["details"]["field"] == "order_id"

    # Entity not found
    not_found = EntityNotFoundError("Decision", "d-123")
    assert not_found.status_code == 404
    assert not_found.code == "ENTITY_NOT_FOUND"

    # Policy violation
    pol_err = PolicyViolationError(action="A3", allowed_actions=["A0", "A1"])
    assert pol_err.status_code == 400
    assert pol_err.code == "POLICY_VIOLATION"

    # Circuit breaker open
    cb_err = CircuitBreakerOpenError(failures=5, open_seconds=30)
    assert cb_err.status_code == 500
    assert cb_err.code == "CIRCUIT_BREAKER_OPEN"

    # Dependency error
    dep_err = DatabaseUnavailableError("Connection dropped")
    assert dep_err.status_code == 503
    assert dep_err.code == "DEPENDENCY_UNAVAILABLE"


def test_logging_initialization_and_redaction():
    """Verify structured logger formatting, custom context, and sensitive key redaction."""
    setup_logging(level="DEBUG", json_format=True)
    logger = get_logger("test.foundation")
    assert logger.name == "test.foundation"

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test event logged",
        args=(),
        exc_info=None,
    )
    # Inject context with a sensitive key
    record.api_key = "sensitive-super-secret-token"
    record.correlation_id = "corr-xyz-123"

    formatted_json = formatter.format(record)
    parsed = json.loads(formatted_json)

    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Test event logged"
    assert parsed["context"]["correlation_id"] == "corr-xyz-123"
    # Ensure api_key was redacted
    assert parsed["context"]["api_key"] == "[REDACTED]"
