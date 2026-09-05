"""Manual override request and response DTOs.

Implements TRD.md §E and PLAN.md T-SCHEMA-05.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import Action


class ManualOverrideRequest(BaseModel):
    """Operator request payload for POST /v1/risk/decisions/{id}/override."""

    operator_id: str = Field(min_length=1, description="Identity of the reviewing operator")
    reason: str = Field(min_length=1, description="Mandatory rationale for changing decision")
    new_action: Action = Field(description="New target action (A0-A4)")


class ManualOverrideResponse(BaseModel):
    """Audit response payload confirming manual override state transition."""

    decision_id: UUID
    previous_action: Action
    new_action: Action
    overridden_at: datetime
    audit_event_id: UUID
