"""RiskDecision entity model.

Implements TRD.md §C/D and PLAN.md T-DB-04.
Maintains an immutable historical record of the original automated scoring decision.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import RiskBand, ScoringSource

if TYPE_CHECKING:
    from risk_manager.db.models.agent_run import AgentRun
    from risk_manager.db.models.intervention import Intervention
    from risk_manager.db.models.model_version import ModelVersion
    from risk_manager.db.models.policy_decision import PolicyDecision
    from risk_manager.db.models.return_request import ReturnRequest
    from risk_manager.db.models.risk_features import RiskFeatures


class RiskDecision(Base):
    """Immutable record of an automated return risk scoring event."""

    __tablename__ = "risk_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    return_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("return_requests.id"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, comment="Client deduplication token"
    )
    p_return_abuse: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), comment="Calibrated abuse probability (0.0000 - 1.0000)"
    )
    risk_band: Mapped[RiskBand] = mapped_column(
        Enum(RiskBand, native_enum=False), index=True
    )
    scoring_source: Mapped[ScoringSource] = mapped_column(
        Enum(ScoringSource, native_enum=False)
    )
    fallback_tier: Mapped[int] = mapped_column(
        SmallInteger, comment="0=Primary, 1=IsolationForest, 2=Rules"
    )
    fallback_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("model_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    return_request: Mapped["ReturnRequest"] = relationship(
        "ReturnRequest", back_populates="risk_decisions", lazy="selectin"
    )
    model_version: Mapped["ModelVersion | None"] = relationship(
        "ModelVersion", back_populates="risk_decisions", lazy="selectin"
    )
    features: Mapped["RiskFeatures | None"] = relationship(
        "RiskFeatures", back_populates="risk_decision", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    interventions: Mapped[list["Intervention"]] = relationship(
        "Intervention", back_populates="risk_decision", cascade="all, delete-orphan", lazy="selectin"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun", back_populates="risk_decision", cascade="all, delete-orphan", lazy="selectin"
    )
    policy_decisions: Mapped[list["PolicyDecision"]] = relationship(
        "PolicyDecision", back_populates="risk_decision", cascade="all, delete-orphan", lazy="selectin"
    )
