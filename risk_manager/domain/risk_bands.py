"""Centralized risk band mapping and boundary evaluation.

Implements TRD.md §Q, SPEC.md §18, and prompt requirement §4.
Centralizes policy-default risk bands:
- LOW:      0.00 <= p < 0.25
- MEDIUM:   0.25 <= p < 0.60
- HIGH:     0.60 <= p < 0.85
- CRITICAL: 0.85 <= p <= 1.00
"""

import math
from risk_manager.core.config import settings
from risk_manager.domain.schemas.enums import RiskBand


def map_probability_to_risk_band(p: float) -> RiskBand:
    """Map a calibrated risk probability into the authoritative RiskBand enum.

    Boundary Rules:
    - 0.00 <= p < 0.25 -> LOW
    - 0.25 <= p < 0.60 -> MEDIUM
    - 0.60 <= p < 0.85 -> HIGH
    - 0.85 <= p <= 1.00 -> CRITICAL

    Edge handling:
    - Floating point epsilon tolerance for exactly 1.0 or minor numeric drift.
    - Raises ValueError if p is NaN or outside [0.0, 1.0] beyond epsilon.
    """
    if math.isnan(p) or math.isinf(p):
        raise ValueError(f"Invalid probability value: {p}. Cannot map to RiskBand.")

    # Guard against minor floating point representation anomalies
    if -1e-9 <= p < 0.0:
        p = 0.0
    elif 1.0 < p <= 1.0 + 1e-9:
        p = 1.0

    if not (0.0 <= p <= 1.0):
        raise ValueError(f"Probability {p} is outside valid range [0.0, 1.0].")

    if p < settings.RISK_MEDIUM_THRESHOLD:
        return RiskBand.LOW
    elif p < settings.RISK_HIGH_THRESHOLD:
        return RiskBand.MEDIUM
    elif p < settings.RISK_CRITICAL_THRESHOLD:
        return RiskBand.HIGH
    else:
        return RiskBand.CRITICAL


def get_risk_band_thresholds() -> dict[str, float]:
    """Retrieve active risk band threshold configuration."""
    return {
        "LOW_UPPER": settings.RISK_MEDIUM_THRESHOLD,
        "MEDIUM_UPPER": settings.RISK_HIGH_THRESHOLD,
        "HIGH_UPPER": settings.RISK_CRITICAL_THRESHOLD,
        "CRITICAL_UPPER": 1.0,
    }
