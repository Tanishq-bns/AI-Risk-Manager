"""Tier 1 Isolation Forest unsupervised anomaly detector.

Implements TRD.md §I, STATE.md ADR-003, and prompt requirement §5.
Provides an unsupervised anomaly-derived risk proxy when Tier 0 is degraded.
Does NOT require labels. Outputs are explicitly marked with scoring_source=ISOLATION_FOREST.
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
from sklearn.ensemble import IsolationForest

from risk_manager.domain.schemas.enums import FallbackTier, ScoringSource
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.encoder import FeatureEncoder


class Tier1IsolationForest:
    """Unsupervised Isolation Forest anomaly detector for Tier 1 fallback scoring."""

    def __init__(
        self,
        n_estimators: int = 100,
        contamination: float = 0.10,
        random_seed: int = 42,
    ) -> None:
        self.n_estimators: int = n_estimators
        self.contamination: float = contamination
        self.random_seed: int = random_seed
        self.model: IsolationForest | None = None
        self.encoder: FeatureEncoder | None = None
        self.min_score_: float = -0.5
        self.max_score_: float = 0.5
        self.is_loaded: bool = False
        self.model_version: str = "v1.0.0-iforest"
        self.feature_schema_version: str = "v1"

    def fit(self, train_df: pd.DataFrame, encoder: FeatureEncoder) -> Tier1IsolationForest:
        """Fit Isolation Forest purely on feature inputs (unsupervised, no target labels)."""
        self.encoder = encoder
        model_feature_cols = FeatureVector.model_feature_names()
        X_train = self.encoder.transform(train_df[model_feature_cols])

        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_seed,
            n_jobs=-1,
        )
        self.model.fit(X_train)

        # Store calibration bounds for anomaly score normalization
        train_scores = self.model.decision_function(X_train)
        self.min_score_ = float(np.min(train_scores))
        self.max_score_ = float(np.max(train_scores))
        self.is_loaded = True
        return self

    def score_one(self, feature_vector: FeatureVector | dict[str, Any]) -> tuple[float, float]:
        """Compute anomaly score and mapped risk proxy in [0.0, 1.0].

        Returns:
            (anomaly_risk_proxy, raw_anomaly_score)
        """
        if not self.is_loaded or self.model is None or self.encoder is None:
            raise RuntimeError("Tier1IsolationForest is not fitted or loaded.")

        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.to_model_features()
        else:
            data = feature_vector

        X = self.encoder.transform(data)
        raw_score = float(self.model.decision_function(X)[0])

        # Map decision function to [0.0, 1.0] anomaly risk proxy
        # In scikit-learn, lower/negative decision function = higher anomaly
        denom = max(1e-6, self.max_score_ - self.min_score_)
        anomaly_proxy = float(np.clip((self.max_score_ - raw_score) / denom, 0.0, 1.0))

        return anomaly_proxy, raw_score

    def save(self, file_path: Path | str) -> None:
        """Save fitted Isolation Forest model to disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "min_score": self.min_score_,
            "max_score": self.max_score_,
            "n_estimators": self.n_estimators,
            "contamination": self.contamination,
            "random_seed": self.random_seed,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, file_path: Path | str, encoder_path: Path | str | None = None) -> Tier1IsolationForest:
        """Load fitted Isolation Forest from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Isolation Forest artifact not found at {path}")
        payload = joblib.load(path)
        if isinstance(payload, dict):
            instance = cls(
                n_estimators=payload.get("n_estimators", 100),
                contamination=payload.get("contamination", 0.10),
                random_seed=payload.get("random_seed", 42),
            )
            instance.model = payload["model"]
            instance.min_score_ = payload.get("min_score", -0.5)
            instance.max_score_ = payload.get("max_score", 0.5)
            instance.model_version = payload.get("model_version", "v1.0.0-iforest")
            instance.feature_schema_version = payload.get("feature_schema_version", "v1")
        elif isinstance(payload, Tier1IsolationForest):
            instance = payload
        else:
            raise TypeError(f"Loaded artifact is not valid Isolation Forest payload: {type(payload)}")

        if encoder_path:
            instance.encoder = FeatureEncoder.load(encoder_path)

        instance.is_loaded = True
        return instance


def train_isolation_forest(
    data_dir: Path | str = "data",
    output_dir: Path | str = "models",
    random_seed: int = 42,
) -> Tier1IsolationForest:
    """Train and save Isolation Forest model on train.csv."""
    data_path = Path(data_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_csv(data_path / "train.csv")

    # Load or fit encoder
    encoder_path = out_path / "preprocessor.joblib"
    if encoder_path.exists():
        encoder = FeatureEncoder.load(encoder_path)
    else:
        encoder = FeatureEncoder()
        encoder.fit(train_df[FeatureVector.model_feature_names()])
        encoder.save(encoder_path)

    iforest = Tier1IsolationForest(random_seed=random_seed)
    iforest.fit(train_df, encoder)
    iforest.save(out_path / "isolation_forest.joblib")

    return iforest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Tier 1 Isolation Forest anomaly detector.")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--output-dir", type=str, default="models")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Training Tier 1 Isolation Forest (seed={args.seed})...")
    train_isolation_forest(data_dir=args.data_dir, output_dir=args.output_dir, random_seed=args.seed)
    print(f"Isolation Forest trained and saved to {args.output_dir}/isolation_forest.joblib")


if __name__ == "__main__":
    main()
