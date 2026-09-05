"""ModelVersion entity model.

Implements TRD.md §D and PLAN.md T-DB-08.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import ModelApprovalStatus, ScoringSource

if TYPE_CHECKING:
    from risk_manager.db.models.risk_decision import RiskDecision


class ModelVersion(Base):
    """Registry mirror tracking active and historical model promotions."""

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    mlflow_run_id: Mapped[str] = mapped_column(
        String(128), index=True, comment="Tracking run identifier or artifact hash"
    )
    model_type: Mapped[ScoringSource] = mapped_column(
        Enum(ScoringSource, native_enum=False), index=True
    )
    approval_status: Mapped[ModelApprovalStatus] = mapped_column(
        Enum(ModelApprovalStatus, native_enum=False), default=ModelApprovalStatus.PENDING
    )
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    risk_decisions: Mapped[list["RiskDecision"]] = relationship(
        "RiskDecision", back_populates="model_version", lazy="selectin"
    )
