"""Fetch competitor pricing data for competitive positioning.

Mock tool that generates realistic competitor pricing based on the product
category and current price. In production, this would call a pricing API,
web scraper, or database.

Returns 3-5 competitor entries with +/-20% price variance and a summary
of where our product sits in the market.
"""

import hashlib
from typing import Any

from agent_actions import udf_tool

# Simulated competitor names by category
COMPETITORS_BY_CATEGORY = {
    "electronics": [
        ("AudioTech", "TechMart"),
        ("SonicBeat", "BestGear"),
        ("WaveAudio", "Amazon Basics"),
        ("BassKing", "GadgetHub"),
        ("ClearSound", "TechDirect"),
    ],
    "kitchen": [
        ("KitchenPro", "HomeChef Store"),
        ("CuisineMaster", "CookDirect"),
        ("PrepStation", "HomeGoods"),
        ("ChopSmart", "Williams & Home"),
        ("BlendWell", "Kitchen Outlet"),
    ],
    "outdoor_gear": [
        ("SummitPack", "REI Outlet"),
        ("WildTrail", "BackcountryGear"),
        ("PeakVenture", "CampDirect"),
        ("TerrainPro", "Outdoor World"),
        ("AlpineEdge", "TrailShop"),
    ],
    "home_office": [
        ("DeskWorks", "OfficeDirect"),
        ("PosturePro", "WorkSpace Co"),
        ("StandUp", "ErgoStore"),
        ("FlexDesk", "OfficeMax"),
        ("WorkEase", "DeskHub"),
    ],
}

# Fallback competitors for unknown categories
DEFAULT_COMPETITORS = [
    ("ValueBrand", "GeneralMart"),
    ("ProLine", "DirectShop"),
    ("CoreProduct", "MegaStore"),
    ("EssentialCo", "PrimeDeals"),
    ("StandardPro", "AllGoods"),
]


def _seeded_float(seed_str: str, min_val: float, max_val: float) -> float:
    """Generate a deterministic float from a seed string."""
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    normalized = (h % 10000) / 10000.0
    return min_val + normalized * (max_val - min_val)


@udf_tool()
def fetch_competitor_prices(data: dict[str, Any]) -> dict[str, Any]:
    """Generate simulated competitor pricing based on category and current price.

    Produces 3-5 competitor entries with realistic price variance and
    a market positioning summary.
    """
    current_price = float(data.get("current_price", 100.0))
    category = data.get("product_category", "general")
    keywords = data.get("search_keywords", [])

    # Use keywords as part of the seed for deterministic but varied results
    keyword_seed = "_".join(sorted(keywords[:3])) if keywords else category

    # Select competitors for this category
    competitor_pool = COMPETITORS_BY_CATEGORY.get(category, DEFAULT_COMPETITORS)

    # Determine how many competitors (3-5) based on a deterministic seed
    num_competitors = 3 + int(_seeded_float(f"count_{keyword_seed}", 0, 2.99))
    num_competitors = min(num_competitors, len(competitor_pool))

    competitor_prices = []
    prices_seen = []

    for i in range(num_competitors):
        brand_name, store_name = competitor_pool[i]

        # Generate a price with +/-20% variance, seeded deterministically
        variance = _seeded_float(f"price_{brand_name}_{keyword_seed}", -0.20, 0.20)
        comp_price = round(current_price * (1 + variance), 2)

        # Ensure price is reasonable (at least $5)
        comp_price = max(comp_price, 5.00)
        prices_seen.append(comp_price)

        # Generate a plausible product name
        category_labels = {
            "electronics": "Wireless ANC Headphones",
            "kitchen": "Multi-Function Food Processor",
            "outdoor_gear": "Expedition Backpack",
            "home_office": "Adjustable Standing Desk",
        }
        product_type = category_labels.get(category, "Comparable Product")

        competitor_prices.append(
            {
                "competitor_name": brand_name,
                "product_name": f"{brand_name} {product_type}",
                "price": comp_price,
                "source": store_name,
            }
        )

    # Calculate market position
    avg_price = round(sum(prices_seen) / len(prices_seen), 2) if prices_seen else current_price
    price_min = min(prices_seen) if prices_seen else current_price
    price_max = max(prices_seen) if prices_seen else current_price

    # Determine positioning
    price_diff_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0

    if price_diff_pct < -10:
        position = "below_average"
    elif price_diff_pct <= 10:
        position = "average"
    elif price_diff_pct <= 25:
        position = "above_average"
    else:
        position = "premium"

    return {
        "competitor_prices": competitor_prices,
        "price_position": position,
        "average_competitor_price": avg_price,
        "price_range": {
            "min": round(price_min, 2),
            "max": round(price_max, 2),
        },
    }
