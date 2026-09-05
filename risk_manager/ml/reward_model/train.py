"""Training and evaluation pipeline for the Random Forest Economic Reward Model.

Implements TRD.md §O, STATE.md ADR-006, SPEC.md §14, and prompt requirements §3-§7.
Trains a RandomForestRegressor to predict expected net economic value (margin saved - friction/ops cost)
associated with candidate interventions.
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
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


NUMERIC_FEATURES = [
    "p_return_abuse",
    "order_value",
    "reverse_logistics_cost",
    "estimated_item_recovery_value",
    "customer_return_rate",
    "prior_return_value",
    "prior_return_frequency",
    "customer_order_count",
    "customer_return_count",
    "cod_flag",
    "days_since_purchase",
    "friction_cost",
    "operational_cost",
]

CATEGORICAL_FEATURES = [
    "action",
    "product_category",
]

ECONOMIC_FEATURE_NAMES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COL = "expected_net_value"


def build_economic_pipeline(random_seed: int = 42) -> Pipeline:
    """Construct scikit-learn pipeline for tabular economic regression."""
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )

    regressor = RandomForestRegressor(
        n_estimators=100,
        max_depth=6,
        min_samples_leaf=4,
        random_state=random_seed,
        n_jobs=-1,
    )

    return Pipeline([
        ("preprocessor", preprocessor),
        ("regressor", regressor),
    ])


def evaluate_economic_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    actions: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compute regression and action-level metrics on predictions."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    worst_case_error = float(np.max(np.abs(y_true - y_pred)))

    action_errors: dict[str, dict[str, float]] = {}
    if actions is not None:
        for action in np.unique(actions):
            mask = actions == action
            if np.sum(mask) > 0:
                act_mae = float(mean_absolute_error(y_true[mask], y_pred[mask]))
                act_rmse = float(np.sqrt(mean_squared_error(y_true[mask], y_pred[mask])))
                action_errors[str(action)] = {
                    "mae": round(act_mae, 4),
                    "rmse": round(act_rmse, 4),
                    "sample_count": int(np.sum(mask)),
                }

    return {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "test_sample_count": len(y_true),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2_score": round(r2, 6),
        "worst_case_error": round(worst_case_error, 4),
        "prediction_distribution": {
            "mean": round(float(np.mean(y_pred)), 4),
            "std": round(float(np.std(y_pred)), 4),
            "min": round(float(np.min(y_pred)), 4),
            "p50": round(float(np.percentile(y_pred, 50)), 4),
            "max": round(float(np.max(y_pred)), 4),
        },
        "action_level_metrics": action_errors,
    }


def train_economic_model(
    data_dir: Path | str = "data",
    output_dir: Path | str = "models",
    random_seed: int = 42,
) -> dict[str, Any]:
    """Train Random Forest Regressor and evaluate on held-out temporal test set."""
    data_path = Path(data_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_file = data_path / "economic_train.csv"
    val_file = data_path / "economic_val.csv"
    test_file = data_path / "economic_test.csv"

    if not (train_file.exists() and val_file.exists() and test_file.exists()):
        raise FileNotFoundError(
            f"Economic splits missing in {data_path}. Run scripts/generate_economic_data.py first."
        )

    # 1. Ingest temporal splits
    train_df = pd.read_csv(train_file)
    val_df = pd.read_csv(val_file)
    test_df = pd.read_csv(test_file)

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COL].to_numpy(dtype=np.float64)

    X_val = val_df[feature_cols]
    y_val = val_df[TARGET_COL].to_numpy(dtype=np.float64)

    X_test = test_df[feature_cols]
    y_test = test_df[TARGET_COL].to_numpy(dtype=np.float64)

    # 2. Fit pipeline on training data
    pipeline = build_economic_pipeline(random_seed=random_seed)
    pipeline.fit(X_train, y_train)

    # 3. Evaluate on held-out temporal test set
    y_pred_test = pipeline.predict(X_test)
    metrics_payload = evaluate_economic_predictions(y_test, y_pred_test, test_df["action"].to_numpy())

    metadata_payload = {
        "model_type": "RANDOM_FOREST_REGRESSOR",
        "model_version": "v1.0.0-rf-econ",
        "feature_schema_version": "v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": random_seed,
        "input_feature_count": len(feature_cols),
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "train_samples": len(train_df),
        "val_samples": len(val_df),
        "test_samples": len(test_df),
        "n_estimators": 100,
        "max_depth": 6,
    }

    # 4. Serialize artifacts (using dictionary payload to prevent pickle namespace issues)
    artifact_payload = {
        "pipeline": pipeline,
        "metadata": metadata_payload,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
    }
    joblib.dump(artifact_payload, out_path / "rf_reward_model.joblib")

    with open(out_path / "economic_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    with open(out_path / "economic_model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=2)

    return {
        "metrics": metrics_payload,
        "metadata": metadata_payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Random Forest Economic Reward Model.")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--output-dir", type=str, default="models")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Starting Random Forest economic model training (seed={args.seed})...")
    result = train_economic_model(data_dir=args.data_dir, output_dir=args.output_dir, random_seed=args.seed)

    m = result["metrics"]
    print("\nEconomic Model Training Complete:")
    print(f"  MAE:              INR {m['mae']:.2f}")
    print(f"  RMSE:             INR {m['rmse']:.2f}")
    print(f"  R^2 Score:        {m['r2_score']:.4f}")
    print(f"  Worst-Case Error: INR {m['worst_case_error']:.2f}")
    print(f"  Pred Distribution: Mean=INR {m['prediction_distribution']['mean']:.2f}, Median=INR {m['prediction_distribution']['p50']:.2f}")
    print(f"  Artifacts saved to: {args.output_dir}/")


if __name__ == "__main__":
    main()
