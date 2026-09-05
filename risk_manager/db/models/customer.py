"""Customer entity model.

Implements TRD.md §D and PLAN.md T-DB-01.
Stores pseudonymous customer identifier only; zero raw PII.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base

if TYPE_CHECKING:
    from risk_manager.db.models.order import Order


class Customer(Base):
    """Pseudonymous customer identity."""

    __tablename__ = "customers"

    customer_id_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True, index=True, comment="SHA-256 customer hash"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="customer", cascade="all, delete-orphan", lazy="selectin"
    )
