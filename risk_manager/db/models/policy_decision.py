"""PolicyDecision entity model.

Implements TRD.md §C/D, PLAN.md T-DB-09, and ADR-012.
Append-only ledger of decision state transitions and operator manual overrides.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import Action, ActionSelector

if TYPE_CHECKING:
    from risk_manager.db.models.risk_decision import RiskDecision


class PolicyDecision(Base):
    """Append-only audit row capturing an intervention assignment or manual override."""

    __tablename__ = "policy_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("risk_decisions.id"), index=True
    )
    previous_action: Mapped[Action | None] = mapped_column(
        Enum(Action, native_enum=False), nullable=True, comment="Prior action state"
    )
    new_action: Mapped[Action] = mapped_column(
        Enum(Action, native_enum=False), comment="Effective action after transition"
    )
    selected_by: Mapped[ActionSelector] = mapped_column(
        Enum(ActionSelector, native_enum=False), comment="LINUCB, RULES, or MANUAL_OVERRIDE"
    )
    operator_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="Required for MANUAL_OVERRIDE"
    )
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Operator justification for override"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    risk_decision: Mapped["RiskDecision"] = relationship(
        "RiskDecision", back_populates="policy_decisions", lazy="selectin"
    )
