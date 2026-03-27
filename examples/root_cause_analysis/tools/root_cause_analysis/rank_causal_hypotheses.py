"""
Aggregate and rank causal hypotheses from multiple reasoning strategies.
Demonstrates pattern: parallel evaluation → aggregation with scoring.
"""

from typing import Any

from agent_actions import udf_tool


def _calculate_evidence_score(evidence: list[str]) -> float:
    """Calculate evidence strength score."""
    # More evidence = higher score, with diminishing returns
    base_score = min(len(evidence) * 0.15, 0.6)

    # Bonus for specific evidence types
    strong_evidence_keywords = [
        "correlation",
        "timestamp",
        "metric",
        "log",
        "historical",
        "pattern",
        "topology",
    ]
    evidence_text = " ".join(evidence).lower()
    bonus = sum(0.08 for keyword in strong_evidence_keywords if keyword in evidence_text)

    return min(base_score + bonus, 1.0)


def _calculate_consensus_score(hypothesis_text: str, all_hypotheses: list[dict]) -> float:
    """Calculate consensus score based on similar hypotheses across strategies."""
    # Check if multiple strategies identified similar causes
    similar_count = sum(
        1
        for h in all_hypotheses
        if any(
            keyword in h.get("cause", "").lower() for keyword in hypothesis_text.lower().split()[:3]
        )
    )
    return min(similar_count * 0.25, 1.0)


@udf_tool()
def rank_causal_hypotheses(data: dict[str, Any]) -> dict[str, Any]:
    """
    Aggregate hypotheses from multiple reasoning strategies and rank by evidence.

    Pattern: Parallel evaluation → weighted aggregation with scoring
    Returns: Dict with ranked hypotheses (passthrough handles upstream fields)
    """
    content = data.get("content", data)

    # Extract hypotheses from three parallel reasoning strategies (numeric versions)
    # Versions are named generate_hypotheses_1, generate_hypotheses_2, generate_hypotheses_3
    strategy_names = ["strategy_1", "strategy_2", "strategy_3"]
    strategy_data_list = []

    for i in range(1, 4):
        version_key = f"generate_hypotheses_{i}"
        strategy_data_list.append((strategy_names[i - 1], content.get(version_key, {})))

    # Get seed data for validation
    causal_patterns = content.get("causal_patterns", {})
    known_rules = causal_patterns.get("causal_rules", {})
    known_chains = causal_patterns.get("causal_chains", {})

    # Collect all hypotheses with strategy context
    all_hypotheses = []

    for strategy_name, strategy_data in strategy_data_list:
        hypotheses = strategy_data.get("hypotheses", [])
        for h in hypotheses:
            if isinstance(h, dict):
                all_hypotheses.append(
                    {
                        "cause": h.get("cause", "Unknown"),
                        "mechanism": h.get("mechanism", "Unknown"),
                        "confidence": h.get("confidence", 0.5),
                        "evidence": h.get("evidence", []),
                        "strategy": strategy_name,
                    }
                )

    # Rank hypotheses using multi-factor scoring
    ranked_hypotheses = []

    for hypothesis in all_hypotheses:
        # Base confidence from the strategy
        base_confidence = float(hypothesis.get("confidence", 0.5))

        # Evidence strength score
        evidence = hypothesis.get("evidence", [])
        evidence_score = _calculate_evidence_score(evidence)

        # Consensus score (multiple strategies identified similar cause)
        cause_text = hypothesis.get("cause", "")
        consensus_score = _calculate_consensus_score(cause_text, all_hypotheses)

        # Pattern matching bonus (matches known causal patterns)
        pattern_bonus = 0.0
        cause_lower = cause_text.lower()
        for rule_name, _rule_data in known_rules.items():
            if any(keyword in cause_lower for keyword in rule_name.split("_")[:2]):
                pattern_bonus = 0.2
                break

        # Chain matching bonus (part of known causal chain)
        chain_bonus = 0.0
        for _chain_name, chain_data in known_chains.items():
            chain_steps = chain_data.get("chain", [])
            if any(cause_lower in step.lower() for step in chain_steps):
                chain_bonus = 0.15
                break

        # Calculate composite score
        composite_score = (
            base_confidence * 0.35
            + evidence_score * 0.30
            + consensus_score * 0.20
            + pattern_bonus
            + chain_bonus
        )

        ranked_hypotheses.append(
            {
                "cause": hypothesis["cause"],
                "mechanism": hypothesis["mechanism"],
                "confidence": base_confidence,
                "evidence": evidence,
                "strategy": hypothesis["strategy"],
                "composite_score": round(composite_score, 3),
                "scoring_breakdown": {
                    "base_confidence": round(base_confidence, 2),
                    "evidence_score": round(evidence_score, 2),
                    "consensus_score": round(consensus_score, 2),
                    "pattern_bonus": round(pattern_bonus, 2),
                    "chain_bonus": round(chain_bonus, 2),
                },
            }
        )

    # Sort by composite score (descending)
    ranked_hypotheses.sort(key=lambda x: x["composite_score"], reverse=True)

    # Identify top hypotheses for validation
    top_hypotheses = ranked_hypotheses[:5] if len(ranked_hypotheses) >= 5 else ranked_hypotheses

    # Generate ranking summary
    strategy_distribution = {}
    for h in top_hypotheses:
        strategy = h["strategy"]
        strategy_distribution[strategy] = strategy_distribution.get(strategy, 0) + 1

    # Return ONLY new fields (passthrough forwards upstream fields)
    return {
        "all_ranked_hypotheses": ranked_hypotheses,
        "top_hypotheses": top_hypotheses,
        "hypothesis_count": len(ranked_hypotheses),
        "strategy_distribution": strategy_distribution,
        "top_cause": ranked_hypotheses[0]["cause"] if ranked_hypotheses else "Unknown",
        "top_confidence": ranked_hypotheses[0]["composite_score"] if ranked_hypotheses else 0.0,
        "ranking_method": "weighted_composite_scoring",
        "used_seed_patterns": len(known_rules) > 0 or len(known_chains) > 0,
    }
