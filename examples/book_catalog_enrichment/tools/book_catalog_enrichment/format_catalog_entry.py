"""Format the final enriched catalog entry."""

from agent_actions import udf_tool


@udf_tool()
def format_catalog_entry(data: dict) -> dict:
    """Consolidate all enriched data into a clean catalog entry."""
    enriched_fields = []

    entry = {
        "isbn": data.get("isbn", ""),
        "catalog_id": f"CAT-{data.get('isbn', 'UNKNOWN')[-6:]}",
        "title": data.get("title", ""),
        "authors": data.get("authors", []),
        "publisher": data.get("publisher", ""),
        "publish_year": data.get("publish_year", 0),
        "page_count": data.get("page_count", 0),
    }

    # Classification
    bisac_names = data.get("bisac_names", [])
    entry["primary_category"] = bisac_names[0] if bisac_names else "Uncategorized"
    entry["categories"] = bisac_names
    entry["bisac_codes"] = data.get("bisac_codes", [])
    if bisac_names:
        enriched_fields.append("classification")

    # Marketing content
    hook = data.get("hook_sentence", "")
    full_desc = data.get("marketing_description", "")
    entry["short_description"] = (
        hook if hook else full_desc[:200] + "..." if len(full_desc) > 200 else full_desc
    )
    entry["full_description"] = full_desc
    entry["key_selling_points"] = data.get("key_benefits", [])
    entry["target_audience"] = data.get("target_audience", "")
    if full_desc:
        enriched_fields.append("marketing_description")

    # SEO
    primary_kw = data.get("primary_keywords", [])
    long_tail_kw = data.get("long_tail_keywords", [])
    entry["seo_keywords"] = primary_kw + long_tail_kw
    entry["meta_title"] = data.get("meta_title", data.get("title", ""))
    entry["meta_description"] = data.get("meta_description", "")
    if primary_kw:
        enriched_fields.append("seo_keywords")

    # Recommendations
    similar = data.get("similar_books", [])
    entry["similar_titles"] = similar[:5] if similar else []
    entry["reading_path"] = data.get("reading_path", "")
    if similar:
        enriched_fields.append("recommendations")

    # Reading info
    entry["difficulty_level"] = data.get("reading_level", "Intermediate")
    entry["experience_required"] = data.get("years_experience_needed", "")
    entry["prerequisites"] = data.get("prerequisites", [])
    entry["reading_time_hours"] = data.get("estimated_reading_time", "")
    if data.get("reading_level"):
        enriched_fields.append("reading_level")

    # Quality
    entry["quality_score"] = float(data.get("overall_score", 0))
    entry["publication_ready"] = data.get("ready_for_publication", False)

    # Metadata
    entry["enrichment_version"] = "1.0.0"
    entry["enriched_fields"] = enriched_fields

    return entry
