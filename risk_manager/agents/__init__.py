"""LangGraph multi-agent orchestration runtime package (Phase 6).

Implements asynchronous multi-agent enrichment for risk decisions:
- Investigator: Evidence synthesis and factor discovery
- Verifier: 10 internal consistency checks and disagreement detection
- Action Orchestrator: Operational execution mode translation

The numerical risk score (p_return_abuse) from Phase 4 and policy action from Phase 5
are strictly authoritative and immutable.
"""

from risk_manager.agents.graph import (
    agent_workflow_graph,
    build_agent_graph,
    run_agent_workflow,
)
from risk_manager.agents.investigator import investigator_node
from risk_manager.agents.llm import AgentLLMClient, default_agent_llm
from risk_manager.agents.orchestrator import action_orchestrator_node
from risk_manager.agents.persistence import persist_agent_workflow_result
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.tools import ALLOWLISTED_TOOLS
from risk_manager.agents.verifier import verifier_node

__all__ = [
    "AgentGraphState",
    "build_agent_graph",
    "agent_workflow_graph",
    "run_agent_workflow",
    "investigator_node",
    "verifier_node",
    "action_orchestrator_node",
    "AgentLLMClient",
    "default_agent_llm",
    "ALLOWLISTED_TOOLS",
    "persist_agent_workflow_result",
]
