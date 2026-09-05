"""Deterministic rule-based policy fallback when LinUCB is degraded or fails.

Implements STATE.md ADR-004, TRD.md §C/§K, and prompt requirement §13.
Guarantees a safe, deterministic, explainable intervention is ALWAYS selected.
"""

from __future__ import annotations

from typing import Any

from risk_manager.domain.schemas.economics import ActionEvaluation
from risk_manager.domain.schemas.enums import Action, RiskBand
from risk_manager.features.schema import FeatureVector


class DeterministicPolicyFallback:
    """Fallback policy selector choosing the safest eligible intervention."""

    def select_fallback_action(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        p_return_abuse: float,
        risk_band: RiskBand,
        eligible_actions: list[Action],
        evaluations: list[ActionEvaluation] | None = None,
        reason: str = "LINUCB_FALLBACK",
    ) -> tuple[Action, str]:
        """Select action deterministically based on risk band and economics.

        Returns:
            (selected_action, rationale)
        """
        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.model_dump()
        else:
            data = feature_vector

        try:
            order_val = float(data.get("order_value", 0.0))
        except (ValueError, TypeError):
            order_val = 0.0

        # 1. Economic priority: If evaluations exist, pick the eligible action with highest net value
        if evaluations:
            eligible_evals = [e for e in evaluations if e.action in eligible_actions and e.expected_net_value > 0.0]
            if eligible_evals:
                best_eval = max(eligible_evals, key=lambda e: e.expected_net_value)
                return best_eval.action, f"Deterministic economic fallback: highest net value (₹{best_eval.expected_net_value:.2f}) due to {reason}"

        # 2. Rule-based heuristic hierarchy if economic model is absent/degenerate
        if risk_band == RiskBand.LOW or (0.0 < order_val < 100.0):
            return Action.A0, f"Rule fallback: Low risk ({risk_band}) or low value (₹{order_val:.2f}) default to zero friction."

        if risk_band == RiskBand.MEDIUM:
            if Action.A1 in eligible_actions:
                return Action.A1, f"Rule fallback: Medium risk fee mitigation due to {reason}."
            elif Action.A3 in eligible_actions:
                return Action.A3, f"Rule fallback: Medium risk store credit due to {reason}."
            return Action.A0, f"Rule fallback: Medium risk default to A0."

        if risk_band == RiskBand.HIGH:
            if Action.A2 in eligible_actions:
                return Action.A2, f"Rule fallback: High risk doorstep OTP inspection due to {reason}."
            elif Action.A1 in eligible_actions:
                return Action.A1, f"Rule fallback: High risk fee mitigation due to {reason}."
            return Action.A0, f"Rule fallback: High risk default to A0."

        if risk_band == RiskBand.CRITICAL:
            if order_val >= 5000.0 and Action.A4 in eligible_actions:
                return Action.A4, f"Rule fallback: Critical risk high-value manual review due to {reason}."
            if Action.A2 in eligible_actions:
                return Action.A2, f"Rule fallback: Critical risk doorstep OTP verification due to {reason}."
            if Action.A1 in eligible_actions:
                return Action.A1, f"Rule fallback: Critical risk fee mitigation due to {reason}."

        # Ultimate safety fallback
        return Action.A0, f"Rule fallback: Ultimate defensive baseline A0 due to {reason}."
