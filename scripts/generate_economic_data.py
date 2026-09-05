"""Synthetic Economic Outcome Dataset Generator for Indian D2C Return Scenarios.

Implements SPEC.md §14, TRD.md §O, and prompt requirements §4-§6.
Transforms Phase 3/4 return records into action-level economic training observations.
Preserves strict temporal splitting (Train -> Val -> Test) with zero lookahead leakage.
"""

import argparse
import csv
from pathlib import Path
import random
import sys
from uuid import uuid4

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_manager.domain.actions import ACTION_REGISTRY
from risk_manager.domain.schemas.enums import Action
from risk_manager.ml.xgboost_model.infer import Tier0Predictor


def generate_economic_split(
    input_csv: Path,
    output_csv: Path,
    predictor: Tier0Predictor,
    seed: int = 42,
) -> int:
    """Generate action-level economic outcomes for a specific temporal split."""
    random.seed(seed)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input split not found: {input_csv}")

    with open(input_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fieldnames = [
        "sample_id",
        "return_request_id",
        "action",
        "p_return_abuse",
        "is_return_abuse",
        "order_value",
        "product_category",
        "reverse_logistics_cost",
        "estimated_item_recovery_value",
        "customer_return_rate",
        "prior_return_value",
        "prior_return_frequency",
        "customer_order_count",
        "customer_return_count",
        "cod_flag",
        "days_since_purchase",
        "expected_loss_no_action",
        "expected_loss_with_action",
        "friction_cost",
        "operational_cost",
        "margin_saved",
        "expected_net_value",
        "realized_outcome",
    ]

    out_records = []

    for row in rows:
        ret_id = row.get("return_request_id", str(uuid4()))
        order_val = float(row["order_value"])
        rev_cost = float(row["reverse_logistics_cost"])
        recovery_val = float(row["estimated_item_recovery_value"])
        is_abuse = int(row["is_return_abuse"])

        # Compute calibrated p_return_abuse from Phase 4 Tier 0 model
        cal_prob, raw_prob, _ = predictor.predict_one(row)

        # Baseline unmitigated loss if abuse occurs
        unmitigated_loss = max(100.0, order_val + rev_cost - recovery_val)
        expected_loss_no_action = round(cal_prob * unmitigated_loss, 2)

        # Generate outcome for all canonical actions
        for action_enum in [Action.A0, Action.A1, Action.A2, Action.A3, Action.A4]:
            meta = ACTION_REGISTRY[action_enum]
            friction = meta.customer_friction_cost
            ops_cost = meta.merchant_operational_cost
            mit_rate = meta.abuse_loss_mitigation_rate

            # SPEC §14 Economic Formulation
            loss_if_abuse = unmitigated_loss * (1.0 - mit_rate) + ops_cost
            expected_loss_with_action = round(
                cal_prob * loss_if_abuse + (1.0 - cal_prob) * friction, 2
            )
            expected_net_value = round(expected_loss_no_action - expected_loss_with_action, 2)
            margin_saved = round(unmitigated_loss * mit_rate, 2)

            # Ground-truth simulated outcome (for offline regression target evaluation)
            if is_abuse == 1:
                realized = round(margin_saved - ops_cost, 2)
            else:
                realized = round(-friction - ops_cost, 2)

            out_records.append({
                "sample_id": f"{ret_id}_{action_enum.value}",
                "return_request_id": ret_id,
                "action": action_enum.value,
                "p_return_abuse": round(cal_prob, 4),
                "is_return_abuse": is_abuse,
                "order_value": order_val,
                "product_category": row["product_category"],
                "reverse_logistics_cost": rev_cost,
                "estimated_item_recovery_value": recovery_val,
                "customer_return_rate": float(row["customer_return_rate"]),
                "prior_return_value": float(row["prior_return_value"]),
                "prior_return_frequency": float(row["prior_return_frequency"]),
                "customer_order_count": int(row["customer_order_count"]),
                "customer_return_count": int(row["customer_return_count"]),
                "cod_flag": int(row["cod_flag"]),
                "days_since_purchase": int(row["days_since_purchase"]),
                "expected_loss_no_action": expected_loss_no_action,
                "expected_loss_with_action": expected_loss_with_action,
                "friction_cost": friction,
                "operational_cost": ops_cost,
                "margin_saved": margin_saved,
                "expected_net_value": expected_net_value,
                "realized_outcome": realized,
            })

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_records)

    return len(out_records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic economic outcome datasets.")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--models-dir", type=str, default="models")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    models_dir = Path(args.models_dir)

    print("Loading Tier 0 predictor...")
    predictor = Tier0Predictor(models_dir=models_dir).load()

    print("Generating economic training split...")
    n_train = generate_economic_split(data_dir / "train.csv", data_dir / "economic_train.csv", predictor, seed=args.seed)
    print(f"  Generated {n_train} rows in economic_train.csv")

    print("Generating economic validation split...")
    n_val = generate_economic_split(data_dir / "val.csv", data_dir / "economic_val.csv", predictor, seed=args.seed)
    print(f"  Generated {n_val} rows in economic_val.csv")

    print("Generating economic test split...")
    n_test = generate_economic_split(data_dir / "test.csv", data_dir / "economic_test.csv", predictor, seed=args.seed)
    print(f"  Generated {n_test} rows in economic_test.csv")

    print("\nSynthetic Economic Dataset Generation Complete.")


if __name__ == "__main__":
    main()
