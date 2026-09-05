"""Policy Engine orchestrator integrating economics, guardrails, LinUCB, and fallbacks.

Implements TRD.md §C/§E/§N/§O, SPEC.md §14, and prompt requirements §1, §9, §11, §13, §14.
Produces auditable PolicyDecisionContext and domain response DTOs.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any
from uuid import UUID, uuid4

from risk_manager.core.config import settings
from risk_manager.domain.actions import get_action_metadata
from risk_manager.domain.schemas.economics import ActionEvaluation, PolicyDecisionContext
from risk_manager.domain.schemas.enums import Action, ActionSelector, RiskBand
from risk_manager.domain.schemas.responses import EconomicPrediction, InterventionCandidate
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.bandit.fallback import DeterministicPolicyFallback
from risk_manager.ml.bandit.guardrails import PolicyGuardrails
from risk_manager.ml.bandit.linucb import LinUCBPolicy
from risk_manager.ml.reward_model.predict import EconomicPredictor


class PolicyEngine:
    """Intervention policy engine selecting the optimal, policy-safe intervention."""

    def __init__(
        self,
        models_dir: Path | str = "models",
        exploration_enabled: bool = False,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.economic_predictor = EconomicPredictor(models_dir=self.models_dir)
        self.bandit = LinUCBPolicy(exploration_enabled=exploration_enabled)
        self.guardrails = PolicyGuardrails()
        self.fallback = DeterministicPolicyFallback()

        self._init_models()

    def _init_models(self) -> None:
        """Attempt to load economic and bandit models without crashing."""
        try:
            self.economic_predictor.load()
        except Exception:
            # Predictor operates in analytical fallback mode
            pass

        try:
            bandit_path = self.models_dir / "linucb_state.joblib"
            if bandit_path.exists():
                self.bandit = LinUCBPolicy.load(bandit_path)
        except Exception:
            pass

    def evaluate_policy(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        p_return_abuse: float,
        risk_band: RiskBand,
        risk_decision_id: UUID | None = None,
        is_automated: bool = True,
    ) -> PolicyDecisionContext:
        """Execute intervention policy evaluation pipeline.

        Pipeline:
        1. Evaluate candidate economics {A0-A4}
        2. Apply policy guardrails and eligibility constraints
        3. Score eligible actions via LinUCB
        4. On LinUCB failure, execute deterministic fallback
        5. Assemble auditable PolicyDecisionContext
        """
        import math

        if risk_decision_id is None:
            risk_decision_id = uuid4()

        # Sanitize and clamp p_return_abuse safely
        if math.isnan(p_return_abuse) or math.isinf(p_return_abuse):
            p_return_abuse = 0.5
        p_return_abuse = max(0.0, min(1.0, float(p_return_abuse)))

        # Step 1: Economic evaluations across action space
        try:
            evaluations = self.economic_predictor.evaluate_all_actions(feature_vector, p_return_abuse)
        except Exception:
            # Analytical baseline fallback
            evaluations = []
            for a in [Action.A0, Action.A1, Action.A2, Action.A3, Action.A4]:
                meta = get_action_metadata(a)
                evaluations.append(
                    ActionEvaluation(
                        action=a,
                        action_name=meta.action_name,
                        expected_loss=0.0,
                        expected_net_value=0.0,
                        friction_cost=meta.customer_friction_cost,
                        operational_cost=meta.merchant_operational_cost,
                        is_eligible=True,
                    )
                )

        # Step 2: Policy guardrails filtering
        eligible_actions = self.guardrails.filter_eligible_actions(
            feature_vector=feature_vector,
            p_return_abuse=p_return_abuse,
            risk_band=risk_band,
            evaluations=evaluations,
            is_automated=is_automated,
        )

        # Update evaluation eligibility markers
        guardrails_applied: list[str] = []
        for e in evaluations:
            if e.action not in eligible_actions:
                e.is_eligible = False
                e.ineligibility_reason = f"Filtered by guardrails (RiskBand={risk_band})"
                guardrails_applied.append(f"{e.action.value}_INELIGIBLE")

        # Step 3: LinUCB selection among eligible actions
        fallback_priors = {e.action: e.expected_net_value for e in evaluations}

        try:
            context_vec = self.bandit.construct_context_vector(feature_vector, p_return_abuse, risk_band)
            selected_action, pred_reward, bonus = self.bandit.select_action(
                context=context_vec,
                eligible_actions=eligible_actions,
                fallback_economic_priors=fallback_priors,
            )
            selector = ActionSelector.LINUCB
            fallback_reason = None
            meta = get_action_metadata(selected_action)

        except Exception as e:
            # Step 4: Deterministic fallback if LinUCB fails
            selected_action, rationale = self.fallback.select_fallback_action(
                feature_vector=feature_vector,
                p_return_abuse=p_return_abuse,
                risk_band=risk_band,
                eligible_actions=eligible_actions,
                evaluations=evaluations,
                reason=f"LINUCB_EXCEPTION: {type(e).__name__}",
            )
            selector = ActionSelector.RULES
            pred_reward = 0.0
            bonus = 0.0
            fallback_reason = str(e)
            meta = get_action_metadata(selected_action)

        # Retrieve expected net value for chosen action
        chosen_eval = next((e for e in evaluations if e.action == selected_action), None)
        net_val = chosen_eval.expected_net_value if chosen_eval else 0.0

        return PolicyDecisionContext(
            risk_decision_id=risk_decision_id,
            p_return_abuse=p_return_abuse,
            risk_band=risk_band,
            action_selected=selected_action,
            action_selector=selector,
            candidate_actions=evaluations,
            expected_net_value=net_val,
            reward_estimate=pred_reward,
            exploration_bonus=bonus,
            policy_model_version=self.bandit.model_version,
            guardrails_applied=guardrails_applied,
            fallback_reason=fallback_reason,
        )

    def to_domain_response(
        self,
        policy_context: PolicyDecisionContext,
    ) -> tuple[InterventionCandidate, EconomicPrediction]:
        """Convert policy context into InterventionCandidate and EconomicPrediction DTOs."""
        meta = get_action_metadata(policy_context.action_selected)

        chosen_eval = next(
            (e for e in policy_context.candidate_actions if e.action == policy_context.action_selected),
            None,
        )
        no_action_eval = next(
            (e for e in policy_context.candidate_actions if e.action == Action.A0),
            None,
        )

        loss_no_action = no_action_eval.expected_loss if no_action_eval else 0.0
        loss_with_action = chosen_eval.expected_loss if chosen_eval else 0.0
        net_value = policy_context.expected_net_value

        candidate = InterventionCandidate(
            action=policy_context.action_selected,
            selected_by=policy_context.action_selector,
            rationale=(
                f"{meta.action_name} selected by {policy_context.action_selector.value} "
                f"(ExpectedNetValue=INR {net_value:.2f}, RiskBand={policy_context.risk_band.value})"
            ),
        )

        prediction = EconomicPrediction(
            expected_loss_no_action=loss_no_action,
            expected_loss_with_action=loss_with_action,
            expected_net_value=net_value,
        )

        return candidate, prediction
