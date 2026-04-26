"""Validate marketing copy against marketplace character limits and rules.

Deterministic tool that checks every field of the marketing copy against
the marketplace_rules seed data. Returns pass/fail per field and an
overall compliance verdict.

No LLM needed — counting characters is a tool's job.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def validate_marketplace_compliance(data: dict[str, Any]) -> dict[str, Any]:
    """Check marketing copy against marketplace character limits and required fields.

    Reads write_marketing_copy output and seed_data.marketplace_rules.
    Returns per-field results and overall compliance status.
    """
    # Extract marketing copy fields
    # Fields from observe: write_marketing_copy.* are flattened into content
    # Try nested first (action namespace), then flat (direct fields)
    write_marketing_copy = data.get("write_marketing_copy", {})
    if isinstance(write_marketing_copy, dict) and write_marketing_copy:
        listing_title = write_marketing_copy.get("listing_title", "")
        listing_description = write_marketing_copy.get("listing_description", "")
        bullet_points = write_marketing_copy.get("bullet_points", [])
        search_keywords = write_marketing_copy.get("search_keywords", [])
    else:
        listing_title = data.get("listing_title", "")
        listing_description = data.get("listing_description", "")
        bullet_points = data.get("bullet_points", [])
        search_keywords = data.get("search_keywords", [])

    # Extract marketplace rules (seed data arrives under "seed" namespace)
    seed = data.get("seed", {})
    if isinstance(seed, dict):
        marketplace_rules = seed.get("marketplace_rules", {})
    else:
        marketplace_rules = {}
    # Fallback: try top-level for backwards compatibility
    if not marketplace_rules:
        marketplace_rules = data.get("marketplace_rules", {})
    if not isinstance(marketplace_rules, dict):
        marketplace_rules = {}

    title_rules = marketplace_rules.get("title", {})
    desc_rules = marketplace_rules.get("description", {})
    bullet_rules = marketplace_rules.get("bullet_points", {})
    keyword_rules = marketplace_rules.get("search_keywords", {})
    required_fields = marketplace_rules.get("required_fields", [])

    field_results = []
    violations = []
    all_passed = True

    # --- Title validation ---
    title_max = title_rules.get("max_chars", 200)
    title_len = len(listing_title)
    title_passed = title_len <= title_max and title_len > 0

    field_results.append(
        {
            "field_name": "listing_title",
            "passed": title_passed,
            "actual_length": title_len,
            "max_allowed": title_max,
            "message": (
                f"Title OK ({title_len}/{title_max} chars)"
                if title_passed
                else f"Title {'empty' if title_len == 0 else f'exceeds limit ({title_len}/{title_max} chars)'}"
            ),
        }
    )

    if not title_passed:
        all_passed = False
        violations.append(
            f"Title {'is empty' if title_len == 0 else f'exceeds {title_max} char limit ({title_len} chars)'}"
        )

    # --- Description validation ---
    desc_max = desc_rules.get("max_chars", 2000)
    desc_len = len(listing_description)
    desc_passed = desc_len <= desc_max and desc_len > 0

    field_results.append(
        {
            "field_name": "listing_description",
            "passed": desc_passed,
            "actual_length": desc_len,
            "max_allowed": desc_max,
            "message": (
                f"Description OK ({desc_len}/{desc_max} chars)"
                if desc_passed
                else f"Description {'empty' if desc_len == 0 else f'exceeds limit ({desc_len}/{desc_max} chars)'}"
            ),
        }
    )

    if not desc_passed:
        all_passed = False
        violations.append(
            f"Description {'is empty' if desc_len == 0 else f'exceeds {desc_max} char limit ({desc_len} chars)'}"
        )

    # --- Bullet points validation ---
    max_bullets = bullet_rules.get("max_count", 5)
    max_bullet_chars = bullet_rules.get("max_chars_per_bullet", 250)
    bullet_count = len(bullet_points)
    bullet_count_passed = 0 < bullet_count <= max_bullets

    field_results.append(
        {
            "field_name": "bullet_points_count",
            "passed": bullet_count_passed,
            "actual_length": bullet_count,
            "max_allowed": max_bullets,
            "message": (
                f"Bullet count OK ({bullet_count}/{max_bullets})"
                if bullet_count_passed
                else f"Bullet count {'is 0' if bullet_count == 0 else f'exceeds max ({bullet_count}/{max_bullets})'}"
            ),
        }
    )

    if not bullet_count_passed:
        all_passed = False
        violations.append(
            f"{'No bullet points provided' if bullet_count == 0 else f'Too many bullets ({bullet_count}/{max_bullets})'}"
        )

    for idx, bullet in enumerate(bullet_points):
        b_len = len(bullet)
        b_passed = b_len <= max_bullet_chars and b_len > 0

        field_results.append(
            {
                "field_name": f"bullet_point_{idx + 1}",
                "passed": b_passed,
                "actual_length": b_len,
                "max_allowed": max_bullet_chars,
                "message": (
                    f"Bullet {idx + 1} OK ({b_len}/{max_bullet_chars} chars)"
                    if b_passed
                    else f"Bullet {idx + 1} exceeds limit ({b_len}/{max_bullet_chars} chars)"
                ),
            }
        )

        if not b_passed:
            all_passed = False
            violations.append(
                f"Bullet point {idx + 1} exceeds {max_bullet_chars} char limit ({b_len} chars)"
            )

    # --- Search keywords validation ---
    max_keywords = keyword_rules.get("max_count", 10)
    max_kw_chars = keyword_rules.get("max_chars_per_keyword", 50)
    kw_count = len(search_keywords)
    kw_count_passed = 0 < kw_count <= max_keywords

    field_results.append(
        {
            "field_name": "search_keywords_count",
            "passed": kw_count_passed,
            "actual_length": kw_count,
            "max_allowed": max_keywords,
            "message": (
                f"Keyword count OK ({kw_count}/{max_keywords})"
                if kw_count_passed
                else f"Keyword count issue ({kw_count}/{max_keywords})"
            ),
        }
    )

    if not kw_count_passed:
        all_passed = False
        violations.append(
            f"{'No search keywords provided' if kw_count == 0 else f'Too many keywords ({kw_count}/{max_keywords})'}"
        )

    for idx, kw in enumerate(search_keywords):
        kw_len = len(kw)
        kw_passed = kw_len <= max_kw_chars and kw_len > 0

        if not kw_passed:
            all_passed = False
            field_results.append(
                {
                    "field_name": f"search_keyword_{idx + 1}",
                    "passed": False,
                    "actual_length": kw_len,
                    "max_allowed": max_kw_chars,
                    "message": f"Keyword '{kw[:30]}...' exceeds {max_kw_chars} char limit ({kw_len} chars)",
                }
            )
            violations.append(f"Search keyword {idx + 1} exceeds {max_kw_chars} char limit")

    # --- Prohibited content check ---
    all_text = f"{listing_title} {listing_description} {' '.join(bullet_points)}"
    all_text_lower = all_text.lower()

    prohibited_patterns = {
        "unsubstantiated superlatives": [
            "best",
            "#1",
            "top-rated",
            "number one",
            "world's best",
            "industry-leading",
        ],
        "pricing or discount language": [
            "% off",
            "discount",
            "sale",
            "limited time",
            "free shipping",
            "buy now",
        ],
        "contact information or external URLs": ["http://", "https://", "www.", ".com", "@"],
    }

    for category, patterns in prohibited_patterns.items():
        for pattern in patterns:
            if pattern.lower() in all_text_lower:
                all_passed = False
                violations.append(f"Prohibited content ({category}): found '{pattern}'")
                field_results.append(
                    {
                        "field_name": "prohibited_content",
                        "passed": False,
                        "actual_length": 0,
                        "max_allowed": 0,
                        "message": f"Prohibited content: '{pattern}' found ({category})",
                    }
                )
                break  # one violation per category is enough

    # --- Brand name in title check ---
    brand = data.get("brand", "") or data.get("write_marketing_copy", {}).get("brand", "")
    if brand and brand.lower() not in listing_title.lower():
        all_passed = False
        violations.append(f"Title must include brand name '{brand}'")
        field_results.append(
            {
                "field_name": "title_brand_name",
                "passed": False,
                "actual_length": 0,
                "max_allowed": 0,
                "message": f"Brand name '{brand}' not found in title",
            }
        )

    # --- Bullet capitalization check ---
    for idx, bullet in enumerate(bullet_points):
        if bullet and not bullet[0].isupper():
            all_passed = False
            violations.append(f"Bullet {idx + 1} must start with a capitalized keyword")
            field_results.append(
                {
                    "field_name": f"bullet_{idx + 1}_capitalization",
                    "passed": False,
                    "actual_length": 0,
                    "max_allowed": 0,
                    "message": f"Bullet {idx + 1} does not start with a capital letter",
                }
            )

    # --- Required fields check ---
    present_fields = set()
    if listing_title:
        present_fields.add("listing_title")
    if listing_description:
        present_fields.add("listing_description")
    if bullet_points:
        present_fields.add("bullet_points")
    if search_keywords:
        present_fields.add("search_keywords")
    # product_category comes from source passthrough, always present in context
    present_fields.add("product_category")

    for req_field in required_fields:
        if req_field not in present_fields:
            all_passed = False
            violations.append(f"Required field missing: {req_field}")

    # Build summary
    passed_count = sum(1 for r in field_results if r["passed"])
    total_count = len(field_results)

    if all_passed:
        summary = f"All checks passed ({passed_count}/{total_count} fields compliant). Listing is marketplace-ready."
    else:
        summary = (
            f"{passed_count}/{total_count} fields passed. "
            f"{len(violations)} violation(s) found: {'; '.join(violations[:3])}"
            + ("..." if len(violations) > 3 else "")
        )

    return {
        "compliance_passed": all_passed,
        "field_results": field_results,
        "violations": violations,
        "summary": summary,
    }
