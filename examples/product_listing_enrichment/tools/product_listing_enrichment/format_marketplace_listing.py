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

    # Marketing copy from write_marketing_copy
    write_copy = content.get("write_marketing_copy", {})
    if not isinstance(write_copy, dict):
        write_copy = {}

    # SEO data from optimize_seo (may be None if guard filtered)
    seo_data = content.get("optimize_seo", {})
    if not isinstance(seo_data, dict):
        seo_data = {}

    # Compliance from validate_compliance
    compliance_data = content.get("validate_compliance", {})
    if not isinstance(compliance_data, dict):
        compliance_data = {}

    # Competitor data from fetch_competitor_prices
    competitor_data = content.get("fetch_competitor_prices", {})
    if not isinstance(competitor_data, dict):
        competitor_data = {}

    # Use SEO-optimized title/bullets if available, otherwise fall back to copy
    final_title = seo_data.get("optimized_title") or write_copy.get("listing_title", "")
    final_bullets = seo_data.get("optimized_bullets") or write_copy.get("bullet_points", [])

    # Build the listing object
    listing = {
        "title": final_title,
        "description": write_copy.get("listing_description", ""),
        "bullet_points": final_bullets,
        "value_proposition": write_copy.get("value_proposition", ""),
    }

    # Build SEO object
    seo = {
        "primary_keywords": seo_data.get("primary_keywords", write_copy.get("search_keywords", [])),
        "long_tail_keywords": seo_data.get("long_tail_keywords", []),
        "backend_keywords": seo_data.get("backend_keywords", []),
        "seo_score": seo_data.get("seo_score_estimate", "not_optimized"),
    }

    # Build competitive intel summary
    competitor_prices = competitor_data.get("competitor_prices", [])
    competitive_intel = {
        "price_position": competitor_data.get("price_position", "unknown"),
        "average_competitor_price": competitor_data.get("average_competitor_price", 0),
        "competitor_count": len(competitor_prices),
    }

    # Build compliance summary
    compliance = {
        "passed": compliance_data.get("compliance_passed", False),
        "violations": compliance_data.get("violations", []),
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
