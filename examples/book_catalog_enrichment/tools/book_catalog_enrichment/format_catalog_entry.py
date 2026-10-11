"""Format the final enriched catalog entry."""

from agent_actions import udf_tool


@udf_tool()
def format_catalog_entry(data: dict) -> dict:
    """Consolidate all enriched data into a clean catalog entry."""
    # A record tool is handed one key per observed action.
    write_description = data.get("write_description", {})
    validate_bisac = data.get("validate_bisac", {})
    generate_seo = data.get("generate_seo", {})
    generate_recommendations = data.get("generate_recommendations", {})
    assess_reading_level = data.get("assess_reading_level", {})
    score_quality = data.get("score_quality", {})

    enriched_fields = []

    entry = {
        "isbn": write_description.get("isbn", ""),
        "catalog_id": f"CAT-{write_description.get('isbn', 'UNKNOWN')[-6:]}",
        "title": write_description.get("title", ""),
        "authors": write_description.get("authors", []),
        "publisher": write_description.get("publisher", ""),
        "publish_year": write_description.get("publish_year", 0),
        "page_count": write_description.get("page_count", 0),
    }

    # Classification
    bisac_names = validate_bisac.get("bisac_names", [])
    entry["primary_category"] = bisac_names[0] if bisac_names else "Uncategorized"
    entry["categories"] = bisac_names
    entry["bisac_codes"] = validate_bisac.get("bisac_codes", [])
    if bisac_names:
        enriched_fields.append("classification")

    # Marketing content
    hook = write_description.get("hook_sentence", "")
    full_desc = write_description.get("marketing_description", "")
    entry["short_description"] = (
        hook if hook else full_desc[:200] + "..." if len(full_desc) > 200 else full_desc
    )
    entry["full_description"] = full_desc
    entry["key_selling_points"] = write_description.get("key_benefits", [])
    entry["target_audience"] = write_description.get("target_audience", "")
    if full_desc:
        enriched_fields.append("marketing_description")

    # SEO
    primary_kw = generate_seo.get("primary_keywords", [])
    long_tail_kw = generate_seo.get("long_tail_keywords", [])
    entry["seo_keywords"] = primary_kw + long_tail_kw
    entry["meta_title"] = generate_seo.get("meta_title", write_description.get("title", ""))
    entry["meta_description"] = generate_seo.get("meta_description", "")
    if primary_kw:
        enriched_fields.append("seo_keywords")

    # Recommendations
    similar = generate_recommendations.get("similar_books", [])
    entry["similar_titles"] = similar[:5] if similar else []
    entry["reading_path"] = generate_recommendations.get("reading_path", "")
    if similar:
        enriched_fields.append("recommendations")

    # Reading info
    entry["difficulty_level"] = assess_reading_level.get("reading_level", "Intermediate")
    entry["experience_required"] = assess_reading_level.get("years_experience_needed", "")
    entry["prerequisites"] = assess_reading_level.get("prerequisites", [])
    entry["reading_time_hours"] = assess_reading_level.get("estimated_reading_time", "")
    if assess_reading_level.get("reading_level"):
        enriched_fields.append("reading_level")

    # Quality
    entry["quality_score"] = float(score_quality.get("overall_score", 0))
    entry["publication_ready"] = score_quality.get("ready_for_publication", False)

    # Metadata
    entry["enrichment_version"] = "1.0.0"
    entry["enriched_fields"] = enriched_fields

    return entry
