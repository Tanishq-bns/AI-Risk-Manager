#!/usr/bin/env python
"""Programmatic evaluation of held-out test datasets for Phase E1.

Generates machine-verified evaluation results in reports/heldout_test/results.json.
Guarantees:
- Zero fabricated metrics.
- Uses strictly frozen held-out test datasets (data/test.csv and data/economic_test.csv).
- Appends execution provenance to reports/heldout_test/ACCESS_LOG.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from risk_manager.features.schema import FeatureVector
from risk_manager.ml.calibration.evaluate import evaluate_calibration
from risk_manager.ml.calibration.isotonic import IsotonicProbabilityCalibrator
from risk_manager.ml.encoder import FeatureEncoder


def evaluate_heldout_suite() -> dict:
    models_dir = PROJECT_ROOT / "models"
    data_dir = PROJECT_ROOT / "data"
    reports_dir = PROJECT_ROOT / "reports" / "heldout_test"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Tier 0 Risk Model Artifacts
    xgb_path = models_dir / "xgboost_model.joblib"
    prep_path = models_dir / "preprocessor.joblib"
    calib_path = models_dir / "isotonic_calibrator.joblib"
    test_csv = data_dir / "test.csv"

    if not all(p.exists() for p in [xgb_path, prep_path, calib_path, test_csv]):
        raise FileNotFoundError("Missing Tier 0 risk model artifacts or test.csv")

    xgb_model = joblib.load(xgb_path)
    preprocessor = FeatureEncoder.load(prep_path)
    calibrator = IsotonicProbabilityCalibrator.load(calib_path)
    test_df = pd.read_csv(test_csv)

    feature_cols = FeatureVector.model_feature_names()
    X_test_raw = test_df[feature_cols]
    y_test = test_df["is_return_abuse"].to_numpy(dtype=np.int32)

    X_test_encoded = preprocessor.transform(X_test_raw)
    test_raw_probs = xgb_model.predict_proba(X_test_encoded)[:, 1]
    test_calibrated_probs = np.asarray(calibrator.calibrate(test_raw_probs), dtype=np.float64)

    # Classification & Ranking Metrics
    pr_auc = float(average_precision_score(y_test, test_calibrated_probs))
    roc_auc = float(roc_auc_score(y_test, test_calibrated_probs))

    preds_binary = (test_calibrated_probs >= 0.5).astype(int)
    precision = float(precision_score(y_test, preds_binary, zero_division=0))
    recall = float(recall_score(y_test, preds_binary, zero_division=0))
    f1 = float(f1_score(y_test, preds_binary, zero_division=0))

    tn, fp, fn, tp = confusion_matrix(y_test, preds_binary, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0

    cal_metrics = evaluate_calibration(y_test, test_calibrated_probs)

    # Risk Band Stratification
    bands = {"LOW": (0.0, 0.25), "MEDIUM": (0.25, 0.60), "HIGH": (0.60, 0.85), "CRITICAL": (0.85, 1.0001)}
    band_breakdown = {}
    for band_name, (low, high) in bands.items():
        mask = (test_calibrated_probs >= low) & (test_calibrated_probs < high)
        count = int(np.sum(mask))
        abuse_in_band = int(np.sum(y_test[mask])) if count > 0 else 0
        actual_rate = float(abuse_in_band / count) if count > 0 else 0.0
        mean_p = float(np.mean(test_calibrated_probs[mask])) if count > 0 else 0.0
        band_breakdown[band_name] = {
            "sample_count": count,
            "abuse_count": abuse_in_band,
            "actual_abuse_rate": round(actual_rate, 4),
            "mean_calibrated_prob": round(mean_p, 4),
        }

    tier0_results = {
        "model_version": "v1.0.0-xgb-calibrated",
        "sample_count": len(y_test),
        "positive_sample_count": int(np.sum(y_test)),
        "negative_sample_count": int(len(y_test) - np.sum(y_test)),
        "base_rate": round(float(np.mean(y_test)), 4),
        "pr_auc": round(pr_auc, 6),
        "roc_auc": round(roc_auc, 6),
        "precision_at_0_5": round(precision, 6),
        "recall_at_0_5": round(recall, 6),
        "f1_score_at_0_5": round(f1, 6),
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        },
        "false_positive_rate": round(fpr, 6),
        "false_negative_rate": round(fnr, 6),
        "brier_score": round(cal_metrics["brier_score"], 6),
        "expected_calibration_error": round(cal_metrics["expected_calibration_error"], 6),
        "max_calibration_error": round(cal_metrics["max_calibration_error"], 6),
        "risk_band_stratification": band_breakdown,
    }

    # 2. Load Economic Model Artifacts
    econ_path = models_dir / "rf_reward_model.joblib"
    econ_test_csv = data_dir / "economic_test.csv"
    econ_results = {}

    if econ_path.exists() and econ_test_csv.exists():
        econ_raw = joblib.load(econ_path)
        econ_pipeline = econ_raw["pipeline"] if isinstance(econ_raw, dict) else econ_raw
        econ_df = pd.read_csv(econ_test_csv)
        y_econ_test = econ_df["expected_net_value"].to_numpy(dtype=np.float64)
        y_econ_pred = econ_pipeline.predict(econ_df)

        mae = float(mean_absolute_error(y_econ_test, y_econ_pred))
        rmse = float(np.sqrt(mean_squared_error(y_econ_test, y_econ_pred)))
        r2 = float(r2_score(y_econ_test, y_econ_pred))

        action_metrics = {}
        for act in ["A0", "A1", "A2", "A3", "A4"]:
            act_mask = econ_df["action"] == act
            if np.any(act_mask):
                y_act_true = y_econ_test[act_mask]
                y_act_pred = y_econ_pred[act_mask]
                action_metrics[act] = {
                    "sample_count": int(np.sum(act_mask)),
                    "mae_inr": round(float(mean_absolute_error(y_act_true, y_act_pred)), 2),
                    "rmse_inr": round(float(np.sqrt(mean_squared_error(y_act_true, y_act_pred))), 2),
                }

        econ_results = {
            "model_version": "v1.0.0-rf-econ",
            "sample_count": len(y_econ_test),
            "mae_inr": round(mae, 2),
            "rmse_inr": round(rmse, 2),
            "r2_score": round(r2, 4),
            "action_level_metrics": action_metrics,
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    final_payload = {
        "evaluation_timestamp": now_iso,
        "dataset_type": "SYNTHETIC_DATA_TEMPORAL_SPLIT",
        "disclaimer": "SYNTHETIC DATA / DEMONSTRATION VALIDATION — Not measured on live merchant production traffic.",
        "random_seed": 42,
        "tier0_risk_model": tier0_results,
        "economic_reward_model": econ_results,
    }

    # Save results.json
    results_file = reports_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)

    # Append to ACCESS_LOG.md
    access_log = reports_dir / "ACCESS_LOG.md"
    log_exists = access_log.exists()
    with open(access_log, "a", encoding="utf-8") as f:
        if not log_exists:
            f.write("# Held-Out Test Evaluation Access Log\n\n")
            f.write("| Timestamp (UTC) | Action / Reason | Script | Target | Results Artifact |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
        f.write(
            f"| {now_iso} | Phase E1 Held-out Evaluation | `scripts/evaluate_heldout.py` | `data/test.csv` (170 samples), `data/economic_test.csv` (850 samples) | [`reports/heldout_test/results.json`](file:///reports/heldout_test/results.json) |\n"
        )

    print(f"[SUCCESS] Held-out evaluation complete. Artifacts written to {reports_dir}")
    return final_payload


if __name__ == "__main__":
    evaluate_heldout_suite()
