"""Order entity model.

Implements TRD.md §D and PLAN.md T-DB-02.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import PaymentMethod

if TYPE_CHECKING:
    from risk_manager.db.models.customer import Customer
    from risk_manager.db.models.return_request import ReturnRequest


class Order(Base):
    """Historical and active order transactions."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    customer_id_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.customer_id_hash"), index=True
    )
    order_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), comment="Gross order amount in INR"
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False), default=PaymentMethod.PREPAID
    )
    cod_flag: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="True if Cash On Delivery"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders", lazy="selectin")
    return_requests: Mapped[list["ReturnRequest"]] = relationship(
        "ReturnRequest", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
