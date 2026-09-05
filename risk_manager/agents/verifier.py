"""Verifier agent node for LangGraph multi-agent orchestration.

Implements Phase 6 Verifier requirements §2, §6, §8, §9, §10 and targeted fixes for
deterministic-first invariant verification.
Hard safety and policy checks execute in deterministic Python first; Gemini enrichment
runs subsequently and CANNOT override deterministic invariant failures.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from risk_manager.agents.llm import default_agent_llm
from risk_manager.agents.prompts import (
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_USER_PROMPT_TEMPLATE,
)
from risk_manager.agents.state import AgentGraphState
from risk_manager.agents.tools import (
    clear_workflow_tool_context,
    set_workflow_tool_context,
)
from risk_manager.domain.risk_bands import map_probability_to_risk_band
from risk_manager.domain.schemas.agents import InvestigationResult, VerificationResult
from risk_manager.domain.schemas.enums import (
    Action,
    AgentFallbackReason,
    AgentName,
    AgentProvider,
    AgentRunStatus,
    RiskBand,
    VerifierRecommendation,
)
from risk_manager.observability.tracer import traced

logger = logging.getLogger(__name__)


def run_deterministic_verifier_checks(
    state: AgentGraphState,
) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """Execute authoritative deterministic Python safety and invariant checks.

    Returns:
        passed_checks: list of check descriptions that passed
        failed_checks: list of check descriptions that failed
        warnings: list of advisory warnings
        disagreements: list of detected discrepancies
        requires_human_review: boolean flag indicating if human escalation is required
    """
    passed_checks: list[str] = []
    failed_checks: list[str] = []
    warnings: list[str] = []
    disagreements: list[str] = []
    requires_human_review = False

    p_return_abuse = float(state.get("p_return_abuse", 0.0))
    risk_band_str = str(state.get("risk_band", "")).upper()
    selected_action = state.get("selected_action", Action.A0)
    candidate_actions = state.get("candidate_actions", [])
    guardrails_applied = state.get("guardrails_applied", [])
    expected_loss = float(state.get("expected_loss", 0.0))
    expected_net_value = float(state.get("expected_net_value", 0.0))

    # --------------------------------------------------------------------------
    # 1. RISK BAND CONSISTENCY (Centralized Phase 4 definition)
    # --------------------------------------------------------------------------
    try:
        expected_band = map_probability_to_risk_band(p_return_abuse)
        if risk_band_str != expected_band.value:
            failed_checks.append(
                f"Check 1 (Risk Band): Inconsistent risk band '{risk_band_str}' for p={p_return_abuse:.4f} "
                f"(centralized policy expected '{expected_band.value}')"
            )
            disagreements.append(f"Risk band mismatch: expected {expected_band.value}, got {risk_band_str}")
            requires_human_review = True
        else:
            passed_checks.append(
                f"Check 1 (Risk Band): Authoritative risk band '{risk_band_str}' matches p={p_return_abuse:.4f}"
            )
    except Exception as e:
        failed_checks.append(f"Check 1 (Risk Band): Failed evaluating risk band: {e}")
        disagreements.append(f"Risk band evaluation exception: {e}")
        requires_human_review = True

    # --------------------------------------------------------------------------
    # 2. ACTION VALIDITY (Canonical Phase 5 Action space)
    # --------------------------------------------------------------------------
    action_str = selected_action.value if hasattr(selected_action, "value") else str(selected_action)
    valid_actions = {a.value for a in Action}
    if action_str not in valid_actions:
        failed_checks.append(
            f"Check 2 (Action Validity): Invalid action '{selected_action}' not in canonical action space {sorted(valid_actions)}"
        )
        disagreements.append(f"Action '{selected_action}' is not in canonical action space")
        requires_human_review = True
    else:
        passed_checks.append(f"Check 2 (Action Validity): Selected action '{action_str}' is canonical")

    # --------------------------------------------------------------------------
    # 3. GUARDRAIL & ELIGIBILITY CONSISTENCY
    # --------------------------------------------------------------------------
    for cand in candidate_actions:
        if isinstance(cand, dict) and cand.get("action") == action_str:
            if not cand.get("is_eligible", True):
                reason = cand.get("ineligibility_reason", "Action marked ineligible by Phase 5 policy")
                failed_checks.append(
                    f"Check 3 (Eligibility): Selected action '{action_str}' is ineligible: {reason}"
                )
                disagreements.append(f"Selected action '{action_str}' is marked ineligible by policy")
                requires_human_review = True
            else:
                passed_checks.append(f"Check 3 (Eligibility): Selected action '{action_str}' verified eligible")

    for g in guardrails_applied:
        g_lower = g.lower()
        if "violation" in g_lower or "disallowed" in g_lower or "breach" in g_lower:
            failed_checks.append(f"Check 4 (Guardrails): Guardrail violation: {g}")
            disagreements.append(f"Guardrail violation: {g}")
            requires_human_review = True
        else:
            passed_checks.append(f"Check 4 (Guardrails): Guardrail satisfied: {g}")

    # --------------------------------------------------------------------------
    # 4. MANUAL REVIEW / A4 SAFETY
    # --------------------------------------------------------------------------
    if selected_action == Action.A4 or action_str == "A4":
        warnings.append("Check 5 (A4 Safety): Action is A4 (MANUAL_REVIEW) - mandatory human review required")
        requires_human_review = True
    else:
        passed_checks.append("Check 5 (A4 Safety): Action is not A4")

    # --------------------------------------------------------------------------
    # 5. ECONOMIC CONSISTENCY
    # --------------------------------------------------------------------------
    if expected_loss < 0.0:
        failed_checks.append(f"Check 6 (Economics): Invalid negative expected loss {expected_loss}")
        requires_human_review = True
    elif not (0.0 <= p_return_abuse <= 1.0):
        failed_checks.append(f"Check 6 (Economics): Invalid probability value {p_return_abuse}")
        requires_human_review = True
    else:
        passed_checks.append("Check 6 (Economics): Authoritative economic fields verified non-negative")

    # --------------------------------------------------------------------------
    # 6. INVESTIGATOR FINDINGS & DISAGREEMENTS
    # --------------------------------------------------------------------------
    inv_res: InvestigationResult | None = state.get("investigator_result")
    if inv_res and inv_res.contradictions:
        warnings.append(f"Check 8 (Contradictions): Investigator noted contradictions: {inv_res.contradictions}")
        disagreements.extend(inv_res.contradictions)
        requires_human_review = True

    # Test harness injection flag
    if state.get("inject_disagreement"):
        failed_checks.append("Check 7 (Disagreement): Injected simulated disagreement")
        disagreements.append("Simulated engine-evidence disagreement")
        requires_human_review = True

    return passed_checks, failed_checks, warnings, disagreements, requires_human_review


def combine_verifier_results(
    state: AgentGraphState,
    det_passed: list[str],
    det_failed: list[str],
    det_warnings: list[str],
    det_disagreements: list[str],
    det_requires_human: bool,
    gemini_result: VerificationResult | None,
) -> VerificationResult:
    """Combine deterministic checks with optional Gemini output without allowing invariant overrides."""
    decision_id = state.get("decision_id")
    all_checks = list(det_passed) + list(det_failed)
    all_failed = list(det_failed)
    all_warnings = list(det_warnings)
    all_disagreements = list(det_disagreements)
    requires_human = det_requires_human

    # Default fallback provenance if Gemini is absent
    provider = AgentProvider.DETERMINISTIC_FALLBACK.value
    is_llm_generated = False
    fallback_reason: str | None = AgentFallbackReason.PROVIDER_UNAVAILABLE.value
    model_name: str | None = None

    if gemini_result is not None:
        provider = gemini_result.provider
        is_llm_generated = gemini_result.is_llm_generated
        fallback_reason = gemini_result.fallback_reason
        model_name = gemini_result.model_name

        # Merge additional non-contradictory qualitative signals from Gemini
        for w in gemini_result.warnings:
            if w not in all_warnings:
                all_warnings.append(w)
        for d in gemini_result.disagreements:
            if d not in all_disagreements:
                all_disagreements.append(d)
        for f in gemini_result.failed_checks:
            if f not in all_failed:
                all_failed.append(f)

        if gemini_result.requires_human_review:
            requires_human = True

        # CRITICAL SAFETY INVARIANT:
        # If deterministic checks failed, Gemini CANNOT override to CONFIRM/VERIFIED!
        if det_failed and (gemini_result.verified or gemini_result.recommendation == VerifierRecommendation.CONFIRM):
            all_disagreements.append("Gemini LLM attempted to confirm an invalid deterministic invariant; overridden.")
            requires_human = True

    # Final verdict calculation
    if all_failed:
        verification_status = "FAILED"
        verified = False
        requires_human = True
        recommendation = VerifierRecommendation.MANUAL_REVIEW
    elif all_disagreements:
        verification_status = "DISAGREEMENT"
        verified = False
        requires_human = True
        recommendation = VerifierRecommendation.MANUAL_REVIEW
    elif requires_human:
        verification_status = "VERIFIED"
        verified = True
        recommendation = VerifierRecommendation.MANUAL_REVIEW
    else:
        verification_status = "VERIFIED"
        verified = True
        recommendation = VerifierRecommendation.CONFIRM

    return VerificationResult(
        case_id=decision_id,
        agent_name=AgentName.VERIFIER,
        status=AgentRunStatus.COMPLETED,
        provider=provider,
        is_llm_generated=is_llm_generated,
        fallback_reason=fallback_reason,
        model_name=model_name,
        verification_status=verification_status,
        checks=all_checks,
        failed_checks=all_failed,
        warnings=all_warnings,
        disagreements=all_disagreements,
        recommendation=recommendation,
        requires_human_review=requires_human,
        confidence=0.95 if not all_failed else 0.70,
        verified=verified,
        contradictions=all_disagreements,
        missing_evidence=[],
        verifier_confidence=0.95 if not all_failed else 0.70,
    )


@traced("agent.verifier")
async def verifier_node(state: AgentGraphState) -> dict[str, Any]:
    """Execute the Verifier agent node using deterministic-first invariant checks."""
    start_time = time.perf_counter()
    errors: list[str] = list(state.get("agent_errors", []))
    latencies: dict[str, float] = dict(state.get("latencies_ms", {}))

    try:
        set_workflow_tool_context(dict(state))

        # STEP 1: Authoritative Deterministic Python Invariant Checks (Issue 3)
        det_passed, det_failed, det_warnings, det_disagreements, det_requires_human = (
            run_deterministic_verifier_checks(state)
        )

        # STEP 2: Optional Gemini Qualitative Enrichment
        decision_id = state.get("decision_id")
        p_return_abuse = state.get("p_return_abuse", 0.0)
        risk_band = state.get("risk_band", "LOW")
        scoring_source = state.get("scoring_source", "XGBOOST")
        fallback_tier = state.get("fallback_tier", 0)
        selected_action = state.get("selected_action", Action.A0)
        action_selector = state.get("action_selector", "LINUCB")
        expected_net_value = state.get("expected_net_value", 0.0)
        guardrails_applied = state.get("guardrails_applied", [])
        candidate_actions = state.get("candidate_actions", [])

        inv_res: InvestigationResult | None = state.get("investigator_result")
        customer_history = state.get("customer_history", {})
        return_reason = str(customer_history.get("return_reason", "Not provided"))

        gemini_result: VerificationResult | None = None
        try:
            user_prompt = VERIFIER_USER_PROMPT_TEMPLATE.format(
                decision_id=decision_id,
                p_return_abuse=p_return_abuse,
                risk_band=risk_band,
                scoring_source=scoring_source,
                fallback_tier=fallback_tier,
                selected_action=selected_action.value if hasattr(selected_action, "value") else str(selected_action),
                action_selector=action_selector,
                expected_net_value=expected_net_value,
                guardrails_applied=", ".join(guardrails_applied) if guardrails_applied else "None",
                candidate_actions=str(candidate_actions),
                investigator_evidence_quality=inv_res.evidence_quality.value if inv_res else "UNKNOWN",
                investigator_risk_factors=", ".join(inv_res.key_risk_factors) if inv_res else "None",
                investigator_mitigating_factors=", ".join(inv_res.mitigating_factors) if inv_res else "None",
                investigator_contradictions=", ".join(inv_res.contradictions) if inv_res else "None",
                investigator_missing_info=", ".join(inv_res.missing_information) if inv_res else "None",
                investigator_recommendation=inv_res.recommendation if inv_res else "UNKNOWN",
                investigator_confidence=inv_res.confidence if inv_res else 0.0,
                return_reason=return_reason,
            )

            gemini_result = await default_agent_llm.invoke_structured(
                schema=VerificationResult,
                system_prompt=VERIFIER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                context=dict(state),
                agent_name=AgentName.VERIFIER,
            )
        except Exception as e:
            logger.warning("Optional Gemini enrichment failed in Verifier: %s", e)
            errors.append(f"Verifier Gemini enrichment error: {e}")

        # STEP 3: Combine without overriding invariants
        result = combine_verifier_results(
            state=state,
            det_passed=det_passed,
            det_failed=det_failed,
            det_warnings=det_warnings,
            det_disagreements=det_disagreements,
            det_requires_human=det_requires_human,
            gemini_result=gemini_result,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["verifier"] = latency_ms

        logger.info(
            "Verifier node completed for decision %s in %.2f ms (status=%s, human_review=%s, failed_checks=%d)",
            decision_id,
            latency_ms,
            result.verification_status,
            result.requires_human_review,
            len(result.failed_checks),
        )

        return {
            "verifier_result": result,
            "requires_human_review": result.requires_human_review,
            "disagreements": list(set(result.disagreements)),
            "latencies_ms": latencies,
            "agent_errors": errors,
        }

    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        latencies["verifier"] = latency_ms
        err_msg = f"Verifier node unexpected error: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

        fallback_res = VerificationResult(
            case_id=state.get("decision_id"),
            agent_name=AgentName.VERIFIER,
            status=AgentRunStatus.FAILED,
            provider=AgentProvider.DETERMINISTIC_FALLBACK.value,
            is_llm_generated=False,
            fallback_reason=AgentFallbackReason.OTHER.value,
            verification_status="FAILED",
            failed_checks=[err_msg],
            recommendation=VerifierRecommendation.MANUAL_REVIEW,
            requires_human_review=True,
            confidence=0.0,
            verified=False,
        )

        return {
            "verifier_result": fallback_res,
            "requires_human_review": True,
            "disagreements": list(state.get("disagreements", [])) + [err_msg],
            "latencies_ms": latencies,
            "agent_errors": errors,
            "agent_status": AgentRunStatus.DEGRADED,
        }
    finally:
        clear_workflow_tool_context()
