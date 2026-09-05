"""Calibration diagnostics and evaluation metrics.

Calculates Brier score, Expected Calibration Error (ECE), and reliability curve points.
Implements TRD.md §I and prompt requirement §3.
"""

from typing import Any
import numpy as np
from sklearn.metrics import brier_score_loss


def calculate_ece(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, list[dict[str, float]]]:
    """Calculate Expected Calibration Error (ECE) and reliability curve bin metrics."""
    y_true = np.asarray(y_true, dtype=np.int32)
    y_prob = np.asarray(y_prob, dtype=np.float64)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_details: list[dict[str, float]] = []
    total_samples = len(y_true)
    weighted_error_sum = 0.0

    for i in range(n_bins):
        bin_lower = bin_edges[i]
        bin_upper = bin_edges[i + 1]

        if i == n_bins - 1:
            in_bin = (y_prob >= bin_lower) & (y_prob <= bin_upper)
        else:
            in_bin = (y_prob >= bin_lower) & (y_prob < bin_upper)

        bin_count = int(np.sum(in_bin))
        if bin_count > 0:
            bin_acc = float(np.mean(y_true[in_bin]))
            bin_conf = float(np.mean(y_prob[in_bin]))
            bin_error = abs(bin_acc - bin_conf)
            weighted_error_sum += (bin_count / total_samples) * bin_error

            bin_details.append({
                "bin_index": i,
                "bin_lower": round(bin_lower, 4),
                "bin_upper": round(bin_upper, 4),
                "bin_center": round((bin_lower + bin_upper) / 2.0, 4),
                "sample_count": bin_count,
                "empirical_accuracy": round(bin_acc, 4),
                "mean_confidence": round(bin_conf, 4),
                "calibration_error": round(bin_error, 4),
            })

    ece = round(weighted_error_sum, 6)
    return ece, bin_details


def evaluate_calibration(
    y_true: np.ndarray | list[int],
    y_prob: np.ndarray | list[float],
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute complete calibration diagnostic report."""
    y_t = np.asarray(y_true, dtype=np.int32)
    y_p = np.asarray(y_prob, dtype=np.float64)

    brier = float(brier_score_loss(y_t, y_p))
    ece, bins = calculate_ece(y_t, y_p, n_bins=n_bins)

    max_cal_error = max((b["calibration_error"] for b in bins), default=0.0)

    return {
        "brier_score": round(brier, 6),
        "expected_calibration_error": ece,
        "max_calibration_error": round(max_cal_error, 6),
        "reliability_bins": bins,
    }
