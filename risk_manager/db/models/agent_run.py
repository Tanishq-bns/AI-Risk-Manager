"""AgentRun entity model.

Implements TRD.md §D and PLAN.md T-DB-07.
Persists asynchronous LangGraph agent investigation and verification outcomes.
"""

from datetime import datetime
from typing import Any, TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from risk_manager.db.session import Base
from risk_manager.domain.schemas.enums import AgentName, AgentRunStatus

if TYPE_CHECKING:
    from risk_manager.db.models.risk_decision import RiskDecision


class AgentRun(Base):
    """Execution trace and structured output for an asynchronous agent node."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("risk_decisions.id"), index=True
    )
    agent_name: Mapped[AgentName] = mapped_column(
        Enum(AgentName, native_enum=False), index=True
    )
    output: Mapped[dict[str, Any]] = mapped_column(
        JSON, comment="Pydantic structured output dump"
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, native_enum=False), default=AgentRunStatus.RUNNING
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    risk_decision: Mapped["RiskDecision"] = relationship(
        "RiskDecision", back_populates="agent_runs", lazy="selectin"
    )
