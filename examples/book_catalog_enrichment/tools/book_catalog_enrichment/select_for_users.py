"""Build user-specific views of the enriched catalog entry."""

from agent_actions import udf_tool


@udf_tool()
def select_for_users(data: dict) -> dict:
    """Build SEO, management, and developer views from the enriched catalog entry."""
    # A record tool is handed one key per observed action.
    filter_quality = data.get("filter_quality", {})
    format_entry = data.get("format_entry", {})

    seo_view = {
        "isbn": format_entry.get("isbn", ""),
        "title": format_entry.get("title", ""),
        "meta_title": format_entry.get("meta_title", ""),
        "meta_description": format_entry.get("meta_description", ""),
        "seo_keywords": format_entry.get("seo_keywords", []),
        "target_audience": format_entry.get("target_audience", ""),
        "marketing_description": format_entry.get("full_description", ""),
        "hook_sentence": format_entry.get("short_description", ""),
        "key_selling_points": format_entry.get("key_selling_points", []),
    }

    management_view = {
        "isbn": format_entry.get("isbn", ""),
        "title": format_entry.get("title", ""),
        "catalog_id": format_entry.get("catalog_id", ""),
        "quality_score": format_entry.get("quality_score", 0),
        "publication_ready": format_entry.get("publication_ready", False),
        "primary_category": format_entry.get("primary_category", ""),
        "target_audience": format_entry.get("target_audience", ""),
        "enriched_fields": format_entry.get("enriched_fields", []),
        "enrichment_version": format_entry.get("enrichment_version", ""),
        "filter_reason": filter_quality.get("filter_reason", ""),
    }

    developer_view = {
        "isbn": format_entry.get("isbn", ""),
        "title": format_entry.get("title", ""),
        "bisac_codes": format_entry.get("bisac_codes", []),
        "primary_category": format_entry.get("primary_category", ""),
        "difficulty_level": format_entry.get("difficulty_level", ""),
        "experience_required": format_entry.get("experience_required", ""),
        "prerequisites": format_entry.get("prerequisites", []),
        "reading_time_hours": format_entry.get("reading_time_hours", ""),
        "similar_titles": format_entry.get("similar_titles", []),
        "reading_path": format_entry.get("reading_path", ""),
    }

    return {
        "isbn": format_entry.get("isbn", ""),
        "title": format_entry.get("title", ""),
        "seo_view": seo_view,
        "management_view": management_view,
        "developer_view": developer_view,
    }
