"""Training and evaluation pipeline for Tier 0 XGBoost return abuse model.

Implements TRD.md §I, SPEC.md §18-20, and prompt requirements §1-§3.
Guarantees:
- Strictly respects temporal train/validation/test ordering.
- Zero target leakage: only the 16 documented model features are used.
- Isotonic calibration fitted strictly on validation predictions (never on test data).
- Generates metrics.json and model_metadata.json artifacts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from risk_manager.features.schema import FeatureVector, OutcomeLabel
from risk_manager.ml.calibration.evaluate import evaluate_calibration
from risk_manager.ml.calibration.isotonic import IsotonicProbabilityCalibrator
from risk_manager.ml.encoder import FeatureEncoder


def train_tier0_model(
    data_dir: Path | str = "data",
    output_dir: Path | str = "models",
    random_seed: int = 42,
) -> dict[str, Any]:
    """Train XGBoost, fit isotonic calibrator, and evaluate on held-out temporal test set."""
    data_path = Path(data_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_file = data_path / "train.csv"
    val_file = data_path / "val.csv"
    test_file = data_path / "test.csv"

    if not (train_file.exists() and val_file.exists() and test_file.exists()):
        raise FileNotFoundError(
            f"Dataset splits not found in {data_path}. Run scripts/generate_synthetic_data.py first."
        )

    # 1. Load temporal splits without shuffling across boundaries
    train_df = pd.read_csv(train_file)
    val_df = pd.read_csv(val_file)
    test_df = pd.read_csv(test_file)

    target_col = "is_return_abuse"
    model_feature_cols = FeatureVector.model_feature_names()

    # Leakage Assertion: Verify no post-outcome or ID columns are in model features
    prohibited = set(OutcomeLabel.model_fields.keys()) | {
        "actual_loss", "confirmed_abuse", "refund_completed_at", "customer_id_hash", "order_id", "return_request_id"
    }
    leakage = set(model_feature_cols) & prohibited
    if leakage:
        raise ValueError(f"Target leakage detected! Prohibited columns in model features: {leakage}")

    # 2. Fit FeatureEncoder on training data ONLY
    encoder = FeatureEncoder()
    X_train = encoder.fit_transform(train_df[model_feature_cols])
    X_val = encoder.transform(val_df[model_feature_cols])
    X_test = encoder.transform(test_df[model_feature_cols])

    y_train = train_df[target_col].to_numpy(dtype=np.int32)
    y_val = val_df[target_col].to_numpy(dtype=np.int32)
    y_test = test_df[target_col].to_numpy(dtype=np.int32)

    # 3. Train XGBoost binary classifier with validation early stopping
    xgb_model = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        eval_metric="aucpr",
        early_stopping_rounds=10,
        random_state=random_seed,
        n_jobs=-1,
    )
    xgb_model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # 4. Fit Isotonic Calibrator strictly on validation split predictions
    val_raw_probs = xgb_model.predict_proba(X_val)[:, 1]
    calibrator = IsotonicProbabilityCalibrator()
    calibrator.fit(val_raw_probs, y_val)

    # 5. Evaluate on Held-out Temporal Test Set
    test_raw_probs = xgb_model.predict_proba(X_test)[:, 1]
    test_calibrated_probs = np.asarray(calibrator.calibrate(test_raw_probs), dtype=np.float64)

    # Classification & Ranking Metrics
    pr_auc = float(average_precision_score(y_test, test_calibrated_probs))
    roc_auc = float(roc_auc_score(y_test, test_calibrated_probs))

    # Binary decision metrics at threshold 0.5
    preds_binary = (test_calibrated_probs >= 0.5).astype(int)
    precision = float(precision_score(y_test, preds_binary, zero_division=0))
    recall = float(recall_score(y_test, preds_binary, zero_division=0))
    f1 = float(f1_score(y_test, preds_binary, zero_division=0))

    tn, fp, fn, tp = confusion_matrix(y_test, preds_binary, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0

    # Calibration Metrics
    cal_metrics = evaluate_calibration(y_test, test_calibrated_probs)

    metrics_payload = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "test_sample_count": len(y_test),
        "test_positive_ratio": float(np.mean(y_test)),
        "primary_metric_pr_auc": round(pr_auc, 6),
        "roc_auc": round(roc_auc, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        },
        "false_positive_rate": round(fpr, 6),
        "false_negative_rate": round(fnr, 6),
        "brier_score": cal_metrics["brier_score"],
        "expected_calibration_error": cal_metrics["expected_calibration_error"],
        "max_calibration_error": cal_metrics["max_calibration_error"],
        "calibration_method": calibrator.method,
    }

    metadata_payload = {
        "model_type": "XGBOOST",
        "model_version": "v1.0.0",
        "feature_schema_version": "v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": random_seed,
        "input_feature_count": len(model_feature_cols),
        "encoded_feature_count": X_train.shape[1],
        "feature_names_in": model_feature_cols,
        "encoded_feature_names": encoder.get_feature_names_out(),
        "train_samples": len(train_df),
        "val_samples": len(val_df),
        "test_samples": len(test_df),
        "best_iteration": int(xgb_model.best_iteration) if hasattr(xgb_model, "best_iteration") and xgb_model.best_iteration is not None else 100,
    }

    # 6. Save model artifacts
    joblib.dump(xgb_model, out_path / "xgboost_model.joblib")
    encoder.save(out_path / "preprocessor.joblib")
    calibrator.save(out_path / "isotonic_calibrator.joblib")

    with open(out_path / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    with open(out_path / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=2)

    return {
        "metrics": metrics_payload,
        "metadata": metadata_payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Tier 0 XGBoost model with Isotonic Calibration.")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing temporal splits.")
    parser.add_argument("--output-dir", type=str, default="models", help="Directory to save artifacts.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    args = parser.parse_args()

    print(f"Starting Tier 0 XGBoost training (seed={args.seed})...")
    result = train_tier0_model(data_dir=args.data_dir, output_dir=args.output_dir, random_seed=args.seed)

    m = result["metrics"]
    print("\nTraining and Evaluation Complete:")
    print(f"  PR-AUC (Primary): {m['primary_metric_pr_auc']:.4f}")
    print(f"  ROC-AUC:          {m['roc_auc']:.4f}")
    print(f"  Precision:        {m['precision']:.4f}")
    print(f"  Recall:           {m['recall']:.4f}")
    print(f"  F1 Score:         {m['f1']:.4f}")
    print(f"  Brier Score:      {m['brier_score']:.4f}")
    print(f"  ECE:              {m['expected_calibration_error']:.4f}")
    print(f"  Confusion Matrix: TN={m['confusion_matrix']['true_negatives']}, FP={m['confusion_matrix']['false_positives']}, FN={m['confusion_matrix']['false_negatives']}, TP={m['confusion_matrix']['true_positives']}")
    print(f"  FPR:              {m['false_positive_rate']:.4f}")
    print(f"  FNR:              {m['false_negative_rate']:.4f}")
    print(f"  Calibrator:       {m['calibration_method']}")
    print(f"  Artifacts saved to: {args.output_dir}/")


if __name__ == "__main__":
    main()
