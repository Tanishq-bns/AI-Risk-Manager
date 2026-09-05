"""Event envelope and streaming event schemas.

Implements TRD.md §E/F and PLAN.md T-SCHEMA-01.
"""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import PaymentMethod

PayloadT = TypeVar("PayloadT")


class EventEnvelope(BaseModel, Generic[PayloadT]):
    """Generic event envelope shared by all Redpanda / streaming topics (TRD.md §F)."""

    event_id: UUID
    event_type: str
    event_version: str = "v1"
    occurred_at: datetime
    producer: str
    correlation_id: str
    entity_id: str
    payload: PayloadT


class CheckoutEvent(BaseModel):
    """Event emitted when an order is placed at checkout (TRD.md §E)."""

    order_id: UUID
    customer_id_hash: str
    order_value: float = Field(gt=0, description="Gross order value in INR")
    payment_method: PaymentMethod
    cod_flag: bool
    occurred_at: datetime


class ReturnRequestEvent(BaseModel):
    """Event emitted when a return request is initiated by a customer (TRD.md §E)."""

    return_request_id: UUID
    order_id: UUID
    return_reason: str
    requested_at: datetime
