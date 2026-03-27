"""Compute composite risk score blending LLM and statistical judgments.

Combines the LLM meta-detector's confidence and judgment with the
statistical aggregate score to produce a final decision of BLOCK,
REVIEW, or PASS. Handles LLM overrides of statistical consensus.
"""

from typing import Any, TypedDict

from agent_actions import udf_tool


class ComputeCompositeRiskInput(TypedDict, total=False):
    """Input schema for compute_composite_risk."""

    aggregate_detection_scores: dict[str, Any]
    meta_detector_judgment: dict[str, Any]


class ComputeCompositeRiskOutput(TypedDict, total=False):
    """Output schema for compute_composite_risk."""

    composite_score: float
    decision: str
    llm_override: bool
    reasoning: str


# Blending weights
STATISTICAL_WEIGHT = 0.45
LLM_WEIGHT = 0.55

# Decision thresholds
BLOCK_THRESHOLD = 0.65
REVIEW_THRESHOLD = 0.35


@udf_tool()
def compute_composite_risk(data: dict) -> dict:
    """Compute composite risk by blending LLM and statistical scores.

    The LLM confidence is blended with the statistical aggregate score.
    If the LLM overrides the statistical consensus, the score is adjusted
    to reflect the LLM's judgment more heavily.

    Args:
        data: Input containing aggregate_detection_scores and
              meta_detector_judgment results.

    Returns:
        Dict with composite_score, decision (BLOCK/REVIEW/PASS),
        llm_override flag, and reasoning.
    """
    content = data.get("content", data)

    agg_data = content.get("aggregate_detection_scores", {})
    llm_data = content.get("meta_detector_judgment", {})

    aggregate_score = agg_data.get("aggregate_score", 0.0)
    statistical_verdict = agg_data.get("statistical_verdict", "SUSPICIOUS")

    is_injection = llm_data.get("is_injection", False)
    llm_confidence = llm_data.get("confidence", 0.5)
    llm_risk_level = llm_data.get("risk_level", "medium")
    override_statistical = llm_data.get("override_statistical", False)
    llm_reasoning = llm_data.get("reasoning", "")

    # Convert LLM judgment to numeric score
    if is_injection:
        llm_score = llm_confidence
    else:
        llm_score = 1.0 - llm_confidence  # High confidence safe → low risk

    # Blend scores
    stat_weight = STATISTICAL_WEIGHT
    llm_weight = LLM_WEIGHT

    # If LLM overrides, shift weight toward LLM
    if override_statistical:
        stat_weight = 0.25
        llm_weight = 0.75

    composite_score = stat_weight * aggregate_score + llm_weight * llm_score
    composite_score = round(min(max(composite_score, 0.0), 1.0), 4)

    # Determine decision
    if composite_score >= BLOCK_THRESHOLD:
        decision = "BLOCK"
    elif composite_score >= REVIEW_THRESHOLD:
        decision = "REVIEW"
    else:
        decision = "PASS"

    # If LLM says critical with high confidence, force BLOCK regardless
    if is_injection and llm_risk_level == "critical" and llm_confidence >= 0.90:
        decision = "BLOCK"
        composite_score = max(composite_score, 0.90)

    # If LLM confidently overrides to safe, cap at REVIEW (never auto-PASS an override)
    if override_statistical and not is_injection and statistical_verdict == "RISKY":
        decision = "REVIEW" if decision == "PASS" else decision

    # Build reasoning
    reasoning_parts = []
    reasoning_parts.append(f"Statistical aggregate: {aggregate_score:.3f} ({statistical_verdict})")
    reasoning_parts.append(
        f"LLM judgment: {'injection' if is_injection else 'safe'} "
        f"(confidence={llm_confidence:.2f}, risk={llm_risk_level})"
    )
    if override_statistical:
        reasoning_parts.append(
            f"LLM OVERRIDES statistical consensus. LLM reasoning: {llm_reasoning}"
        )
    reasoning_parts.append(f"Composite score: {composite_score:.4f} → {decision}")

    return {
        "composite_score": composite_score,
        "decision": decision,
        "llm_override": override_statistical,
        "reasoning": " | ".join(reasoning_parts),
    }
