"""Format the final marketplace-ready product listing.

Deterministic packaging tool that assembles all upstream outputs into
the final listing JSON. No creativity needed — just structure.

Fan-in from: generate_description, write_marketing_copy,
validate_compliance, optimize_seo, fetch_competitor_prices, and source.
"""

from datetime import UTC, datetime
from typing import Any

from agent_actions import udf_tool

PIPELINE_VERSION = "1.0.0"


@udf_tool()
def format_marketplace_listing(data: dict[str, Any]) -> dict[str, Any]:
    """Package all enriched data into the final marketplace listing format.

    Combines outputs from all upstream actions into a single structured
    listing ready for marketplace upload.
    """
    content = data.get("content", data)

    # Source metadata (via passthrough)
    product_id = content.get("product_id", "")
    product_name = content.get("product_name", "")
    brand = content.get("brand", "")
    current_price = content.get("current_price", 0)
    category = content.get("product_category", "")

    # Helper: the framework flattens observed fields into content directly.
    # content["listing_title"] not content["write_marketing_copy"]["listing_title"].
    # Try nested (action namespace) first, fall back to flat (direct fields).
    def _ns(action_name: str, field: str, default=None):
        nested = content.get(action_name, {})
        if isinstance(nested, dict) and field in nested:
            return nested[field]
        return content.get(field, default)

    # Marketing copy from write_marketing_copy
    listing_title = _ns("write_marketing_copy", "listing_title", "")
    listing_description = _ns("write_marketing_copy", "listing_description", "")
    bullet_points = _ns("write_marketing_copy", "bullet_points", [])
    search_keywords = _ns("write_marketing_copy", "search_keywords", [])
    value_proposition = _ns("write_marketing_copy", "value_proposition", "")

    # SEO data from optimize_seo (may be empty if guard skipped)
    optimized_title = _ns("optimize_seo", "optimized_title", "")
    optimized_bullets = _ns("optimize_seo", "optimized_bullets", [])
    primary_keywords = _ns("optimize_seo", "primary_keywords", [])
    long_tail_keywords = _ns("optimize_seo", "long_tail_keywords", [])
    backend_keywords = _ns("optimize_seo", "backend_keywords", [])
    seo_score = _ns("optimize_seo", "seo_score_estimate", "not_optimized")

    # Compliance from validate_compliance
    compliance_passed = _ns("validate_compliance", "compliance_passed", False)
    violations = _ns("validate_compliance", "violations", [])

    # Competitor data from fetch_competitor_prices
    competitor_prices = _ns("fetch_competitor_prices", "competitor_prices", [])
    price_position = _ns("fetch_competitor_prices", "price_position", "unknown")
    avg_competitor_price = _ns("fetch_competitor_prices", "average_competitor_price", 0)

    # Use SEO-optimized title/bullets if available, otherwise fall back to copy
    final_title = optimized_title or listing_title
    final_bullets = optimized_bullets or bullet_points

    # Build the listing object
    listing = {
        "title": final_title,
        "description": listing_description,
        "bullet_points": final_bullets,
        "value_proposition": value_proposition,
    }

    # Build SEO object
    seo = {
        "primary_keywords": primary_keywords or search_keywords,
        "long_tail_keywords": long_tail_keywords,
        "backend_keywords": backend_keywords,
        "seo_score": seo_score,
    }

    # Build competitive intel summary
    competitive_intel = {
        "price_position": price_position,
        "average_competitor_price": avg_competitor_price,
        "competitor_count": len(competitor_prices),
    }

    # Build compliance summary
    compliance = {
        "passed": compliance_passed,
        "violations": violations,
    }

    return {
        "product_id": product_id,
        "product_name": product_name,
        "brand": brand,
        "category": category,
        "price": current_price,
        "listing": listing,
        "seo": seo,
        "competitive_intel": competitive_intel,
        "compliance": compliance,
        "enrichment_version": PIPELINE_VERSION,
        "enriched_at": datetime.now(UTC).isoformat(),
    }
