"""Feature engineering, schema, and completeness evaluation package."""

from risk_manager.features.completeness import (
    CompletenessReport,
    evaluate_feature_completeness,
)
from risk_manager.features.pipeline import (
    HistoricalOrderContext,
    HistoricalReturnContext,
    calculate_feature_vector,
    extract_features_from_db,
)
from risk_manager.features.schema import FeatureVector, OutcomeLabel

__all__ = [
    "FeatureVector",
    "OutcomeLabel",
    "CompletenessReport",
    "evaluate_feature_completeness",
    "calculate_feature_vector",
    "extract_features_from_db",
    "HistoricalOrderContext",
    "HistoricalReturnContext",
]
