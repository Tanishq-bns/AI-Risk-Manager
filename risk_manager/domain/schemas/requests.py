"""Request DTOs for scoring and decision endpoints.

Implements TRD.md §E and PLAN.md T-SCHEMA-02.
"""

import uuid
from uuid import UUID
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import PaymentMethod


class RiskScoreRequest(BaseModel):
    """Synchronous scoring request payload for POST /v1/risk/score."""

    return_request_id: UUID = Field(default_factory=uuid.uuid4, description="Unique return request ID")
    order_id: UUID = Field(default_factory=uuid.uuid4, description="Associated order ID")
    customer_id_hash: str = Field(min_length=1, description="Pseudonymous customer hash")
    idempotency_key: str = Field(min_length=1, description="Unique client idempotency token")

    # Optional inline context to support real-time evaluation without pre-seeding (C-3 audit resolution)
    order_value: float | None = Field(default=None, gt=0, description="Order value if not already in DB")
    payment_method: PaymentMethod | None = None
    cod_flag: bool | None = None
    return_reason: str | None = None
    product_category: str | None = None

    # Granular behavioral simulation fields for real-time simulator (all optional)
    days_since_purchase: int | None = Field(default=None, ge=0)
    customer_order_count: int | None = Field(default=None, ge=0)
    customer_return_count: int | None = Field(default=None, ge=0)
    customer_return_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    prior_return_value: float | None = Field(default=None, ge=0.0)
    prior_return_frequency: float | None = Field(default=None, ge=0.0)
    item_category_return_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    delivery_distance_bucket: str | None = None
    reverse_logistics_cost: float | None = Field(default=None, ge=0.0)
    estimated_item_recovery_value: float | None = Field(default=None, ge=0.0)
    historical_abuse_signal: float | None = Field(default=None, ge=0.0, le=1.0)

