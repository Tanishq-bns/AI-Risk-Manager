"""Application error hierarchy.

Implements TRD.md §R (Error Taxonomy).
Provides structured, categorized exceptions with HTTP status mappings,
error codes, and optional payload details for API and audit logging.
"""

from typing import Any


class AppError(Exception):
    """Base exception for all AI Risk Manager errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to a dictionary suitable for API responses and logs."""
        payload: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


# ------------------------------------------------------------------------------
# Request & Validation Errors (HTTP 4xx)
# ------------------------------------------------------------------------------
class ValidationError(AppError):
    """Raised when an incoming request or payload fails schema constraints."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="VALIDATION_ERROR", status_code=400, details=details)


class EntityNotFoundError(AppError):
    """Raised when an entity (decision, order, return request) cannot be found."""

    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity} with ID '{entity_id}' was not found.",
            code="ENTITY_NOT_FOUND",
            status_code=404,
            details={"entity": entity, "entity_id": entity_id},
        )


class AuthorizationError(AppError):
    """Raised when an operator role lacks required permission."""

    def __init__(self, message: str = "Unauthorized operation") -> None:
        super().__init__(message=message, code="AUTHORIZATION_ERROR", status_code=403)


class IdempotencyConflictError(AppError):
    """Raised when an idempotency key is reused with a conflicting payload."""

    def __init__(self, key: str) -> None:
        super().__init__(
            message=f"Idempotency key '{key}' already exists with a different payload.",
            code="IDEMPOTENCY_CONFLICT",
            status_code=409,
            details={"idempotency_key": key},
        )


# ------------------------------------------------------------------------------
# Policy & Economic Guardrail Errors
# ------------------------------------------------------------------------------
class PolicyError(AppError):
    """Base exception for decision policy violations."""

    def __init__(self, message: str, code: str = "POLICY_ERROR", status_code: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=status_code, details=details)


class PolicyViolationError(PolicyError):
    """Raised when an intervention selection violates merchant-configured allowed actions."""

    def __init__(self, action: str, allowed_actions: list[str]) -> None:
        super().__init__(
            message=f"Action '{action}' is not in merchant allowed actions: {allowed_actions}",
            code="POLICY_VIOLATION",
            details={"action": action, "allowed_actions": allowed_actions},
        )


class EconomicGuardrailError(PolicyError):
    """Raised when an intervention violates expected net value guardrails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="ECONOMIC_GUARDRAIL_VIOLATION", details=details)


# ------------------------------------------------------------------------------
# Machine Learning & Cascade Scoring Errors
# ------------------------------------------------------------------------------
class ModelError(AppError):
    """Base exception for ML inference and model artifact operations."""

    def __init__(self, message: str, code: str = "MODEL_ERROR", status_code: int = 500, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=status_code, details=details)


class ModelUnavailableError(ModelError):
    """Raised when a model artifact cannot be loaded or executed."""

    def __init__(self, model_name: str, reason: str) -> None:
        super().__init__(
            message=f"Model '{model_name}' is unavailable: {reason}",
            code="MODEL_UNAVAILABLE",
            details={"model_name": model_name, "reason": reason},
        )


class InferenceTimeoutError(ModelError):
    """Raised when model scoring exceeds the latency budget."""

    def __init__(self, model_name: str, timeout_ms: int) -> None:
        super().__init__(
            message=f"Model '{model_name}' inference timed out after {timeout_ms} ms.",
            code="INFERENCE_TIMEOUT",
            details={"model_name": model_name, "timeout_ms": timeout_ms},
        )


class FeatureSchemaMismatchError(ModelError):
    """Raised when feature vector schema differs from model signature."""

    def __init__(self, expected_schema: str, actual_schema: str) -> None:
        super().__init__(
            message="Feature vector schema does not match model signature.",
            code="FEATURE_SCHEMA_MISMATCH",
            details={"expected": expected_schema, "actual": actual_schema},
        )


class InsufficientFeaturesError(ModelError):
    """Raised when feature completeness ratio falls below threshold."""

    def __init__(self, completeness_ratio: float, min_ratio: float) -> None:
        super().__init__(
            message=f"Feature completeness {completeness_ratio:.2f} is below minimum {min_ratio:.2f}.",
            code="INSUFFICIENT_FEATURES",
            details={"completeness_ratio": completeness_ratio, "min_ratio": min_ratio},
        )


class CascadeError(AppError):
    """Base exception for scoring cascade orchestration."""

    def __init__(self, message: str, code: str = "CASCADE_ERROR", details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)


class CircuitBreakerOpenError(CascadeError):
    """Raised when the circuit breaker for Tier 0 is open due to consecutive failures."""

    def __init__(self, failures: int, open_seconds: int) -> None:
        super().__init__(
            message=f"Circuit breaker is OPEN ({failures} consecutive failures). Bypassing Tier 0 for {open_seconds}s.",
            code="CIRCUIT_BREAKER_OPEN",
            details={"consecutive_failures": failures, "open_seconds": open_seconds},
        )


class CascadeExhaustedError(CascadeError):
    """Raised when all tiers (Tier 0, 1, 2) in the cascade fail."""

    def __init__(self, message: str = "All scoring tiers in the fallback cascade failed.") -> None:
        super().__init__(message=message, code="CASCADE_EXHAUSTED")


# ------------------------------------------------------------------------------
# Infrastructure & Dependency Errors
# ------------------------------------------------------------------------------
class DependencyError(AppError):
    """Base exception for external infrastructure dependency failures."""

    def __init__(self, dependency: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=f"Dependency '{dependency}' failure: {message}",
            code="DEPENDENCY_UNAVAILABLE",
            status_code=503,
            details={"dependency": dependency, **(details or {})},
        )


class DatabaseUnavailableError(DependencyError):
    """Raised when PostgreSQL/SQLite cannot be reached."""

    def __init__(self, message: str = "Database connection refused") -> None:
        super().__init__(dependency="Database", message=message)


class CacheUnavailableError(DependencyError):
    """Raised when Redis cannot be reached."""

    def __init__(self, message: str = "Redis connection refused") -> None:
        super().__init__(dependency="Redis", message=message)


class BrokerUnavailableError(DependencyError):
    """Raised when Redpanda/Kafka broker cannot be reached."""

    def __init__(self, message: str = "Redpanda broker unreachable") -> None:
        super().__init__(dependency="Redpanda", message=message)


class PersistenceError(AppError):
    """Raised when database write/query fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="PERSISTENCE_ERROR", status_code=500, details=details)


# ------------------------------------------------------------------------------
# Agentic Subsystem Errors
# ------------------------------------------------------------------------------
class AgentExecutionError(AppError):
    """Base exception for LangGraph / LLM agent execution failures."""

    def __init__(self, agent_name: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=f"Agent '{agent_name}' error: {message}",
            code="AGENT_EXECUTION_ERROR",
            status_code=500,
            details={"agent_name": agent_name, **(details or {})},
        )


class AgentTimeoutError(AgentExecutionError):
    """Raised when agent graph execution exceeds the async target latency."""

    def __init__(self, agent_name: str, timeout_ms: int) -> None:
        super().__init__(
            agent_name=agent_name,
            message=f"Execution timed out after {timeout_ms} ms.",
            details={"timeout_ms": timeout_ms},
        )
