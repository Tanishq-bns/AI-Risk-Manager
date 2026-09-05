#!/usr/bin/env python
"""Synthetic dataset generator for Indian D2C e-commerce return risk decisioning.

Implements Phase 3 requirements per TRD.md §Dataset Design and SPEC.md §20.
Simulates realistic mixtures of:
- Legitimate buyers (occasional sizing/defect returns)
- Wardrobing abusers (expensive apparel, returns near policy window edge)
- COD-heavy abusers (repeated doorstep refuse/return loops)
- Serial excessive returners (disproportionate return rate > 65%)
- Switch-and-return abusers (electronics / high-value items)

Enforces strict temporal ordering and non-leakage feature extraction.
"""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import uuid

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_manager.domain.schemas.enums import PaymentMethod
from risk_manager.features.pipeline import (
    HistoricalOrderContext,
    HistoricalReturnContext,
    calculate_feature_vector,
)
from risk_manager.features.schema import FeatureVector, OutcomeLabel

# Archetype distribution in simulated population
# Calibrated so that in the resulting return stream, abuse is a ~20-25% minority class
# per SPEC.md §10 ("abusive returns are a small minority of all return requests").
ARCHETYPE_DISTRIBUTION: dict[str, float] = {
    "LEGITIMATE": 0.88,
    "WARDROBING": 0.04,
    "COD_ABUSE": 0.03,
    "SERIAL_RETURNER": 0.03,
    "SWITCH_AND_RETURN": 0.02,
}

CATEGORIES = ["APPAREL", "FOOTWEAR", "ELECTRONICS", "BEAUTY", "HOME", "ACCESSORIES"]
DISTANCE_BUCKETS = ["LOCAL", "REGIONAL", "NATIONAL"]

RETURN_REASONS = {
    "LEGITIMATE": [
        "Size too small",
        "Size too large",
        "Color differs from website",
        "Fabric stitching defective",
        "Arrived with minor damage",
        "Incomplete order received",
    ],
    "WARDROBING": [
        "Style did not suit me",
        "Did not fit as expected",
        "Changed my mind",
        "Fabric feel not what I wanted",
        "Looked different on me",
    ],
    "COD_ABUSE": [
        "Delivery was delayed",
        "Ordered by mistake",
        "Not available to accept order",
        "Found better price elsewhere",
        "No longer need item",
    ],
    "SERIAL_RETURNER": [
        "Fit not perfect",
        "Color mismatch",
        "Quality below expectations",
        "Did not like style",
        "Multiple sizes ordered to try",
    ],
    "SWITCH_AND_RETURN": [
        "Item inside box does not power on",
        "Wrong item delivered in packaging",
        "Seal was open on delivery",
        "Item was damaged inside box",
    ],
}


def generate_synthetic_dataset(
    num_customers: int = 1000,
    seed: int = 42,
    output_dir: Path = Path("data"),
    simulation_days: int = 180,
) -> dict:
    """Generate chronological synthetic customer order and return event histories."""
    random.seed(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_date = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_date = base_date + timedelta(days=simulation_days)

    all_orders: list[dict] = []
    all_returns: list[dict] = []

    # Map to track historical state per customer
    customer_hist_orders: dict[str, list[HistoricalOrderContext]] = defaultdict(list)
    customer_hist_returns: dict[str, list[HistoricalReturnContext]] = defaultdict(list)

    archetypes_list = list(ARCHETYPE_DISTRIBUTION.keys())
    archetype_weights = list(ARCHETYPE_DISTRIBUTION.values())

    for i in range(num_customers):
        # 1. Customer profile
        raw_cust_id = f"customer_{i}_{seed}"
        cust_hash = hashlib.sha256(raw_cust_id.encode("utf-8")).hexdigest()[:16]
        archetype = random.choices(archetypes_list, weights=archetype_weights)[0]

        # Customer arrival date
        first_seen_days = random.randint(0, simulation_days - 30)
        cust_first_seen = base_date + timedelta(days=first_seen_days)

        # Number of orders based on archetype
        if archetype == "SERIAL_RETURNER":
            num_orders = random.randint(6, 16)
        elif archetype in {"WARDROBING", "COD_ABUSE"}:
            num_orders = random.randint(3, 8)
        else:
            num_orders = random.randint(1, 6)

        # Generate orders chronologically for this customer
        curr_time = cust_first_seen
        for o_idx in range(num_orders):
            interval_days = random.randint(3, max(4, (simulation_days - first_seen_days) // num_orders))
            curr_time += timedelta(days=interval_days, hours=random.randint(1, 12))
            if curr_time >= end_date:
                break

            order_id = uuid.UUID(int=random.getrandbits(128))

            # Category & order value
            if archetype == "WARDROBING":
                category = random.choice(["APPAREL", "FOOTWEAR"])
                order_val = round(random.uniform(2500.0, 7500.0), 2)
            elif archetype == "SWITCH_AND_RETURN":
                category = random.choice(["ELECTRONICS", "ACCESSORIES", "FOOTWEAR"])
                order_val = round(random.uniform(3000.0, 12000.0), 2)
            else:
                category = random.choice(CATEGORIES)
                order_val = round(random.uniform(500.0, 4500.0), 2)

            # Payment method
            if archetype == "COD_ABUSE":
                pm = PaymentMethod.COD
                cod_flag = True
            elif archetype == "WARDROBING":
                pm = random.choice([PaymentMethod.PREPAID, PaymentMethod.PREPAID, PaymentMethod.COD])
                cod_flag = (pm == PaymentMethod.COD)
            else:
                pm = random.choice([PaymentMethod.PREPAID, PaymentMethod.COD])
                cod_flag = (pm == PaymentMethod.COD)

            distance = random.choice(DISTANCE_BUCKETS)

            order_ctx = HistoricalOrderContext(
                id=order_id,
                order_value=order_val,
                payment_method=pm.value,
                cod_flag=cod_flag,
                created_at=curr_time,
                product_category=category,
                delivery_distance_bucket=distance,
            )

            all_orders.append({
                "order_id": str(order_id),
                "customer_id_hash": cust_hash,
                "order_value": order_val,
                "payment_method": pm.value,
                "cod_flag": cod_flag,
                "product_category": category,
                "delivery_distance_bucket": distance,
                "created_at": curr_time.isoformat(),
                "archetype": archetype,
            })

            # Determine return probability
            if archetype == "SERIAL_RETURNER":
                will_return = random.random() < 0.70
            elif archetype == "WARDROBING":
                will_return = random.random() < 0.60
            elif archetype == "COD_ABUSE":
                will_return = random.random() < 0.55
            elif archetype == "SWITCH_AND_RETURN":
                will_return = random.random() < 0.45
            else:  # LEGITIMATE
                will_return = random.random() < 0.22

            if will_return:
                # Return request timing
                if archetype == "WARDROBING":
                    days_to_return = random.randint(11, 14)  # Edge of 14-day policy window
                elif archetype == "COD_ABUSE":
                    days_to_return = random.randint(1, 3)
                elif archetype == "SWITCH_AND_RETURN":
                    days_to_return = random.randint(3, 7)
                else:
                    days_to_return = random.randint(2, 6)

                return_time = curr_time + timedelta(days=days_to_return, hours=random.randint(1, 8))
                if return_time >= end_date:
                    customer_hist_orders[cust_hash].append(order_ctx)
                    continue

                return_id = uuid.UUID(int=random.getrandbits(128))
                reason = random.choice(RETURN_REASONS[archetype])

                # Ground-truth abuse label determination
                if archetype == "LEGITIMATE":
                    is_abuse = False
                    actual_loss = round(random.uniform(50.0, 150.0), 2)  # Normal inspection/restock loss
                else:
                    # Malicious archetypes are ground truth abuse
                    is_abuse = True
                    actual_loss = round(order_val * random.uniform(0.6, 1.0) + 120.0, 2)

                return_ctx = HistoricalReturnContext(
                    id=return_id,
                    order_id=order_id,
                    return_reason=reason,
                    requested_at=return_time,
                    order_value=order_val,
                    status="COMPLETED",
                    confirmed_abuse=is_abuse,
                )

                # Compute point-in-time FeatureVector using the real feature pipeline
                feature_vector = calculate_feature_vector(
                    customer_id_hash=cust_hash,
                    current_order=order_ctx,
                    current_return=return_ctx,
                    prior_orders=customer_hist_orders[cust_hash],
                    prior_returns=customer_hist_returns[cust_hash],
                    decision_timestamp=return_time,
                )

                # Store return record with features and ground-truth labels separated
                return_record = {
                    "return_request_id": str(return_id),
                    "order_id": str(order_id),
                    "customer_id_hash": cust_hash,
                    "requested_at": return_time.isoformat(),
                    "archetype": archetype,
                    # 17 Decision-time features
                    **feature_vector.to_model_features(),
                    "customer_id_hash": cust_hash,
                    "return_reason": reason,
                    "feature_schema_version": "v1",
                    # Ground-truth labels (strictly post-outcome, never features)
                    "is_return_abuse": 1 if is_abuse else 0,
                    "actual_loss": actual_loss,
                    "refund_completed_at": (return_time + timedelta(days=random.randint(2, 5))).isoformat(),
                }

                all_returns.append(return_record)
                customer_hist_returns[cust_hash].append(return_ctx)

            # Record order in history for subsequent orders/returns
            customer_hist_orders[cust_hash].append(order_ctx)

    # --------------------------------------------------------------------------
    # Temporal Train / Validation / Test Splitting
    # --------------------------------------------------------------------------
    # Strict chronological sort by requested_at
    all_returns.sort(key=lambda r: r["requested_at"])

    total_returns = len(all_returns)
    if total_returns == 0:
        raise RuntimeError("No return events generated. Increase customers or simulation_days.")

    train_idx = int(total_returns * 0.70)
    val_idx = int(total_returns * 0.85)

    train_data = all_returns[:train_idx]
    val_data = all_returns[train_idx:val_idx]
    test_data = all_returns[val_idx:]

    # Write CSV files
    fieldnames = list(all_returns[0].keys())

    def write_csv(data_subset: list[dict], file_path: Path) -> None:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data_subset)

    write_csv(all_returns, output_dir / "returns_full.csv")
    write_csv(train_data, output_dir / "train.csv")
    write_csv(val_data, output_dir / "val.csv")
    write_csv(test_data, output_dir / "test.csv")

    # Generate dataset summary
    abuse_count = sum(r["is_return_abuse"] for r in all_returns)
    abuse_rate = round(abuse_count / total_returns, 4)

    summary = {
        "seed": seed,
        "num_customers": num_customers,
        "total_orders": len(all_orders),
        "total_returns": total_returns,
        "abuse_count": abuse_count,
        "legitimate_count": total_returns - abuse_count,
        "abuse_rate": abuse_rate,
        "train_count": len(train_data),
        "val_count": len(val_data),
        "test_count": len(test_data),
        "temporal_windows": {
            "dataset_start": all_returns[0]["requested_at"],
            "dataset_end": all_returns[-1]["requested_at"],
            "train_cutoff": train_data[-1]["requested_at"] if train_data else None,
            "val_cutoff": val_data[-1]["requested_at"] if val_data else None,
            "test_start": test_data[0]["requested_at"] if test_data else None,
        },
        "feature_columns": [c for c in fieldnames if c not in {"is_return_abuse", "actual_loss", "refund_completed_at", "archetype", "return_request_id", "order_id"}],
        "label_columns": ["is_return_abuse", "actual_loss", "refund_completed_at"],
    }

    with open(output_dir / "dataset_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic return-abuse dataset.")
    parser.add_argument("--customers", type=int, default=1000, help="Number of customers to simulate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--output-dir", type=str, default="data", help="Target output directory.")
    parser.add_argument("--days", type=int, default=180, help="Timeline duration in days.")
    args = parser.parse_args()

    print(f"Generating synthetic dataset with {args.customers} customers (seed={args.seed})...")
    summary = generate_synthetic_dataset(
        num_customers=args.customers,
        seed=args.seed,
        output_dir=Path(args.output_dir),
        simulation_days=args.days,
    )

    print("\nDataset Generation Complete:")
    print(f"  Total orders:   {summary['total_orders']}")
    print(f"  Total returns:  {summary['total_returns']}")
    print(f"  Abuse rate:     {summary['abuse_rate'] * 100:.1f}% ({summary['abuse_count']} abuse / {summary['legitimate_count']} legitimate)")
    print(f"  Train split:    {summary['train_count']} rows (cutoff: {summary['temporal_windows']['train_cutoff']})")
    print(f"  Val split:      {summary['val_count']} rows (cutoff: {summary['temporal_windows']['val_cutoff']})")
    print(f"  Test split:     {summary['test_count']} rows (start: {summary['temporal_windows']['test_start']})")
    print(f"  Saved to:       {args.output_dir}/")


if __name__ == "__main__":
    main()
