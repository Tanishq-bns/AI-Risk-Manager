"""ReturnRequest entity model.

Implements TRD.md §D and PLAN.md T-DB-03.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, Enum, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import ReturnRequestStatus

if TYPE_CHECKING:
    from risk_manager.db.models.order import Order
    from risk_manager.db.models.risk_decision import RiskDecision


class ReturnRequest(Base):
    """Customer-initiated return request entity."""

    __tablename__ = "return_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("orders.id"), index=True
    )
    return_reason: Mapped[str] = mapped_column(
        Text, comment="Customer-provided free text return rationale"
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[ReturnRequestStatus] = mapped_column(
        Enum(ReturnRequestStatus, native_enum=False), default=ReturnRequestStatus.PENDING
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="return_requests", lazy="selectin")
    risk_decisions: Mapped[list["RiskDecision"]] = relationship(
        "RiskDecision", back_populates="return_request", cascade="all, delete-orphan", lazy="selectin"
    )
