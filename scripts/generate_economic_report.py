#!/usr/bin/env python
"""Reproducible Economic Analysis Generator for Phase E2.

Evaluates returns against Phase 4 (Tier 0 ML) and Phase 5 (LinUCB Policy Engine)
to measure aggregate business impact, loss avoided, friction costs, and net merchant value in INR.

Generates:
- reports/economic_impact.json (Machine-readable)
- reports/ECONOMIC_IMPACT.md (Executive summary)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from risk_manager.domain.schemas.enums import Action, PaymentMethod
from risk_manager.features.schema import FeatureVector
from risk_manager.api.services.risk_service import get_cascade_scorer, get_policy_engine


def generate_economic_portfolio_report(data_file: str = "data/test.csv") -> dict:
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_path = PROJECT_ROOT / data_file

    if not csv_path.exists():
        raise FileNotFoundError(f"Input dataset not found at {csv_path}")

    df = pd.read_csv(csv_path)
    cascade = get_cascade_scorer()
    policy_engine = get_policy_engine()

    total_returns = len(df)
    total_gmv = 0.0
    total_loss_no_action = 0.0
    total_loss_with_action = 0.0
    total_friction_cost = 0.0
    total_operational_cost = 0.0
    total_net_merchant_value = 0.0

    action_counts = {"A0": 0, "A1": 0, "A2": 0, "A3": 0, "A4": 0}
    action_net_values = {"A0": 0.0, "A1": 0.0, "A2": 0.0, "A3": 0.0, "A4": 0.0}
    risk_band_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

    for _, row in df.iterrows():
        order_val = float(row["order_value"])
        total_gmv += order_val

        # Construct FeatureVector
        fv = FeatureVector(
            customer_id_hash=str(row.get("customer_id_hash", "cust_sim")),
            order_value=order_val,
            product_category=str(row["product_category"]),
            payment_method=PaymentMethod(str(row["payment_method"])),
            cod_flag=bool(row["cod_flag"]),
            customer_order_count=int(row["customer_order_count"]),
            customer_return_count=int(row["customer_return_count"]),
            customer_return_rate=float(row["customer_return_rate"]),
            days_since_purchase=int(row["days_since_purchase"]),
            prior_return_value=float(row["prior_return_value"]),
            prior_return_frequency=float(row["prior_return_frequency"]),
            item_category_return_rate=float(row["item_category_return_rate"]),
            return_reason=str(row["return_reason"]),
            delivery_distance_bucket=str(row["delivery_distance_bucket"]),
            reverse_logistics_cost=float(row["reverse_logistics_cost"]),
            estimated_item_recovery_value=float(row["estimated_item_recovery_value"]),
            historical_abuse_signal=float(row["historical_abuse_signal"]),
        )

        # 1. Authoritative Phase 4 Numerical Scoring
        risk_result = cascade.score(fv)
        risk_band_counts[risk_result.risk_band.value] += 1

        # 2. Authoritative Phase 5 Economic & Policy Evaluation
        pol_context = policy_engine.evaluate_policy(
            feature_vector=fv,
            p_return_abuse=risk_result.p_return_abuse,
            risk_band=risk_result.risk_band,
        )

        selected_act = pol_context.action_selected.value
        action_counts[selected_act] += 1

        # Retrieve selected ActionEvaluation
        selected_eval = None
        for cand in pol_context.candidate_actions:
            if cand.action == pol_context.action_selected:
                selected_eval = cand
                break

        if selected_eval is not None:
            total_loss_no_action += selected_eval.expected_loss + selected_eval.expected_net_value
            total_loss_with_action += selected_eval.expected_loss
            total_friction_cost += selected_eval.friction_cost
            total_operational_cost += selected_eval.operational_cost
            total_net_merchant_value += selected_eval.expected_net_value
            action_net_values[selected_act] += selected_eval.expected_net_value

    loss_avoided = total_loss_no_action - total_loss_with_action

    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": data_file,
        "sample_count": total_returns,
        "currency": "INR",
        "data_scope": "SYNTHETIC / DEMONSTRATION ECONOMIC SIMULATION",
        "summary": {
            "total_gross_merchandise_value_inr": round(total_gmv, 2),
            "expected_abuse_loss_no_action_inr": round(total_loss_no_action, 2),
            "expected_abuse_loss_with_action_inr": round(total_loss_with_action, 2),
            "loss_avoided_inr": round(loss_avoided, 2),
            "customer_friction_cost_inr": round(total_friction_cost, 2),
            "merchant_operational_cost_inr": round(total_operational_cost, 2),
            "net_merchant_value_created_inr": round(total_net_merchant_value, 2),
            "avg_net_value_per_return_inr": round(total_net_merchant_value / total_returns, 2) if total_returns > 0 else 0.0,
            "net_margin_improvement_bps_of_gmv": round((total_net_merchant_value / total_gmv) * 10000.0, 1) if total_gmv > 0 else 0.0,
        },
        "action_distribution": {
            k: {
                "count": action_counts[k],
                "percentage": round((action_counts[k] / total_returns) * 100.0, 1) if total_returns > 0 else 0.0,
                "total_net_value_inr": round(action_net_values[k], 2),
            }
            for k in ["A0", "A1", "A2", "A3", "A4"]
        },
        "risk_band_distribution": {
            k: {
                "count": risk_band_counts[k],
                "percentage": round((risk_band_counts[k] / total_returns) * 100.0, 1) if total_returns > 0 else 0.0,
            }
            for k in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        },
        "human_review_volume": action_counts["A4"],
    }

    # Save JSON
    json_path = reports_dir / "economic_impact.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    # Save Markdown
    md_path = reports_dir / "ECONOMIC_IMPACT.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Aggregate Economic Impact & Value Creation Analysis\n\n")
        f.write(f"**Generated:** {report_payload['generated_at']}  \n")
        f.write(f"**Dataset Evaluated:** `{data_file}` ({total_returns} return events)  \n")
        f.write(f"**Data Scope:** `{report_payload['data_scope']}`  \n\n")
        f.write("---\n\n")
        f.write("## 1. Executive Financial Scorecard\n\n")
        f.write("| Financial Metric | Amount in INR (₹) | Basis / Formula |\n")
        f.write("| :--- | :---: | :--- |\n")
        f.write(f"| **Total GMV Evaluated** | **₹{total_gmv:,.2f}** | Cumulative gross merchandise value of evaluated returns |\n")
        f.write(f"| **Baseline Abuse Loss (No Action)** | **₹{total_loss_no_action:,.2f}** | Unmitigated return abuse exposure ($p \\times \\text{{order_loss}}$) |\n")
        f.write(f"| **Residual Abuse Loss (With Intervention)** | **₹{total_loss_with_action:,.2f}** | Residual loss after applying optimal policy interventions |\n")
        f.write(f"| **Abuse Loss Prevented** | **₹{loss_avoided:,.2f}** | Direct fraudulent margin leakage intercepted |\n")
        f.write(f"| **Customer Friction Cost Incurred** | **₹{total_friction_cost:,.2f}** | Quantified LTV and customer churn friction penalty |\n")
        f.write(f"| **Merchant Operational Courier / Review Cost** | **₹{total_operational_cost:,.2f}** | Direct doorstep OTP fees and specialist manual review time |\n")
        f.write(f"| **Net Merchant Value Created** | **₹{total_net_merchant_value:,.2f}** | **$\\text{{Loss Avoided}} - C_{{\\text{{friction}}}} - C_{{\\text{{ops}}}}$** |\n")
        f.write(f"| **Average Net Value per Return** | **₹{report_payload['summary']['avg_net_value_per_return_inr']:,.2f}** | Net economic profit contribution per processed return |\n")
        f.write(f"| **GMV Margin Recovery** | **+{report_payload['summary']['net_margin_improvement_bps_of_gmv']} bps** | Margin recovery expressed as basis points of return GMV |\n\n")
        f.write("---\n\n")
        f.write("## 2. Policy Action Distribution\n\n")
        f.write("| Action | Name | Volume | Share (%) | Total Net Value Created (₹) |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: |\n")
        for act in ["A0", "A1", "A2", "A3", "A4"]:
            info = report_payload["action_distribution"][act]
            f.write(f"| **{act}** | `{act}` | {info['count']} | {info['percentage']}% | ₹{info['total_net_value_inr']:,.2f} |\n")
        f.write("\n---\n\n")
        f.write("## 3. Operations & Review Queue Load\n\n")
        f.write(f"- **Total Automated Straight-Through Processing ($A_0 - A_3$):** {total_returns - action_counts['A4']} cases ({round(((total_returns - action_counts['A4']) / total_returns) * 100, 1)}%)\n")
        f.write(f"- **Human Specialist Review Volume ($A_4$):** {action_counts['A4']} cases ({report_payload['action_distribution']['A4']['percentage']}%)\n")

    print(f"[SUCCESS] Economic report generated at {json_path} and {md_path}")
    return report_payload


if __name__ == "__main__":
    generate_economic_portfolio_report()
