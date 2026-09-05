"""Domain schemas and Pydantic DTOs."""

from risk_manager.domain.schemas.agents import (
    ActionDecision,
    AgentVerificationResult,
    AgentWorkflowResult,
    InvestigationResult,
    VerificationResult,
)
from risk_manager.domain.schemas.enums import (
    Action,
    ActionSelector,
    AgentFallbackReason,
    AgentName,
    AgentProvider,
    AgentRunStatus,
    EvidenceQuality,
    FallbackTier,
    ModelApprovalStatus,
    PaymentMethod,
    PersistenceStatus,
    RiskBand,
    ReturnRequestStatus,
    ScoringSource,
    VerifierRecommendation,
)
from risk_manager.domain.schemas.events import (
    CheckoutEvent,
    EventEnvelope,
    ReturnRequestEvent,
)
from risk_manager.domain.schemas.override import (
    ManualOverrideRequest,
    ManualOverrideResponse,
)
from risk_manager.domain.schemas.requests import RiskScoreRequest
from risk_manager.domain.schemas.responses import (
    EconomicPrediction,
    FallbackMetadata,
    InterventionCandidate,
    ModelMetadata,
    PolicyDecision,
    RiskEvidence,
    RiskScoreResponse,
)

__all__ = [
    # Enums
    "Action",
    "ActionSelector",
    "AgentFallbackReason",
    "AgentName",
    "AgentProvider",
    "AgentRunStatus",
    "EvidenceQuality",
    "FallbackTier",
    "ModelApprovalStatus",
    "PaymentMethod",
    "PersistenceStatus",
    "RiskBand",
    "ReturnRequestStatus",
    "ScoringSource",
    "VerifierRecommendation",
    # Events
    "EventEnvelope",
    "CheckoutEvent",
    "ReturnRequestEvent",
    # Requests
    "RiskScoreRequest",
    # Responses
    "RiskEvidence",
    "ModelMetadata",
    "FallbackMetadata",
    "EconomicPrediction",
    "InterventionCandidate",
    "PolicyDecision",
    "RiskScoreResponse",
    # Agents
    "InvestigationResult",
    "VerificationResult",
    "ActionDecision",
    "AgentVerificationResult",
    "AgentWorkflowResult",
    # Override
    "ManualOverrideRequest",
    "ManualOverrideResponse",
]
