"""
Aggregate all clause-level risk analyses into a unified contract risk report.

FILE granularity — receives ALL clause records at once and emits a single
aggregated summary. This is the REDUCE step of the Map-Reduce pattern.

Uses FileUDFResult with source_index to indicate which input record each
output derives from (required by the framework for FILE-granularity tools).
"""

from typing import Any

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.types import Granularity


@udf_tool(granularity=Granularity.FILE)
def aggregate_clause_analyses(data: list[dict[str, Any]]) -> FileUDFResult:
    """
    Combine clause-level risk analyses into a single contract risk report.

    Input (one item per clause, holding the observed fields as flat keys):
        - risk_level, risk_score, risk_indicators, obligations, deadlines,
          recommended_action, reasoning (bare: the one wildcard, analyze_clause.*)
        - split_into_clauses.clause_number, split_into_clauses.clause_title
        - source.contract_id, source.title, source.parties

    Output (single record):
        - overall_risk_level, overall_risk_score, risk_distribution
        - high_risk_clauses, total_obligations, key_deadlines
        - negotiation_priority
    """
    if not data:
        return FileUDFResult(
            outputs=[
                {
                    "source_index": None,
                    "data": {
                        "contract_id": "unknown",
                        "contract_title": "unknown",
                        "overall_risk_level": "low",
                        "overall_risk_score": 0.0,
                        "total_clauses_analyzed": 0,
                        "risk_distribution": {"high": 0, "medium": 0, "low": 0},
                        "high_risk_clauses": [],
                        "total_obligations": [],
                        "key_deadlines": [],
                        "negotiation_priority": [],
                    },
                }
            ]
        )

    # Every clause of a contract carries the same contract metadata
    contract_id = data[0].get("source.contract_id", "unknown")
    contract_title = data[0].get("source.title", "unknown")
    parties = data[0].get("source.parties", [])

    # Collect analyses from all clause records
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    risk_scores: list[float] = []
    high_risk_clauses: list[dict[str, Any]] = []
    all_obligations: list[dict[str, Any]] = []
    all_deadlines: list[dict[str, Any]] = []
    negotiation_items: list[dict[str, Any]] = []

    for record in data:
        risk_level = record.get("risk_level", "low")
        risk_score = record.get("risk_score", 0.0)
        clause_number = record.get("split_into_clauses.clause_number", 0)
        clause_title = record.get("split_into_clauses.clause_title", "Unknown")

        # Count risk levels
        if risk_level in risk_counts:
            risk_counts[risk_level] += 1
        risk_scores.append(risk_score)

        # Collect high-risk clause details
        if risk_level == "high":
            high_risk_clauses.append(
                {
                    "clause_number": clause_number,
                    "clause_title": clause_title,
                    "risk_score": risk_score,
                    "risk_indicators": record.get("risk_indicators", []),
                    "recommended_action": record.get("recommended_action", "flag_for_legal"),
                    "reasoning": record.get("reasoning", ""),
                }
            )

        # Collect obligations with clause reference
        for obligation in record.get("obligations", []):
            all_obligations.append(
                {
                    "clause_number": clause_number,
                    "clause_title": clause_title,
                    **obligation,
                }
            )

        # Collect deadlines with clause reference
        for deadline in record.get("deadlines", []):
            all_deadlines.append(
                {
                    "clause_number": clause_number,
                    "clause_title": clause_title,
                    **deadline,
                }
            )

        # Track items that need negotiation
        action = record.get("recommended_action", "accept")
        if action in ("negotiate", "reject", "flag_for_legal"):
            negotiation_items.append(
                {
                    "clause_number": clause_number,
                    "clause_title": clause_title,
                    "action": action,
                    "risk_score": risk_score,
                }
            )

    # Calculate overall risk
    avg_risk_score = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

    # Overall risk level: highest individual clause risk, elevated if 3+ medium
    if risk_counts["high"] > 0:
        overall_risk_level = "high"
    elif risk_counts["medium"] >= 3:
        overall_risk_level = "high"
    elif risk_counts["medium"] > 0:
        overall_risk_level = "medium"
    else:
        overall_risk_level = "low"

    # Sort deadlines by urgency (shortest first)
    all_deadlines.sort(key=lambda d: d.get("days", 999))

    # Prioritize negotiation items by risk score (highest first)
    negotiation_items.sort(key=lambda n: n.get("risk_score") or 0, reverse=True)
    negotiation_priority = [
        f"Clause {n['clause_number']} ({n['clause_title']}): {n['action']}"
        for n in negotiation_items
    ]

    # Sort high-risk clauses by risk score (highest first)
    high_risk_clauses.sort(key=lambda c: c.get("risk_score") or 0, reverse=True)

    result = {
        "contract_id": contract_id,
        "contract_title": contract_title,
        "parties": parties,
        "overall_risk_level": overall_risk_level,
        "overall_risk_score": round(avg_risk_score, 3),
        "total_clauses_analyzed": len(data),
        "risk_distribution": risk_counts,
        "high_risk_clauses": high_risk_clauses,
        "total_obligations": all_obligations,
        "key_deadlines": all_deadlines,
        "negotiation_priority": negotiation_priority,
    }

    # source_index: None — synthetic aggregation record, not derived from a single input
    return FileUDFResult(outputs=[{"source_index": None, "data": result}])
