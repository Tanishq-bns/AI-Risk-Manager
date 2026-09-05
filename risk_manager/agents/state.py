"""LangGraph workflow state definition.

Implements TRD.md §M and Phase 6 LangGraph State specification.
Strictly encapsulates immutable numerical inputs from Phase 4 & 5 alongside
accumulated agent reasoning artifacts.
"""

from typing import Any, TypedDict
from uuid import UUID

from risk_manager.domain.schemas.agents import (
    ActionDecision,
    InvestigationResult,
    VerificationResult,
)
from risk_manager.domain.schemas.enums import (
    Action,
    AgentRunStatus,
    RiskBand,
    ScoringSource,
)


class AgentGraphState(TypedDict, total=False):
    """Strongly typed LangGraph state dictionary.

    Authoritative Read-Only numerical fields from Phase 4 & Phase 5:
    - decision_id: UUID of overall request/evaluation
    - risk_decision_id: UUID of Phase 4 RiskDecision
    - policy_decision_id: UUID of Phase 5 PolicyDecision
    - p_return_abuse: float in [0, 1]
    - risk_band: str / RiskBand
    - scoring_source: str / ScoringSource
    - fallback_tier: int (0=XGBoost, 1=Isolation Forest, 2=Rules)
    - selected_action: Action (canonical A0-A4)
    - action_selector: str (LINUCB, RULES, etc.)
    - expected_loss: float
    - expected_net_value: float
    - guardrails_applied: list[str]
    """

    # Identifiers & Correlation
    decision_id: UUID
    risk_decision_id: UUID
    policy_decision_id: UUID
    trace_id: str

    # Read-Only Numerical Risk Decision (Phase 4 Authority)
    p_return_abuse: float
    risk_band: str
    scoring_source: str
    fallback_tier: int

    # Read-Only Economic & Policy Decision (Phase 5 Authority)
    selected_action: Action
    action_selector: str
    expected_loss: float
    expected_net_value: float
    candidate_actions: list[dict[str, Any]]
    guardrails_applied: list[str]
    economic_predictions: dict[str, Any]

    # Contextual Evidence & Telemetry (Untrusted Customer Data Boundary)
    feature_evidence: dict[str, Any]
    customer_history: dict[str, Any]
    model_metadata: dict[str, Any]

    # Agent Structured Outputs (Phase 6 Enrichment)
    investigator_result: InvestigationResult | None
    verifier_result: VerificationResult | None
    orchestrator_result: ActionDecision | None

    # Operational Workflow & Escalation Flags
    requires_human_review: bool
    disagreements: list[str]
    final_agent_recommendation: str
    agent_status: AgentRunStatus
    agent_errors: list[str]
    inject_disagreement: bool

    # Benchmarking & Telemetry
    timestamps: dict[str, str]
    latencies_ms: dict[str, float]
