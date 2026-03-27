"""Format the final review analysis output.

Fan-in tool that packages results from parallel branches
(generate_response + extract_product_insights) into the final structure.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_analysis_output(data: dict[str, Any]) -> dict[str, Any]:
    """Package review analysis, merchant response, and product insights.

    Combines outputs from:
    - extract_claims (claims, aspects, sentiment)
    - aggregate_scores (quality score, strengths, weaknesses)
    - generate_response (merchant response text)
    - extract_product_insights (actionable feedback)
    - source (original review metadata)
    """
    content = data.get("content", data)

    # Source metadata
    source = {
        "review_id": content.get("review_id", ""),
        "product_name": content.get("product_name", ""),
        "product_category": content.get("product_category", ""),
        "reviewer_name": content.get("reviewer_name", ""),
        "review_date": content.get("review_date", ""),
    }

    # Analysis from extract_claims + aggregate_scores
    extract_claims = content.get("extract_claims", {})
    aggregate_scores = content.get("aggregate_scores", {})

    analysis = {
        "quality_score": aggregate_scores.get("consensus_score", 0),
        "is_split_decision": aggregate_scores.get("is_split_decision", False),
        "claims_extracted": len(extract_claims.get("claims", [])),
        "aspects_covered": extract_claims.get("product_aspects", []),
        "sentiment": (
            extract_claims.get("sentiment_signals", {}).get("overall_tone", "unknown")
            if isinstance(extract_claims.get("sentiment_signals"), dict)
            else "unknown"
        ),
        "red_flags": aggregate_scores.get("red_flags", []),
    }

    # Merchant response (may be None if review was filtered by guard)
    generate_response = content.get("generate_response", {})
    merchant_response = None
    if generate_response and isinstance(generate_response, dict):
        merchant_response = {
            "response_text": generate_response.get("response_text", ""),
            "response_tone": generate_response.get("response_tone", ""),
        }

    # Product insights (may be None if review was filtered by guard)
    insights = content.get("extract_product_insights", {})
    product_insights = None
    if insights and isinstance(insights, dict):
        product_insights = {
            "feedback_items": insights.get("feedback_items", []),
            "improvement_priority": insights.get("improvement_priority", ""),
            "positive_differentiators": insights.get("positive_differentiators", []),
        }

    return {
        **source,
        "analysis": analysis,
        "merchant_response": merchant_response,
        "product_insights": product_insights,
    }
