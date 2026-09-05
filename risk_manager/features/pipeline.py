"""Feature engineering pipeline with strict point-in-time calculation.

Implements PLAN.md T-FE-02 and TRD.md §H.
Guarantees that all customer behavioral aggregations are computed
strictly prior to the return request decision timestamp (no target leakage).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from risk_manager.db.models import Order, ReturnRequest
from risk_manager.domain.schemas.enums import PaymentMethod
from risk_manager.features.schema import FeatureVector

# Standard Indian retail D2C category baseline return rates
CATEGORY_BASELINE_RETURN_RATES: dict[str, float] = {
    "APPAREL": 0.28,
    "FOOTWEAR": 0.22,
    "ELECTRONICS": 0.12,
    "BEAUTY": 0.08,
    "HOME": 0.10,
    "ACCESSORIES": 0.15,
}

# Standard reverse logistics shipping cost by courier zone (INR)
ZONE_REVERSE_LOGISTICS_COST: dict[str, float] = {
    "LOCAL": 75.0,
    "REGIONAL": 135.0,
    "NATIONAL": 210.0,
}

# Category-specific asset restock recovery factors
CATEGORY_RECOVERY_FACTORS: dict[str, float] = {
    "APPAREL": 0.70,
    "FOOTWEAR": 0.75,
    "ELECTRONICS": 0.85,
    "BEAUTY": 0.40,
    "HOME": 0.80,
    "ACCESSORIES": 0.75,
}


@dataclass(frozen=True)
class HistoricalOrderContext:
    """Historical order data point for feature computation."""

    id: uuid.UUID | str
    order_value: float
    payment_method: str
    cod_flag: bool
    created_at: datetime
    product_category: str = "APPAREL"
    delivery_distance_bucket: str = "REGIONAL"


@dataclass(frozen=True)
class HistoricalReturnContext:
    """Historical return data point for feature computation."""

    id: uuid.UUID | str
    order_id: uuid.UUID | str
    return_reason: str
    requested_at: datetime
    order_value: float = 0.0
    status: str = "PENDING"
    confirmed_abuse: bool = False


def calculate_feature_vector(
    customer_id_hash: str,
    current_order: HistoricalOrderContext,
    current_return: HistoricalReturnContext,
    prior_orders: list[HistoricalOrderContext],
    prior_returns: list[HistoricalReturnContext],
    decision_timestamp: datetime | None = None,
) -> FeatureVector:
    """Compute the 17 FeatureVector attributes at decision time.

    Point-in-Time Guarantees:
    1. Only orders with created_at < decision_timestamp are considered.
    2. Only returns with requested_at < decision_timestamp are considered.
    3. The current return is NEVER included in customer_return_count or customer_return_rate.
    """
    decision_time = decision_timestamp or current_return.requested_at

    # Ensure UTC timezone comparability if present
    if decision_time.tzinfo is None:
        decision_time = decision_time.replace(tzinfo=timezone.utc)

    # 1. Strictly prior orders (including current order if placed before decision time)
    candidate_orders = list(prior_orders)
    if not any(str(o.id) == str(current_order.id) for o in candidate_orders):
        candidate_orders.append(current_order)

    valid_prior_orders = [
        o for o in candidate_orders
        if (o.created_at.replace(tzinfo=timezone.utc) if o.created_at.tzinfo is None else o.created_at) < decision_time
    ]

    # 2. Strictly prior returns
    valid_prior_returns = [
        r for r in prior_returns
        if (r.requested_at.replace(tzinfo=timezone.utc) if r.requested_at.tzinfo is None else r.requested_at) < decision_time
        and str(r.id) != str(current_return.id)  # Defensive: never include current return
    ]

    order_count = len(valid_prior_orders)
    return_count = len(valid_prior_returns)

    # Return rate bounded in [0.0, 1.0]
    return_rate = round(return_count / order_count, 4) if order_count > 0 else 0.0
    return_rate = min(1.0, max(0.0, return_rate))

    # Days since purchase
    order_created = current_order.created_at.replace(tzinfo=timezone.utc) if current_order.created_at.tzinfo is None else current_order.created_at
    days_since_purchase = max(0, (decision_time - order_created).days)

    # Prior return value
    prior_return_value = round(sum(r.order_value for r in valid_prior_returns), 2)

    # Prior return frequency: returns per 30-day window over customer history
    if valid_prior_orders:
        earliest_order = min(
            (o.created_at.replace(tzinfo=timezone.utc) if o.created_at.tzinfo is None else o.created_at)
            for o in valid_prior_orders
        )
        tenure_days = max(1, (decision_time - earliest_order).days)
        prior_return_frequency = round((return_count / tenure_days) * 30.0, 4)
    else:
        prior_return_frequency = 0.0

    # Category and logistics defaults
    category = current_order.product_category.upper()
    cat_return_rate = CATEGORY_BASELINE_RETURN_RATES.get(category, 0.15)
    distance_bucket = current_order.delivery_distance_bucket.upper()
    reverse_cost = ZONE_REVERSE_LOGISTICS_COST.get(distance_bucket, 135.0)

    # Recovery value
    recovery_factor = CATEGORY_RECOVERY_FACTORS.get(category, 0.70)
    recovery_value = round(max(0.0, (current_order.order_value * recovery_factor) - reverse_cost), 2)

    # Historical abuse signal: based strictly on prior returns marked as abuse
    if valid_prior_returns:
        prior_abuse_count = sum(1 for r in valid_prior_returns if r.confirmed_abuse)
        hist_abuse_signal = round(prior_abuse_count / len(valid_prior_returns), 4)
    else:
        hist_abuse_signal = 0.0

    # Payment method normalization
    pm = current_order.payment_method
    payment_method_enum = PaymentMethod.COD if (isinstance(pm, str) and pm.upper() == "COD") or pm == PaymentMethod.COD else PaymentMethod.PREPAID

    return FeatureVector(
        customer_id_hash=customer_id_hash,
        order_value=current_order.order_value,
        product_category=category,
        payment_method=payment_method_enum,
        cod_flag=current_order.cod_flag,
        customer_order_count=order_count,
        customer_return_count=return_count,
        customer_return_rate=return_rate,
        days_since_purchase=days_since_purchase,
        prior_return_value=prior_return_value,
        prior_return_frequency=prior_return_frequency,
        item_category_return_rate=cat_return_rate,
        return_reason=current_return.return_reason,
        delivery_distance_bucket=distance_bucket,
        reverse_logistics_cost=reverse_cost,
        estimated_item_recovery_value=recovery_value,
        historical_abuse_signal=hist_abuse_signal,
        feature_schema_version="v1",
    )


async def extract_features_from_db(
    session: AsyncSession,
    return_request_id: uuid.UUID,
    decision_timestamp: datetime | None = None,
) -> FeatureVector:
    """Query database and construct point-in-time FeatureVector for a given return request."""
    # 1. Fetch current return request and its order
    stmt = (
        select(ReturnRequest, Order)
        .join(Order, ReturnRequest.order_id == Order.id)
        .where(ReturnRequest.id == return_request_id)
    )
    result = await session.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError(f"ReturnRequest '{return_request_id}' not found in database")

    db_return, db_order = row
    customer_id_hash = db_order.customer_id_hash
    decision_time = decision_timestamp or db_return.requested_at

    # 2. Fetch all historical orders for this customer prior to decision_time
    order_stmt = (
        select(Order)
        .where(Order.customer_id_hash == customer_id_hash)
        .where(Order.created_at < decision_time)
    )
    order_res = await session.execute(order_stmt)
    prior_orders = [
        HistoricalOrderContext(
            id=o.id,
            order_value=float(o.order_value),
            payment_method=str(o.payment_method),
            cod_flag=o.cod_flag,
            created_at=o.created_at,
        )
        for o in order_res.scalars().all()
    ]

    # 3. Fetch all historical returns for this customer prior to decision_time
    return_stmt = (
        select(ReturnRequest, Order.order_value)
        .join(Order, ReturnRequest.order_id == Order.id)
        .where(Order.customer_id_hash == customer_id_hash)
        .where(ReturnRequest.requested_at < decision_time)
        .where(ReturnRequest.id != return_request_id)
    )
    return_res = await session.execute(return_stmt)
    prior_returns = [
        HistoricalReturnContext(
            id=r.id,
            order_id=r.order_id,
            return_reason=r.return_reason,
            requested_at=r.requested_at,
            order_value=float(val),
        )
        for r, val in return_res.all()
    ]

    current_order_ctx = HistoricalOrderContext(
        id=db_order.id,
        order_value=float(db_order.order_value),
        payment_method=str(db_order.payment_method),
        cod_flag=db_order.cod_flag,
        created_at=db_order.created_at,
    )

    current_return_ctx = HistoricalReturnContext(
        id=db_return.id,
        order_id=db_order.id,
        return_reason=db_return.return_reason,
        requested_at=db_return.requested_at,
        order_value=float(db_order.order_value),
    )

    return calculate_feature_vector(
        customer_id_hash=customer_id_hash,
        current_order=current_order_ctx,
        current_return=current_return_ctx,
        prior_orders=prior_orders,
        prior_returns=prior_returns,
        decision_timestamp=decision_time,
    )
