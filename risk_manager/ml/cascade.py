"""ML Scoring Cascade Orchestrator (Tier 0 -> Tier 1 -> Tier 2).

Implements ARCHITECTURE.md §6/§7, TRD.md §K, and prompt requirement §7.
Guarantees graceful degradation under:
- Feature incompleteness (< 0.85)
- Open circuit breaker (>= 5 failures in 30s)
- Missing model or preprocessor artifacts
- Incompatible feature schema
- Inference timeouts (> 100ms)
- Runtime inference exceptions
- Tier 1 failure -> Tier 2 Rules Engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from risk_manager.core.config import settings
from risk_manager.domain.risk_bands import map_probability_to_risk_band
from risk_manager.domain.schemas.enums import FallbackTier, RiskBand, ScoringSource
from risk_manager.features.completeness import FeatureCompletenessReport, evaluate_feature_completeness
from risk_manager.features.schema import FeatureVector
from risk_manager.ml.isolation_forest.model import Tier1IsolationForest
from risk_manager.ml.rules_engine.rules import Tier2RulesEngine
from risk_manager.ml.xgboost_model.infer import Tier0Predictor


@dataclass
class CascadeResult:
    """Authoritative result from the ML Scoring Cascade."""

    p_return_abuse: float
    risk_band: RiskBand
    scoring_source: ScoringSource
    fallback_tier: FallbackTier
    fallback_reason: str | None
    model_version: str
    feature_schema_version: str
    raw_score: float | None = None
    anomaly_score: float | None = None
    triggered_rules: list[str] = field(default_factory=list)
    rule_explanations: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


class CircuitBreaker:
    """In-process circuit breaker for Tier 0 ML inference."""

    def __init__(
        self,
        failure_threshold: int = settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        open_seconds: int = settings.CIRCUIT_BREAKER_OPEN_SECONDS,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def is_open(self) -> bool:
        """Check if circuit breaker is open (bypassing primary model)."""
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_failure_time >= self.open_seconds:
                self.state = "HALF_OPEN"
                return False
            return True
        return False

    def record_success(self) -> None:
        """Reset failure counter upon successful execution."""
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        """Increment failure counter and transition to OPEN if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


class MLCascadeScorer:
    """Three-tier defensive ML scoring cascade: Tier 0 -> Tier 1 -> Tier 2."""

    def __init__(
        self,
        models_dir: Path | str = settings.ML_MODELS_DIR,
        timeout_ms: float = settings.MODEL_INFERENCE_TIMEOUT_MS,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.timeout_ms = timeout_ms

        self.tier0: Tier0Predictor = Tier0Predictor(models_dir=self.models_dir)
        self.tier1: Tier1IsolationForest | None = None
        self.tier2: Tier2RulesEngine = Tier2RulesEngine()
        self.circuit_breaker: CircuitBreaker = CircuitBreaker()

        self._init_models()

    def _init_models(self) -> None:
        """Attempt to load Tier 0 and Tier 1 models from disk without throwing."""
        try:
            self.tier0.load()
        except Exception:
            # Tier 0 remains unloaded; cascade will gracefully fall back
            pass

        try:
            iforest_path = self.models_dir / "isolation_forest.joblib"
            encoder_path = self.models_dir / "preprocessor.joblib"
            if iforest_path.exists():
                self.tier1 = Tier1IsolationForest.load(iforest_path, encoder_path=encoder_path)
        except Exception:
            self.tier1 = None

    def score(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        completeness_report: FeatureCompletenessReport | None = None,
    ) -> CascadeResult:
        """Execute the scoring cascade.

        Cascade Flow:
        1. Check feature completeness ratio >= 0.85
        2. Check circuit breaker status
        3. Attempt Tier 0 (XGBoost + Isotonic Calibrator)
        4. On failure/timeout/bypass -> Attempt Tier 1 (Isolation Forest)
        5. On Tier 1 failure/unavailable -> Execute Tier 2 (Rules Engine)
        """
        t_start = time.perf_counter()

        # Step 1: Feature completeness validation
        if completeness_report is None:
            completeness_report = evaluate_feature_completeness(feature_vector)

        if completeness_report.completeness_ratio < settings.FEATURE_COMPLETENESS_MIN_RATIO:
            return self._fallback_to_tier1(
                feature_vector=feature_vector,
                reason=f"INSUFFICIENT_FEATURE_COMPLETENESS (ratio={completeness_report.completeness_ratio:.2f})",
                t_start=t_start,
            )

        # Step 2: Circuit breaker check
        if self.circuit_breaker.is_open():
            return self._fallback_to_tier1(
                feature_vector=feature_vector,
                reason="CIRCUIT_BREAKER_OPEN",
                t_start=t_start,
            )

        # Step 3: Attempt Tier 0
        if not self.tier0.is_loaded:
            return self._fallback_to_tier1(
                feature_vector=feature_vector,
                reason="ARTIFACT_LOAD_FAILURE (Tier 0 model or calibrator not loaded)",
                t_start=t_start,
            )

        try:
            t0_start = time.perf_counter()
            cal_prob, raw_prob, t0_latency_ms = self.tier0.predict_one(feature_vector)

            # Enforce timeout budget
            if t0_latency_ms > self.timeout_ms:
                self.circuit_breaker.record_failure()
                return self._fallback_to_tier1(
                    feature_vector=feature_vector,
                    reason=f"INFERENCE_TIMEOUT ({t0_latency_ms:.1f}ms > {self.timeout_ms}ms)",
                    t_start=t_start,
                )

            # Validate probability bounds
            if not (0.0 <= cal_prob <= 1.0):
                self.circuit_breaker.record_failure()
                return self._fallback_to_tier1(
                    feature_vector=feature_vector,
                    reason=f"INVALID_MODEL_OUTPUT (p={cal_prob})",
                    t_start=t_start,
                )

            # Success path: Tier 0 completed
            self.circuit_breaker.record_success()
            total_latency = (time.perf_counter() - t_start) * 1000.0
            risk_band = map_probability_to_risk_band(cal_prob)

            return CascadeResult(
                p_return_abuse=round(cal_prob, 4),
                risk_band=risk_band,
                scoring_source=ScoringSource.XGBOOST,
                fallback_tier=FallbackTier.TIER_0,
                fallback_reason=None,
                model_version=self.tier0.model_version,
                feature_schema_version=self.tier0.feature_schema_version,
                raw_score=round(raw_prob, 4),
                anomaly_score=None,
                latency_ms=round(total_latency, 2),
            )

        except Exception as e:
            self.circuit_breaker.record_failure()
            return self._fallback_to_tier1(
                feature_vector=feature_vector,
                reason=f"INFERENCE_EXCEPTION: {type(e).__name__}: {str(e)}",
                t_start=t_start,
            )

    def _fallback_to_tier1(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        reason: str,
        t_start: float,
    ) -> CascadeResult:
        """Execute Tier 1 (Isolation Forest) fallback."""
        if self.tier1 is None or not self.tier1.is_loaded:
            return self._fallback_to_tier2(
                feature_vector=feature_vector,
                reason=f"{reason} -> TIER_1_UNAVAILABLE",
                t_start=t_start,
            )

        try:
            anomaly_proxy, raw_anomaly_score = self.tier1.score_one(feature_vector)
            risk_band = map_probability_to_risk_band(anomaly_proxy)
            total_latency = (time.perf_counter() - t_start) * 1000.0

            return CascadeResult(
                p_return_abuse=round(anomaly_proxy, 4),
                risk_band=risk_band,
                scoring_source=ScoringSource.ISOLATION_FOREST,
                fallback_tier=FallbackTier.TIER_1,
                fallback_reason=reason,
                model_version=self.tier1.model_version,
                feature_schema_version=self.tier1.feature_schema_version,
                raw_score=None,
                anomaly_score=round(raw_anomaly_score, 4),
                latency_ms=round(total_latency, 2),
            )

        except Exception as e:
            return self._fallback_to_tier2(
                feature_vector=feature_vector,
                reason=f"{reason} -> TIER_1_EXCEPTION: {type(e).__name__}: {str(e)}",
                t_start=t_start,
            )

    def _fallback_to_tier2(
        self,
        feature_vector: FeatureVector | dict[str, Any],
        reason: str,
        t_start: float,
    ) -> CascadeResult:
        """Execute Tier 2 (Rules Engine) final conservative fallback."""
        rules_res = self.tier2.evaluate(feature_vector)
        total_latency = (time.perf_counter() - t_start) * 1000.0

        return CascadeResult(
            p_return_abuse=rules_res.p_return_abuse,
            risk_band=rules_res.risk_band,
            scoring_source=ScoringSource.RULES,
            fallback_tier=FallbackTier.TIER_2,
            fallback_reason=reason,
            model_version="v1.0.0-rules",
            feature_schema_version="v1",
            raw_score=None,
            anomaly_score=None,
            triggered_rules=rules_res.triggered_rules,
            rule_explanations=rules_res.rule_explanations,
            latency_ms=round(total_latency, 2),
        )
