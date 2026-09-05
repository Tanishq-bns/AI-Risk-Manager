"""LinUCB Disjoint Contextual Bandit for Intervention Selection.

Implements TRD.md §N, STATE.md ADR-005, and prompt requirements §9, §10, §12.
Balances exploitation (expected merchant net value) and exploration (upper confidence bound)
across canonical actions {A0, A1, A2, A3, A4}.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import joblib
import numpy as np

from risk_manager.core.config import settings
from risk_manager.domain.schemas.enums import Action, RiskBand
from risk_manager.features.schema import FeatureVector


class LinUCBPolicy:
    """Disjoint Linear Upper Confidence Bound (LinUCB) contextual bandit."""

    ACTIONS: list[Action] = [Action.A0, Action.A1, Action.A2, Action.A3, Action.A4]
    CONTEXT_DIM: int = 10

    def __init__(
        self,
        dimension: int = 10,
        alpha: float = settings.LINUCB_ALPHA,
        ridge_lambda: float = 1.0,
        exploration_enabled: bool = False,
    ) -> None:
        self.dimension: int = dimension
        self.alpha: float = alpha
        self.ridge_lambda: float = ridge_lambda
        self.exploration_enabled: bool = exploration_enabled
        self.model_version: str = "v1.0.0-linucb"

        # Initialize per-action ridge matrices and reward accumulators
        self.A: dict[Action, np.ndarray] = {
            a: self.ridge_lambda * np.eye(self.dimension, dtype=np.float64)
            for a in self.ACTIONS
        }
        self.b: dict[Action, np.ndarray] = {
            a: np.zeros((self.dimension, 1), dtype=np.float64)
            for a in self.ACTIONS
        }

    def construct_context_vector(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        p_return_abuse: float,
        risk_band: RiskBand,
    ) -> np.ndarray:
        """Construct normalized context vector x in R^d (TRD.md §N)."""
        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.model_dump()
        else:
            data = feature_vector

        try:
            order_val = float(data.get("order_value", 1000.0))
        except (ValueError, TypeError):
            order_val = 1000.0

        try:
            rev_cost = float(data.get("reverse_logistics_cost", 135.0))
        except (ValueError, TypeError):
            rev_cost = 135.0

        try:
            rec_val = float(data.get("estimated_item_recovery_value", 700.0))
        except (ValueError, TypeError):
            rec_val = 700.0

        try:
            ret_rate = float(data.get("customer_return_rate", 0.0))
        except (ValueError, TypeError):
            ret_rate = 0.0

        try:
            cod = 1.0 if bool(data.get("cod_flag", False)) else 0.0
        except (ValueError, TypeError):
            cod = 0.0

        try:
            days = float(data.get("days_since_purchase", 0))
        except (ValueError, TypeError):
            days = 0.0

        try:
            hist_abuse = float(data.get("historical_abuse_signal", 0.0))
        except (ValueError, TypeError):
            hist_abuse = 0.0

        # Map risk band to ordinal [0.0, 1.0]
        band_map = {
            RiskBand.LOW: 0.0,
            RiskBand.MEDIUM: 0.33,
            RiskBand.HIGH: 0.66,
            RiskBand.CRITICAL: 1.0,
        }
        band_val = band_map.get(risk_band, 0.5)

        x = np.array([
            p_return_abuse,
            band_val,
            min(1.0, max(0.0, order_val / 10000.0)),
            min(1.0, max(0.0, ret_rate)),
            min(1.0, max(0.0, rec_val / 10000.0)),
            min(1.0, max(0.0, rev_cost / 500.0)),
            cod,
            min(1.0, max(0.0, days / 30.0)),
            min(1.0, max(0.0, hist_abuse)),
            1.0,  # Bias intercept
        ], dtype=np.float64).reshape(-1, 1)

        return x

    def score_action(
        self,
        action: Action,
        context: np.ndarray,
    ) -> tuple[float, float, float]:
        """Compute LinUCB score for a single action.

        Returns:
            (total_score, predicted_reward, confidence_bonus)
        """
        ctx = np.asarray(context, dtype=np.float64).reshape(self.dimension, 1)
        A_inv = np.linalg.inv(self.A[action])
        theta = A_inv @ self.b[action]

        predicted_reward = float((theta.T @ ctx)[0, 0])
        var = float((ctx.T @ A_inv @ ctx)[0, 0])
        std = np.sqrt(max(0.0, var))

        bonus = (self.alpha * std) if self.exploration_enabled else 0.0
        total_score = predicted_reward + bonus

        return total_score, predicted_reward, bonus

    def select_action(
        self,
        context: np.ndarray,
        eligible_actions: list[Action],
        fallback_economic_priors: dict[Action, float] | None = None,
    ) -> tuple[Action, float, float]:
        """Select highest scoring eligible action.

        Returns:
            (selected_action, predicted_reward, confidence_bonus)
        """
        if not eligible_actions:
            raise ValueError("eligible_actions cannot be empty")

        best_action = eligible_actions[0]
        best_score = -float("inf")
        best_pred = 0.0
        best_bonus = 0.0

        for a in eligible_actions:
            score, pred, bonus = self.score_action(a, context)

            # If bandit has had zero updates (cold start), blend with economic prior
            if np.all(self.b[a] == 0.0) and fallback_economic_priors and a in fallback_economic_priors:
                # Prior normalized by 1000 INR
                prior_reward = fallback_economic_priors[a] / 1000.0
                score += prior_reward
                pred = prior_reward

            if score > best_score:
                best_score = score
                best_action = a
                best_pred = pred
                best_bonus = bonus

        return best_action, best_pred, best_bonus

    def update(self, action: Action, context: np.ndarray, reward: float) -> None:
        """Online update of ridge matrix and reward vector with realized reward."""
        if action not in self.A:
            raise ValueError(f"Unknown action: {action}")

        ctx = np.asarray(context, dtype=np.float64).reshape(self.dimension, 1)
        self.A[action] += ctx @ ctx.T
        self.b[action] += reward * ctx

    def save(self, file_path: Path | str) -> None:
        """Save bandit state to disk."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "A": self.A,
            "b": self.b,
            "dimension": self.dimension,
            "alpha": self.alpha,
            "ridge_lambda": self.ridge_lambda,
            "exploration_enabled": self.exploration_enabled,
            "model_version": self.model_version,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, file_path: Path | str) -> LinUCBPolicy:
        """Load bandit state from disk."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"LinUCB artifact not found at {path}")
        payload = joblib.load(path)
        instance = cls(
            dimension=payload.get("dimension", 10),
            alpha=payload.get("alpha", 0.25),
            ridge_lambda=payload.get("ridge_lambda", 1.0),
            exploration_enabled=payload.get("exploration_enabled", False),
        )
        instance.A = payload["A"]
        instance.b = payload["b"]
        instance.model_version = payload.get("model_version", "v1.0.0-linucb")
        return instance
