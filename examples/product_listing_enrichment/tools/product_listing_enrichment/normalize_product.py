"""Transform raw Kaggle product data into the enrichment pipeline's expected schema."""

import re
from typing import Any

from agent_actions import udf_tool


# Map Kaggle categories to pipeline categories
CATEGORY_MAP = {
    "camera": "electronics",
    "photo": "electronics",
    "camcorder": "electronics",
    "speaker": "electronics",
    "audio": "electronics",
    "headphone": "electronics",
    "stereo": "electronics",
    "theater": "electronics",
    "sound": "electronics",
    "game": "electronics",
    "gaming": "electronics",
    "computer": "home_office",
    "laptop": "home_office",
    "tablet": "home_office",
    "desktop": "home_office",
    "monitor": "home_office",
    "printer": "home_office",
    "networking": "home_office",
    "router": "home_office",
    "storage": "home_office",
    "tv": "home_office",
    "television": "home_office",
    "cable": "home_office",
    "adapter": "home_office",
    "mount": "home_office",
    "phone": "outdoor_gear",
    "mobile": "outdoor_gear",
    "wearable": "outdoor_gear",
    "watch": "outdoor_gear",
    "fitness": "outdoor_gear",
    "gps": "outdoor_gear",
    "kitchen": "kitchen",
    "appliance": "kitchen",
    "cook": "kitchen",
    "coffee": "kitchen",
    "blender": "kitchen",
}


def _map_category(categories_str: str) -> str:
    """Map Kaggle categories string to one of the pipeline's expected categories."""
    lower = categories_str.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in lower:
            return category
    return "electronics"


def _parse_price(price_str: str) -> float:
    """Extract numeric price from string like '$278.00' or '278'."""
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(price_str))
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return 0.0


def _build_raw_specs(record: dict) -> dict:
    """Build a structured specs dict from available Kaggle fields."""
    specs = {}

    weight = record.get("weight", "").strip()
    if weight:
        specs["weight"] = weight

    manufacturer = record.get("manufacturer", "").strip()
    if manufacturer:
        specs["manufacturer"] = manufacturer

    mfr_number = record.get("manufacturerNumber", "").strip()
    if mfr_number:
        specs["model_number"] = mfr_number

    condition = record.get("prices.condition", "").strip()
    if condition:
        specs["condition"] = condition

    upc = record.get("upc", "").strip()
    if upc:
        specs["upc"] = upc

    ean = record.get("ean", "").strip()
    if ean:
        specs["ean"] = ean

    categories = record.get("categories", "").strip()
    if categories:
        cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        if len(cat_list) > 1:
            specs["sub_categories"] = cat_list[1:5]

    merchant = record.get("prices.merchant", "").strip()
    if merchant:
        specs["available_at"] = merchant

    price_min = record.get("prices.amountMin", "").strip()
    price_max = record.get("prices.amountMax", "").strip()
    if price_min and price_max and price_min != price_max:
        specs["price_range"] = f"${price_min} - ${price_max}"

    return specs if specs else {"general": "Electronic product"}


def _build_image_description(record: dict) -> str:
    """Generate image description from URLs or return fallback."""
    urls = record.get("imageURLs", "").strip()
    if urls:
        count = len(urls.split(","))
        return f"Product listing includes {count} image(s) from retailer."
    return "No product images available."


@udf_tool()
def normalize_product(data: dict[str, Any]) -> dict[str, Any]:
    """Transform a raw Kaggle product record into the pipeline's expected schema."""
    source = data["source"]

    product_id = source.get("id", "").strip()
    if not product_id:
        product_id = source.get("asins", "unknown")
    product_id = f"PLE-{product_id[:12]}"

    return {
        "product_id": product_id,
        "product_name": source.get("name", "Unknown Product").strip(),
        "product_category": _map_category(source.get("categories", "")),
        "brand": source.get("brand", "Unknown").strip() or "Unknown",
        "current_price": _parse_price(source.get("prices.amountMax", "0")),
        "raw_specs": _build_raw_specs(source),
        "product_images_description": _build_image_description(source),
    }
