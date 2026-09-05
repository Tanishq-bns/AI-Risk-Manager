"""Feature completeness and data quality evaluator.

Implements PLAN.md T-FE-03 and TRD.md §K.
Evaluates input feature vectors for nulls, NaNs, Infs, range violations,
and logical consistency to gate Tier 0 scoring or trigger the fallback cascade.
"""

import math
from typing import Any
from pydantic import BaseModel, Field

from risk_manager.features.schema import FeatureVector


class CompletenessReport(BaseModel):
    """Structured report on feature quality and completeness."""

    completeness_ratio: float = Field(ge=0.0, le=1.0, description="Fraction of required features validly populated")
    is_sufficient: bool = Field(description="True if ratio >= threshold and no fatal invalidities")
    total_fields: int = Field(gt=0)
    populated_fields: int = Field(ge=0)
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    range_violations: list[str] = Field(default_factory=list)


# Alias for backward/forward naming compatibility
FeatureCompletenessReport = CompletenessReport


def evaluate_feature_completeness(
    vector: FeatureVector | dict[str, Any],
    min_ratio: float = 0.85,
) -> CompletenessReport:
    """Evaluate completeness and range sanity of a FeatureVector or raw dict.

    Args:
        vector: FeatureVector instance or feature dictionary.
        min_ratio: Minimum ratio required for Tier 0 scoring (default 0.85 per TRD.md §Q).

    Returns:
        CompletenessReport with ratio, missing fields, and validity flags.
    """
    if isinstance(vector, FeatureVector):
        data = vector.model_dump()
    elif isinstance(vector, dict):
        data = vector
    else:
        raise TypeError(f"Expected FeatureVector or dict, got {type(vector)}")

    # Features that must be evaluated
    expected_fields = [
        "customer_id_hash",
        "order_value",
        "product_category",
        "payment_method",
        "cod_flag",
        "customer_order_count",
        "customer_return_count",
        "customer_return_rate",
        "days_since_purchase",
        "prior_return_value",
        "prior_return_frequency",
        "item_category_return_rate",
        "return_reason",
        "delivery_distance_bucket",
        "reverse_logistics_cost",
        "estimated_item_recovery_value",
        "historical_abuse_signal",
    ]

    missing: list[str] = []
    invalid: list[str] = []
    violations: list[str] = []

    populated = 0

    for field in expected_fields:
        val = data.get(field)
        if val is None:
            missing.append(field)
            continue

        # Check for NaN / Infinity on numeric types
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if math.isnan(val) or math.isinf(val):
                invalid.append(f"{field}: NaN/Inf detected")
                continue

        # Range and logical consistency checks
        if field == "order_value" and val <= 0:
            violations.append("order_value must be > 0")
        elif field == "customer_order_count" and val < 0:
            violations.append("customer_order_count must be >= 0")
        elif field == "customer_return_count" and val < 0:
            violations.append("customer_return_count must be >= 0")
        elif field in {"customer_return_rate", "item_category_return_rate", "historical_abuse_signal"}:
            if not (0.0 <= float(val) <= 1.0):
                violations.append(f"{field} must be in [0.0, 1.0], got {val}")
        elif field == "days_since_purchase" and val < 0:
            violations.append("days_since_purchase must be >= 0")

        populated += 1

    # Cross-field logical check: return count cannot exceed order count
    orders_cnt = data.get("customer_order_count")
    returns_cnt = data.get("customer_return_count")
    if (
        isinstance(orders_cnt, (int, float))
        and isinstance(returns_cnt, (int, float))
        and returns_cnt > orders_cnt
    ):
        violations.append(
            f"Logical violation: customer_return_count ({returns_cnt}) > customer_order_count ({orders_cnt})"
        )

    total = len(expected_fields)
    ratio = populated / total
    is_sufficient = (ratio >= min_ratio) and (len(invalid) == 0) and (len(violations) == 0)

    return CompletenessReport(
        completeness_ratio=round(ratio, 4),
        is_sufficient=is_sufficient,
        total_fields=total,
        populated_fields=populated,
        missing_fields=missing,
        invalid_fields=invalid,
        range_violations=violations,
    )
