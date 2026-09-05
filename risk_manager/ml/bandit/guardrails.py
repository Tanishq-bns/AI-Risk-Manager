"""Hard policy guardrails and eligibility constraints.

Implements SPEC.md §14, TRD.md §Q, and prompt requirement §11.
Filters candidate interventions before bandit scoring.
Guarantees defensive safety, low-risk customer protection, and economic thresholds.
"""

from __future__ import annotations

from typing import Any

from risk_manager.core.config import settings
from risk_manager.domain.actions import ACTION_REGISTRY, get_action_metadata
from risk_manager.domain.schemas.economics import ActionEvaluation
from risk_manager.domain.schemas.enums import Action, RiskBand
from risk_manager.features.schema import FeatureVector


class PolicyGuardrails:
    """Evaluator for hard operational and economic guardrails."""

    def filter_eligible_actions(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        p_return_abuse: float,
        risk_band: RiskBand,
        evaluations: list[ActionEvaluation] | None = None,
        is_automated: bool = True,
    ) -> list[Action]:
        """Filter candidate actions to the safe, policy-compliant subset.

        Always guarantees at least Action.A0 (zero friction) is eligible.
        """
        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.model_dump()
        else:
            data = feature_vector

        try:
            order_val = float(data.get("order_value", 0.0))
        except (ValueError, TypeError):
            order_val = 0.0
        eval_map = {e.action: e for e in evaluations} if evaluations else {}

        eligible_actions: list[Action] = []

        for action_enum in [Action.A0, Action.A1, Action.A2, Action.A3, Action.A4]:
            meta = get_action_metadata(action_enum)

            # Rule 1: A0 is always structurally eligible
            if action_enum == Action.A0:
                eligible_actions.append(action_enum)
                continue

            # Rule 2: Low-risk customers must receive zero friction (SPEC.md §14)
            if risk_band == RiskBand.LOW:
                continue

            # Rule 3: Automated execution gate
            if is_automated and not meta.is_automated_allowed:
                # A4 requires human approval; disallow from purely automated settlement
                continue

            # Rule 4: Minimum order value threshold
            if order_val < meta.min_order_value:
                continue

            # Rule 5: Risk band eligibility
            if risk_band not in meta.allowed_risk_bands:
                continue

            # Rule 6: Economic threshold (TRD.md §Q / SPEC.md §14)
            # An intervention is disqualified if its expected net value is negative
            if action_enum in eval_map:
                net_val = eval_map[action_enum].expected_net_value
                if net_val < 0.0:
                    continue

            # Rule 7: Product category constraints (G05)
            cat = str(data.get("product_category", "")).upper()
            if cat in ("BEAUTY", "PERSONAL_CARE") and action_enum == Action.A2:
                continue

            eligible_actions.append(action_enum)

        # Fallback guarantee: A0 is always present
        if Action.A0 not in eligible_actions:
            eligible_actions.insert(0, Action.A0)

        return eligible_actions
