"""Format the final review analysis output.

Fan-in tool that packages results from parallel branches
(generate_response + extract_product_insights) into the final structure.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_analysis_output(data: dict[str, Any]) -> dict[str, Any]:
    """Package review analysis, merchant response, and product insights.

    Fields arrive flat in content from context_scope.observe — not nested
    under action names.
    """
    # Namespaced data model: fields are at data[namespace][field]
    source_ns = data.get("source", {})
    extract_ns = data.get("extract_claims", {})
    agg_ns = data.get("aggregate_scores", {})
    response_ns = data.get("generate_response", {})
    insights_ns = data.get("extract_product_insights", {})

    source = {
        "review_id": source_ns.get("review_id", ""),
        "product_name": source_ns.get("product_name", ""),
        "product_category": source_ns.get("product_category", ""),
        "reviewer_name": source_ns.get("reviewer_name", ""),
        "review_date": source_ns.get("review_date", ""),
    }

    analysis = {
        "quality_score": agg_ns.get("consensus_score", 0),
        "is_split_decision": agg_ns.get("is_split_decision", False),
        "claims_extracted": len(extract_ns.get("factual_claims", [])),
        "aspects_covered": extract_ns.get("product_aspects", []),
        "sentiment": (
            extract_ns.get("sentiment_signals", {}).get("overall_tone", "unknown")
            if isinstance(extract_ns.get("sentiment_signals"), dict)
            else "unknown"
        ),
        "red_flags": agg_ns.get("red_flags", []),
    }

    result = {
        **source,
        "analysis": analysis,
    }

    # Only include merchant_response if the guard passed
    response_text = response_ns.get("response_text") if isinstance(response_ns, dict) else None
    if response_text:
        result["merchant_response"] = {
            "response_text": response_text,
            "response_tone": response_ns.get("response_tone", ""),
        }

    # Only include product_insights if the guard passed
    feedback_items = insights_ns.get("feedback_items") if isinstance(insights_ns, dict) else None
    if feedback_items:
        result["product_insights"] = {
            "feedback_items": feedback_items,
            "improvement_priority": insights_ns.get("improvement_priority", ""),
            "positive_differentiators": insights_ns.get("positive_differentiators", []),
        }

    return result
