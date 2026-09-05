#!/usr/bin/env python
"""Reproducible Model Training & Calibration Script.

Trains the Tier 0 XGBoost return abuse classifier and fits the Isotonic Probability Calibrator
on temporal train/val splits.
"""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from risk_manager.ml.xgboost_model.train import train_tier0_model


def main():
    data_dir = PROJECT_ROOT / "data"
    output_dir = PROJECT_ROOT / "models"

    print("=" * 60)
    print("TRAINING TIER 0 XGBOOST & ISOTONIC CALIBRATOR")
    print(f"Data Source: {data_dir}")
    print(f"Target Dir:  {output_dir}")
    print("=" * 60)

    res = train_tier0_model(data_dir=data_dir, output_dir=output_dir, random_seed=42)
    m = res["metrics"]
    print(f"\n[SUCCESS] Training finished. Validation ROC-AUC: {m['roc_auc']:.4f}, PR-AUC: {m['primary_metric_pr_auc']:.4f}")
    print(f"Artifacts successfully saved to {output_dir}/")


if __name__ == "__main__":
    main()
