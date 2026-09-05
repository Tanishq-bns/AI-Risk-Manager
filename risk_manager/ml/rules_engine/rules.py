"""Deterministic conservative Rules Engine for Tier 2 fallback scoring.

Implements STATE.md ADR-004, TRD.md §I/§K, and prompt requirement §6.
Activated strictly when both Tier 0 and Tier 1 ML pipelines are degraded/unavailable.
Provides explainable, auditable, conservative heuristic decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from risk_manager.domain.risk_bands import map_probability_to_risk_band
from risk_manager.domain.schemas.enums import FallbackTier, RiskBand, ScoringSource
from risk_manager.features.schema import FeatureVector


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    description: str
    risk_score: float
    risk_band: RiskBand


@dataclass
class RulesEngineResult:
    p_return_abuse: float
    risk_band: RiskBand
    scoring_source: ScoringSource
    fallback_tier: FallbackTier
    triggered_rules: list[str]
    rule_explanations: list[str]


class Tier2RulesEngine:
    """Deterministic, conservative heuristic rules engine for Tier 2 fallback."""

    def evaluate(self, feature_vector: FeatureVector | dict[str, Any]) -> RulesEngineResult:
        """Evaluate input features against conservative rules.

        Returns highest risk score among all matching rules.
        If no specific rule triggers, applies conservative default R08.
        """
        if isinstance(feature_vector, FeatureVector):
            data = feature_vector.model_dump()
        else:
            data = feature_vector

        order_val = float(data.get("order_value", 0.0))
        cod_flag = bool(data.get("cod_flag", False))
        order_count = int(data.get("customer_order_count", 0))
        return_count = int(data.get("customer_return_count", 0))
        return_rate = float(data.get("customer_return_rate", 0.0))
        days_since_purchase = int(data.get("days_since_purchase", 0))
        prior_ret_freq = float(data.get("prior_return_frequency", 0.0))
        hist_abuse = float(data.get("historical_abuse_signal", 0.0))
        category = str(data.get("product_category", "")).upper()

        triggered: list[RuleDefinition] = []

        # R02: Confirmed historical abuse
        if hist_abuse >= 0.50:
            triggered.append(RuleDefinition(
                rule_id="R02_HISTORICAL_ABUSE_FLAG",
                description="Customer has confirmed prior return abuse incidents on record.",
                risk_score=0.85,
                risk_band=RiskBand.CRITICAL,
            ))

        # R01: Excessive serial return rate
        if order_count >= 3 and return_rate >= 0.65:
            triggered.append(RuleDefinition(
                rule_id="R01_HIGH_RETURN_VELOCITY",
                description=f"Customer historical return rate is excessive ({return_rate*100:.1f}% across {order_count} orders).",
                risk_score=0.75,
                risk_band=RiskBand.HIGH,
            ))

        # R05: High value combined with high return frequency
        if order_val >= 6000.0 and prior_ret_freq >= 1.0:
            triggered.append(RuleDefinition(
                rule_id="R05_HIGH_VALUE_HIGH_VELOCITY",
                description=f"High-value return (₹{order_val:.2f}) with frequent return velocity ({prior_ret_freq:.2f}/30d).",
                risk_score=0.70,
                risk_band=RiskBand.HIGH,
            ))

        # R03: COD doorstep return speed
        if cod_flag and return_rate >= 0.50 and days_since_purchase <= 3:
            triggered.append(RuleDefinition(
                rule_id="R03_COD_DOORSTEP_REFUSAL",
                description="Rapid return on Cash-on-Delivery order with elevated prior return history.",
                risk_score=0.65,
                risk_band=RiskBand.HIGH,
            ))

        # R04: Wardrobing pattern at policy limit
        if days_since_purchase >= 12 and category in {"APPAREL", "FOOTWEAR"} and order_val >= 3500.0:
            triggered.append(RuleDefinition(
                rule_id="R04_WARDROBING_EDGE",
                description=f"High-value {category} return filed near policy window edge ({days_since_purchase} days).",
                risk_score=0.65,
                risk_band=RiskBand.HIGH,
            ))

        # R06: New customer high-value return (defensive posture during outage)
        if order_count <= 1 and order_val >= 5000.0:
            triggered.append(RuleDefinition(
                rule_id="R06_NEW_CUSTOMER_DEFENSIVE",
                description=f"Conservative evaluation: high-value first-time order return (₹{order_val:.2f}) during degraded operation.",
                risk_score=0.40,
                risk_band=RiskBand.MEDIUM,
            ))

        # R07: Established low-risk customer
        if order_count >= 3 and return_rate <= 0.15 and hist_abuse == 0.0:
            triggered.append(RuleDefinition(
                rule_id="R07_CLEAN_CUSTOMER_PROTECTIVE",
                description=f"Protective rule: established customer ({order_count} orders, {return_rate*100:.1f}% return rate, clean history).",
                risk_score=0.10,
                risk_band=RiskBand.LOW,
            ))

        # If no specific rule triggered, apply conservative default
        if not triggered:
            final_rule = RuleDefinition(
                rule_id="R08_DEFAULT_CONSERVATIVE",
                description="Conservative baseline applied during total ML degradation.",
                risk_score=0.35,
                risk_band=RiskBand.MEDIUM,
            )
            rule_ids = [final_rule.rule_id]
            rule_explanations = [final_rule.description]
            final_score = final_rule.risk_score
        else:
            # Sort by risk score descending: highest risk rule takes precedence
            triggered.sort(key=lambda r: r.risk_score, reverse=True)
            final_score = triggered[0].risk_score
            rule_ids = [r.rule_id for r in triggered]
            rule_explanations = [r.description for r in triggered]

        band = map_probability_to_risk_band(final_score)

        return RulesEngineResult(
            p_return_abuse=round(final_score, 4),
            risk_band=band,
            scoring_source=ScoringSource.RULES,
            fallback_tier=FallbackTier.TIER_2,
            triggered_rules=rule_ids,
            rule_explanations=rule_explanations,
        )
