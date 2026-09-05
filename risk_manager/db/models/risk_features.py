"""RiskFeatures entity model.

Implements TRD.md §D and PLAN.md T-DB-05.
Stores a point-in-time JSON snapshot of features used for scoring.
"""

from typing import Any, TYPE_CHECKING
import uuid
from sqlalchemy import ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base

if TYPE_CHECKING:
    from risk_manager.db.models.risk_decision import RiskDecision


class RiskFeatures(Base):
    """Snapshot of the feature vector active at the moment of risk decisioning."""

    __tablename__ = "risk_features"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("risk_decisions.id"), unique=True, index=True
    )
    features: Mapped[dict[str, Any]] = mapped_column(
        JSON, comment="Complete serialized feature vector dictionary"
    )
    feature_schema_version: Mapped[str] = mapped_column(
        String(32), default="v1"
    )

    # Relationships
    risk_decision: Mapped["RiskDecision"] = relationship(
        "RiskDecision", back_populates="features", lazy="selectin"
    )
