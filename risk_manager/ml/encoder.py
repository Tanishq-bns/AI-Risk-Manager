"""Deterministic feature encoder and preprocessor for ML scoring models.

Transforms strongly-typed FeatureVector representations into numerical matrices.
Fitted strictly on training data; unseen categories at test/inference time
gracefully map to all-zeros via handle_unknown='ignore'.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import OneHotEncoder

from risk_manager.features.schema import FeatureVector


class FeatureEncoder:
    """Deterministic tabular preprocessor for return abuse ML scoring.

    Attributes:
        NUMERIC_COLS: 12 continuous and discrete numeric features.
        CATEGORICAL_COLS: 4 categorical and structured text features.
    """

    NUMERIC_COLS: list[str] = [
        "order_value",
        "cod_flag",
        "customer_order_count",
        "customer_return_count",
        "customer_return_rate",
        "days_since_purchase",
        "prior_return_value",
        "prior_return_frequency",
        "item_category_return_rate",
        "reverse_logistics_cost",
        "estimated_item_recovery_value",
        "historical_abuse_signal",
    ]

    CATEGORICAL_COLS: list[str] = [
        "product_category",
        "payment_method",
        "delivery_distance_bucket",
        "return_reason",
    ]

    def __init__(self) -> None:
        self.ohe: OneHotEncoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        self.is_fitted: bool = False
        self.feature_names_out_: list[str] = []
        self.cat_feature_names_: list[str] = []

    def _prepare_df(self, data: pd.DataFrame | dict[str, Any] | FeatureVector | list[dict[str, Any]]) -> pd.DataFrame:
        """Standardize inputs into a validated DataFrame."""
        if isinstance(data, FeatureVector):
            records = [data.to_model_features()]
            df = pd.DataFrame(records)
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data.copy()
        else:
            raise TypeError(f"Unsupported data type for FeatureEncoder: {type(data)}")

        # Clean categorical columns: strip and uppercase for deterministic matching
        for col in self.CATEGORICAL_COLS:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.upper()
            else:
                df[col] = "UNKNOWN"

        # Coerce numeric columns
        for col in self.NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            else:
                df[col] = 0.0

        return df

    def fit(self, df: pd.DataFrame) -> FeatureEncoder:
        """Fit the encoder strictly on training data."""
        clean_df = self._prepare_df(df)
        cat_data = clean_df[self.CATEGORICAL_COLS]
        self.ohe.fit(cat_data)
        self.cat_feature_names_ = list(self.ohe.get_feature_names_out(self.CATEGORICAL_COLS))
        self.feature_names_out_ = self.NUMERIC_COLS + self.cat_feature_names_
        self.is_fitted = True
        return self

    def transform(self, data: pd.DataFrame | dict[str, Any] | FeatureVector | list[dict[str, Any]]) -> np.ndarray:
        """Transform features into a 2D numpy matrix matching feature_names_out_ ordering."""
        if not self.is_fitted:
            raise RuntimeError("FeatureEncoder is not fitted yet. Call fit() first.")

        clean_df = self._prepare_df(data)
        num_part = clean_df[self.NUMERIC_COLS].to_numpy(dtype=np.float32)
        cat_part = self.ohe.transform(clean_df[self.CATEGORICAL_COLS]).astype(np.float32)

        return np.hstack([num_part, cat_part])

    def fit_transform(self, df: pd.DataFrame) -> np.ndarray:
        """Fit on training data and return transformed numeric matrix."""
        return self.fit(df).transform(df)

    def get_feature_names_out(self) -> list[str]:
        """Return the final list of encoded column names."""
        if not self.is_fitted:
            raise RuntimeError("FeatureEncoder is not fitted yet.")
        return list(self.feature_names_out_)

    def save(self, file_path: Path | str) -> None:
        """Serialize fitted encoder to disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ohe": self.ohe,
            "is_fitted": self.is_fitted,
            "feature_names_out": self.feature_names_out_,
            "cat_feature_names": self.cat_feature_names_,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, file_path: Path | str) -> FeatureEncoder:
        """Load serialized encoder from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"FeatureEncoder artifact not found at {path}")
        payload = joblib.load(path)
        if isinstance(payload, dict):
            instance = cls()
            instance.ohe = payload["ohe"]
            instance.is_fitted = payload["is_fitted"]
            instance.feature_names_out_ = payload["feature_names_out"]
            instance.cat_feature_names_ = payload["cat_feature_names"]
            return instance
        elif isinstance(payload, FeatureEncoder):
            return payload
        else:
            raise TypeError(f"Loaded artifact is not a valid FeatureEncoder payload: {type(payload)}")
