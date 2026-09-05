"""Intervention entity model.

Implements TRD.md §D and PLAN.md T-DB-06.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import Action, ActionSelector

if TYPE_CHECKING:
    from risk_manager.db.models.risk_decision import RiskDecision


class Intervention(Base):
    """Selected intervention resulting from risk evaluation and policy engine."""

    __tablename__ = "interventions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("risk_decisions.id"), index=True
    )
    action: Mapped[Action] = mapped_column(
        Enum(Action, native_enum=False), index=True
    )
    expected_net_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), comment="Expected net economic value in INR"
    )
    selected_by: Mapped[ActionSelector] = mapped_column(
        Enum(ActionSelector, native_enum=False)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    risk_decision: Mapped["RiskDecision"] = relationship(
        "RiskDecision", back_populates="interventions", lazy="selectin"
    )
