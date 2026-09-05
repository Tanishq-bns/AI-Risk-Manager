"""AuditEvent entity model.

Implements TRD.md §D and PLAN.md T-DB-10.
Append-only log of every system and domain event envelope.
"""

from datetime import datetime
from typing import Any
import uuid
from sqlalchemy import DateTime, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from risk_manager.db.session import Base


class AuditEvent(Base):
    """Immutable audit trail of published event envelopes."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, index=True, comment="Unique event identifier from envelope"
    )
    event_type: Mapped[str] = mapped_column(
        String(64), index=True, comment="Envelope event_type"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, comment="Full serialized event envelope dictionary"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
