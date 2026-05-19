"""Transform raw Kaggle review data into the analyzer pipeline's expected schema."""

import re
from typing import Any

from agent_actions import udf_tool


# Map raw Kaggle categories to readable names
CATEGORY_MAP = {
    "kindle": "E-Readers",
    "paperwhite": "E-Readers",
    "fire hd": "Tablets",
    "fire tablet": "Tablets",
    "tablet": "Tablets",
    "echo dot": "Smart Speakers",
    "echo": "Voice Assistants",
    "alexa": "Voice Assistants",
    "fire tv": "Streaming Devices",
    "fire stick": "Streaming Devices",
    "streaming": "Streaming Devices",
    "charger": "Accessories",
    "cable": "Accessories",
    "adapter": "Accessories",
    "case": "Accessories",
    "cover": "Accessories",
    "screen protector": "Accessories",
    "headphone": "Audio",
    "earbuds": "Audio",
    "speaker": "Audio",
    "camera": "Smart Home",
    "ring": "Smart Home",
    "security": "Smart Home",
    "doorbell": "Smart Home",
}


def _map_category(categories_str: str, name_str: str) -> str:
    """Map Kaggle categories to a readable product category."""
    lower = (categories_str + " " + name_str).lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in lower:
            return category
    return "Electronics"


def _parse_date(date_str: str) -> str:
    """Parse various date formats to YYYY-MM-DD."""
    if not date_str:
        return "2024-01-01"
    # Handle ISO format: 2015-08-08T00:00:00.000Z
    match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
    if match:
        return match.group(1)
    return "2024-01-01"


def _parse_bool(val: str) -> bool:
    """Parse various boolean representations."""
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("y", "yes", "true", "1")


@udf_tool()
def normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Transform a raw Kaggle review record into the pipeline's expected schema."""
    source = data["source"]

    review_id = source.get("id", "").strip()
    if not review_id:
        review_id = f"R{hash(str(source)) % 10000:04d}"

    review_text = source.get("reviews.text", source.get("review_body", "")).strip()
    star_rating = source.get("reviews.rating", source.get("star_rating", "3"))

    try:
        star_rating = int(star_rating)
        star_rating = max(1, min(5, star_rating))
    except (ValueError, TypeError):
        star_rating = 3

    return {
        "review_id": review_id,
        "product_name": source.get("name", source.get("product_title", "Unknown Product")).strip(),
        "product_category": _map_category(
            source.get("categories", source.get("product_category", "")),
            source.get("name", ""),
        ),
        "reviewer_name": source.get("reviews.username", source.get("customer_id", "Anonymous")).strip() or "Anonymous",
        "review_date": _parse_date(source.get("reviews.date", source.get("review_date", ""))),
        "star_rating": star_rating,
        "review_title": source.get("reviews.title", source.get("review_headline", "")).strip(),
        "review_text": review_text,
        "verified_purchase": _parse_bool(source.get("reviews.doRecommend", source.get("verified_purchase", "true"))),
    }
