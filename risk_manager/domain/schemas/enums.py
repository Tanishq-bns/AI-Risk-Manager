"""Authoritative domain enumerations.

Implements TRD.md §A-E and SPEC.md §18.
Uses StrEnum to guarantee zero-copy string interoperability between
Pydantic v2 schemas and SQLAlchemy 2.0 ORM models.
"""

from enum import Enum, IntEnum, StrEnum


class Action(StrEnum):
    """Intervention actions (PRD.md §5).

    A0: ZERO_FRICTION_APPROVAL - Approve return immediately with zero added friction.
    A1: DYNAMIC_RETURN_FEE - Apply risk-sized reverse pickup fee.
    A2: OTP_DOORSTEP_INSPECTION - Require physical verification/OTP at doorstep pickup.
    A3: STORE_CREDIT - Offer store credit instead of cash refund where policy allows.
    A4: MANUAL_REVIEW - Escalate case to human risk operator review queue.
    """

    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"

    @property
    def label(self) -> str:
        """Human-readable action name."""
        labels = {
            "A0": "ZERO_FRICTION_APPROVAL",
            "A1": "DYNAMIC_RETURN_FEE",
            "A2": "OTP_DOORSTEP_INSPECTION",
            "A3": "STORE_CREDIT",
            "A4": "MANUAL_REVIEW",
        }
        return labels[self.value]


class RiskBand(StrEnum):
    """Calibrated risk probability bands (SPEC.md §18)."""

    LOW = "LOW"            # 0.00 <= p < 0.25
    MEDIUM = "MEDIUM"      # 0.25 <= p < 0.60
    HIGH = "HIGH"          # 0.60 <= p < 0.85
    CRITICAL = "CRITICAL"  # 0.85 <= p <= 1.00


class ScoringSource(StrEnum):
    """Active scoring model tier (TRD.md §C)."""

    XGBOOST = "XGBOOST"
    ISOLATION_FOREST = "ISOLATION_FOREST"
    RULES = "RULES"


class FallbackTier(IntEnum):
    """Fallback cascade tier levels (TRD.md §K)."""

    TIER_0 = 0  # Primary XGBoost + Isotonic Calibrator
    TIER_1 = 1  # Isolation Forest anomaly proxy
    TIER_2 = 2  # Deterministic conservative rules engine


class PersistenceStatus(StrEnum):
    """Persistence outcome status for synchronous responses (TRD.md §E)."""

    PERSISTED = "PERSISTED"
    DEFERRED = "DEFERRED"


class ReturnRequestStatus(StrEnum):
    """Lifecycle status of a return request (TRD.md §D)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class PaymentMethod(StrEnum):
    """Order payment classification (TRD.md §E)."""

    PREPAID = "PREPAID"
    COD = "COD"


class ActionSelector(StrEnum):
    """Mechanism responsible for selecting the intervention (TRD.md §C)."""

    LINUCB = "LINUCB"
    RULES = "RULES"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class AgentName(StrEnum):
    """LangGraph agent identifiers (TRD.md §M)."""

    INVESTIGATOR = "INVESTIGATOR"
    VERIFIER = "VERIFIER"
    ACTION_ORCHESTRATOR = "ACTION_ORCHESTRATOR"


class AgentRunStatus(StrEnum):
    """Execution status of an asynchronous agent run (TRD.md §D)."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


class ModelApprovalStatus(StrEnum):
    """Model registry promotion status (TRD.md §D)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class EvidenceQuality(StrEnum):
    """Investigator assessment of evidence strength (TRD.md §M)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerifierRecommendation(StrEnum):
    """Verifier agent recommendation outcome (TRD.md §M)."""

    CONFIRM = "CONFIRM"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AgentProvider(StrEnum):
    """Execution provider for agent nodes."""

    GEMINI = "GEMINI"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"


class AgentFallbackReason(StrEnum):
    """Explicit cause for deterministic fallback activation."""

    API_KEY_MISSING = "API_KEY_MISSING"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    AGENTS_DISABLED = "AGENTS_DISABLED"
    OTHER = "OTHER"
