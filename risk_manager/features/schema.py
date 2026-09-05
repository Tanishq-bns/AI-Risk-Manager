"""Strongly typed feature schema and outcome label definitions.

Implements TRD.md §H and PLAN.md T-FE-01.
Guarantees strict separation between decision-time inputs (FeatureVector)
and post-outcome labels (OutcomeLabel) with zero field overlap.
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

from risk_manager.domain.schemas.enums import PaymentMethod


class FeatureVector(BaseModel):
    """The 17 decision-time features available at the moment of risk scoring (TRD.md §H).

    Strict point-in-time guarantee: every field must reflect only information
    known strictly prior to or at the return request timestamp.
    """

    # 1. Pseudonymous customer identity
    customer_id_hash: str = Field(min_length=1, description="SHA-256 pseudonymous customer identifier")

    # 2. Order characteristics
    order_value: float = Field(gt=0, description="Gross value of the order being returned in INR")
    product_category: str = Field(min_length=1, description="Product category enum/string (e.g. APPAREL, ELECTRONICS)")
    payment_method: PaymentMethod = Field(description="PREPAID or COD")
    cod_flag: bool = Field(description="True if order was Cash On Delivery")

    # 3. Pre-decision customer behavioral aggregates (strictly before this return)
    customer_order_count: int = Field(ge=0, description="Total historical orders prior to this return request")
    customer_return_count: int = Field(ge=0, description="Total historical returns prior to this return request")
    customer_return_rate: float = Field(
        ge=0.0, le=1.0, description="customer_return_count / customer_order_count (0.0 if orders == 0)"
    )

    # 4. Return timing and frequency
    days_since_purchase: int = Field(ge=0, description="Elapsed days between order date and return request date")
    prior_return_value: float = Field(ge=0.0, description="Cumulative INR value of prior returns by this customer")
    prior_return_frequency: float = Field(
        ge=0.0, description="Returns per 30-day window over customer's active history"
    )

    # 5. Category and delivery logistics context
    item_category_return_rate: float = Field(
        ge=0.0, le=1.0, description="Historical category-wide baseline return rate"
    )
    return_reason: str = Field(description="Free-text customer return justification")
    delivery_distance_bucket: str = Field(
        description="Courier transit zone: LOCAL, REGIONAL, or NATIONAL"
    )
    reverse_logistics_cost: float = Field(
        ge=0.0, description="Estimated merchant cost to process reverse courier shipping"
    )
    estimated_item_recovery_value: float = Field(
        ge=0.0, description="Projected resale or restock recovery value if undamaged"
    )

    # 6. Prior risk signal & metadata
    historical_abuse_signal: float = Field(
        ge=0.0, le=1.0, description="Historical risk flag score strictly preceding this decision"
    )
    feature_schema_version: str = Field(default="v1", description="Schema version identifier")

    @classmethod
    def model_feature_names(cls) -> list[str]:
        """Ordered list of numeric/tabular feature columns consumed by ML models.

        Contains 16 predictive features (all 17 documented FeatureVector features
        excluding the pseudonymous identifier customer_id_hash).
        """
        return [
            "order_value",
            "cod_flag",
            "customer_order_count",
            "customer_return_count",
            "customer_return_rate",
            "days_since_purchase",
            "prior_return_value",
            "prior_return_frequency",
            "item_category_return_rate",
            "reverse_logistics_cost",
            "estimated_item_recovery_value",
            "historical_abuse_signal",
            "product_category",
            "payment_method",
            "delivery_distance_bucket",
            "return_reason",
        ]

    def to_model_features(self) -> dict[str, Any]:
        """Extract dictionary of model-consumable features (excluding pseudonymous identifier)."""
        return {
            "order_value": self.order_value,
            "cod_flag": 1 if self.cod_flag else 0,
            "customer_order_count": self.customer_order_count,
            "customer_return_count": self.customer_return_count,
            "customer_return_rate": self.customer_return_rate,
            "days_since_purchase": self.days_since_purchase,
            "prior_return_value": self.prior_return_value,
            "prior_return_frequency": self.prior_return_frequency,
            "item_category_return_rate": self.item_category_return_rate,
            "reverse_logistics_cost": self.reverse_logistics_cost,
            "estimated_item_recovery_value": self.estimated_item_recovery_value,
            "historical_abuse_signal": self.historical_abuse_signal,
            "product_category": self.product_category,
            "payment_method": self.payment_method.value if hasattr(self.payment_method, "value") else str(self.payment_method),
            "delivery_distance_bucket": self.delivery_distance_bucket,
            "return_reason": self.return_reason,
        }


class OutcomeLabel(BaseModel):
    """Post-outcome ground-truth labels (TRD.md §H).

    Available only AFTER inspection and resolution.
    Strictly forbidden from being included in FeatureVector.
    """

    confirmed_abuse: bool = Field(description="True if return was verified as abusive/fraudulent")
    actual_loss: float = Field(ge=0.0, description="Realized financial loss in INR")
    refund_completed_at: datetime | None = Field(
        default=None, description="Timestamp when refund was processed or refused"
    )
