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
    content = data.get("content", data)

    # Source metadata (passthrough fields arrive flat)
    source = {
        "review_id": content.get("review_id", ""),
        "product_name": content.get("product_name", ""),
        "product_category": content.get("product_category", ""),
        "reviewer_name": content.get("reviewer_name", ""),
        "review_date": content.get("review_date", ""),
    }

    # Analysis — fields from extract_claims and aggregate_scores arrive flat
    analysis = {
        "quality_score": content.get("consensus_score", 0),
        "is_split_decision": content.get("is_split_decision", False),
        "claims_extracted": len(content.get("factual_claims", [])),
        "aspects_covered": content.get("product_aspects", []),
        "sentiment": (
            content.get("sentiment_signals", {}).get("overall_tone", "unknown")
            if isinstance(content.get("sentiment_signals"), dict)
            else "unknown"
        ),
        "red_flags": content.get("red_flags", []),
    }

    result = {
        **source,
        "analysis": analysis,
    }

    # Only include merchant_response if the guard passed
    response_text = content.get("response_text")
    if response_text:
        result["merchant_response"] = {
            "response_text": response_text,
            "response_tone": content.get("response_tone", ""),
        }

    # Only include product_insights if the guard passed
    feedback_items = content.get("feedback_items")
    if feedback_items:
        result["product_insights"] = {
            "feedback_items": feedback_items,
            "improvement_priority": content.get("improvement_priority", ""),
            "positive_differentiators": content.get("positive_differentiators", []),
        }

    return result
