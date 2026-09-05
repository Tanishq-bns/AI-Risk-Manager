"""Isotonic probability calibration with Platt scaling contingency fallback.

Implements TRD.md §I, SPEC.md §18, and prompt requirement §3.
Calibrates raw tree model output probabilities to empirical risk probabilities.
Fitted strictly on validation split predictions, NEVER on test data.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


class IsotonicProbabilityCalibrator:
    """Post-hoc probability calibrator with isotonic regression and Platt contingency fallback.

    Ensures 0.0 <= p_calibrated <= 1.0 strictly.
    """

    def __init__(self, min_samples_for_isotonic: int = 50) -> None:
        self.min_samples_for_isotonic: int = min_samples_for_isotonic
        self.calibrator: IsotonicRegression | LogisticRegression | None = None
        self.method: str = "unfitted"
        self.is_fitted: bool = False

    def fit(self, raw_probs: np.ndarray | list[float], y_true: np.ndarray | list[int]) -> IsotonicProbabilityCalibrator:
        """Fit calibration on validation data strictly.

        Contingency:
        - If sample size < min_samples_for_isotonic or unique raw probabilities < 5:
          uses Platt scaling (logistic regression).
        - Otherwise, fits IsotonicRegression(out_of_bounds="clip").
        """
        raw = np.asarray(raw_probs, dtype=np.float64).ravel()
        labels = np.asarray(y_true, dtype=np.int32).ravel()

        if len(raw) != len(labels):
            raise ValueError(f"Length mismatch: {len(raw)} probs vs {len(labels)} labels")

        if len(raw) < 10:
            raise ValueError("Insufficient validation samples to fit any calibrator (< 10 samples).")

        unique_probs = np.unique(raw)

        # Decide whether to use Isotonic or Platt contingency
        if len(raw) < self.min_samples_for_isotonic or len(unique_probs) < 5:
            self._fit_platt(raw, labels)
        else:
            try:
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
                iso.fit(raw, labels)
                # Degeneracy check: If isotonic regression collapses into <= 2 discrete thresholds,
                # it acts as a hard binary gate (forcing all probabilities to strictly 0.0 or 1.0)
                # rather than providing smooth, continuous risk probabilities.
                # In this case, fall back to Platt scaling (logistic calibration).
                if hasattr(iso, "y_thresholds_") and len(np.unique(iso.y_thresholds_)) <= 2:
                    self._fit_platt(raw, labels)
                else:
                    self.calibrator = iso
                    self.method = "isotonic"
            except Exception:
                # Monotonicity failure or edge case: fall back to Platt
                self._fit_platt(raw, labels)

        self.is_fitted = True
        return self

    def _fit_platt(self, raw: np.ndarray, labels: np.ndarray) -> None:
        """Fit Platt scaling (logistic regression on logit/probability)."""
        # Guard logit against 0 or 1 boundaries
        clipped_raw = np.clip(raw, 1e-5, 1.0 - 1e-5)
        logits = np.log(clipped_raw / (1.0 - clipped_raw)).reshape(-1, 1)

        lr = LogisticRegression(C=1.0, solver="lbfgs")
        lr.fit(logits, labels)
        self.calibrator = lr
        self.method = "platt_logistic"

    def calibrate(self, raw_probs: np.ndarray | list[float] | float) -> np.ndarray | float:
        """Calibrate raw probability scores into validated risk probabilities in [0.0, 1.0]."""
        if not self.is_fitted or self.calibrator is None:
            raise RuntimeError("Calibrator is not fitted yet.")

        is_scalar = isinstance(raw_probs, (int, float, np.floating))
        arr = np.asarray([raw_probs] if is_scalar else raw_probs, dtype=np.float64)

        if self.method == "isotonic":
            calibrated = self.calibrator.predict(arr.ravel())
        elif self.method == "platt_logistic":
            clipped = np.clip(arr.ravel(), 1e-5, 1.0 - 1e-5)
            logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
            calibrated = self.calibrator.predict_proba(logits)[:, 1]
        else:
            raise ValueError(f"Unknown calibration method: {self.method}")

        # Strictly enforce bounds [0.0, 1.0]
        calibrated = np.clip(calibrated, 0.0, 1.0)

        if is_scalar:
            return float(calibrated[0])
        return calibrated

    def save(self, file_path: Path | str) -> None:
        """Save fitted calibrator to disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "calibrator": self.calibrator,
            "method": self.method,
            "min_samples": self.min_samples_for_isotonic,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, file_path: Path | str) -> IsotonicProbabilityCalibrator:
        """Load fitted calibrator from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Calibrator artifact not found at {path}")
        payload = joblib.load(path)
        if isinstance(payload, dict):
            instance = cls(min_samples_for_isotonic=payload.get("min_samples", 50))
            instance.calibrator = payload["calibrator"]
            instance.method = payload["method"]
            instance.is_fitted = True
            return instance
        elif isinstance(payload, IsotonicProbabilityCalibrator):
            return payload
        else:
            raise TypeError(f"Loaded artifact is not a valid calibrator payload: {type(payload)}")
