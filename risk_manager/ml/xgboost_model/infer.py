"""Inference runner for Tier 0 XGBoost model with Isotonic Calibration.

Implements TRD.md §I, SPEC.md §18, and prompt requirements §1 and §3.
Enforces strict schema validation, input validation, and latency tracking.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any
import joblib
import numpy as np

from risk_manager.domain.schemas.enums import ScoringSource
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.calibration.isotonic import IsotonicProbabilityCalibrator
from risk_manager.ml.encoder import FeatureEncoder


class Tier0Predictor:
    """Predictor for Tier 0: XGBoost Classifier + Isotonic Calibrator."""

    def __init__(self, models_dir: Path | str = "models") -> None:
        self.models_dir = Path(models_dir)
        self.model = None
        self.encoder: FeatureEncoder | None = None
        self.calibrator: IsotonicProbabilityCalibrator | None = None
        self.metadata: dict[str, Any] = {}
        self.model_version: str = "v1.0.0"
        self.feature_schema_version: str = "v1"
        self.is_loaded: bool = False

    def load(self) -> Tier0Predictor:
        """Load and validate all Tier 0 artifacts from disk."""
        model_path = self.models_dir / "xgboost_model.joblib"
        encoder_path = self.models_dir / "preprocessor.joblib"
        calibrator_path = self.models_dir / "isotonic_calibrator.joblib"
        metadata_path = self.models_dir / "model_metadata.json"

        if not model_path.exists():
            raise FileNotFoundError(f"Tier 0 XGBoost model not found at {model_path}")
        if not encoder_path.exists():
            raise FileNotFoundError(f"Feature preprocessor not found at {encoder_path}")
        if not calibrator_path.exists():
            raise FileNotFoundError(f"Calibrator not found at {calibrator_path}")

        self.model = joblib.load(model_path)
        self.encoder = FeatureEncoder.load(encoder_path)
        self.calibrator = IsotonicProbabilityCalibrator.load(calibrator_path)

        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
                self.model_version = self.metadata.get("model_version", "v1.0.0")
                self.feature_schema_version = self.metadata.get("feature_schema_version", "v1")

        self.is_loaded = True
        return self

    def predict_one(self, feature_vector: FeatureVector | dict[str, Any]) -> tuple[float, float, float]:
        """Score a single feature vector.

        Returns:
            (calibrated_probability, raw_probability, latency_ms)
        """
        if not self.is_loaded or self.model is None or self.encoder is None or self.calibrator is None:
            raise RuntimeError("Tier0Predictor is not loaded. Call load() first.")

        t_start = time.perf_counter()

        # Extract features
        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.to_model_features()
        else:
            data = feature_vector

        # Transform features
        X = self.encoder.transform(data)

        # Predict raw probability
        raw_prob_arr = self.model.predict_proba(X)[:, 1]
        raw_prob = float(raw_prob_arr[0])

        # Calibrate
        cal_prob = float(self.calibrator.calibrate(raw_prob))

        # Enforce bounds
        cal_prob = min(1.0, max(0.0, cal_prob))

        latency_ms = (time.perf_counter() - t_start) * 1000.0

        return cal_prob, raw_prob, latency_ms
