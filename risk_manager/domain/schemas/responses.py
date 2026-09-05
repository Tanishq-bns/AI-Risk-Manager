"""Response DTOs for scoring, decisions, and audit inspection.

Implements TRD.md §E and PLAN.md T-SCHEMA-03.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import (
    Action,
    ActionSelector,
    PersistenceStatus,
    RiskBand,
    ScoringSource,
)


class RiskEvidence(BaseModel):
    """Top feature signals and completeness diagnostics (TRD.md §E)."""

    top_signals: list[str] = Field(default_factory=list, description="Dominant risk/protective factors")
    feature_completeness: float = Field(ge=0, le=1, description="Ratio of non-null required features")


class ModelMetadata(BaseModel):
    """Model provenance information for the decision (TRD.md §E)."""

    model_version: str
    model_type: ScoringSource
    trained_at: datetime | None = None


class FallbackMetadata(BaseModel):
    """Cascade degradation details (TRD.md §E)."""

    fallback_tier: int = Field(ge=0, le=2, description="0=Primary ML, 1=Isolation Forest, 2=Rules")
    fallback_reason: str | None = Field(default=None, description="Null when Tier 0 succeeded")


class EconomicPrediction(BaseModel):
    """Economic loss and recoverable margin estimates (TRD.md §E)."""

    expected_loss_no_action: float = Field(description="Projected loss if no friction applied (INR)")
    expected_loss_with_action: float = Field(description="Projected loss under selected intervention (INR)")
    expected_net_value: float = Field(description="ExpectedNetValue = Loss(no_action) - Loss(action)")


class InterventionCandidate(BaseModel):
    """Intervention chosen by policy engine or fallback rules (TRD.md §E)."""

    action: Action
    selected_by: ActionSelector
    rationale: str


class PolicyDecision(BaseModel):
    """Historical state transition record for policy selection or override (TRD.md §E)."""

    previous_action: Action | None = None
    new_action: Action
    selected_by: ActionSelector
    operator_id: str | None = None
    reason: str | None = None
    created_at: datetime


class RiskScoreResponse(BaseModel):
    """Authoritative response payload from POST /v1/risk/score (TRD.md §E)."""

    decision_id: UUID
    p_return_abuse: float = Field(ge=0, le=1, description="Calibrated abuse probability")
    risk_band: RiskBand
    model_metadata: ModelMetadata
    fallback_metadata: FallbackMetadata
    economic_prediction: EconomicPrediction
    intervention: InterventionCandidate
    evidence: RiskEvidence
    latency_ms: float = Field(ge=0, description="Synchronous decision processing duration in ms")
    persistence_status: PersistenceStatus
