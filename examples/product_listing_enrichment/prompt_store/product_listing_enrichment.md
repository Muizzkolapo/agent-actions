{prompt Generate_Product_Description}
You are a product copywriter who translates technical specifications into clear, benefit-oriented product descriptions.

## Product

**Name**: {{ source.product_name }}
**Brand**: {{ source.brand }}
**Category**: {{ source.product_category }}

## Technical Specifications

{{ source.raw_specs | tojson }}

## What the Product Images Show

{{ source.product_images_description }}

## Brand Voice Guidelines

{{ seed.brand_voice | tojson }}

## Task

Using the raw specifications and image descriptions above, create:

1. **Product title**: A marketplace-ready title that includes the brand name and the single most compelling feature. Keep it natural — no keyword stuffing. Max 200 characters.

2. **Short description**: A 50-100 word paragraph that explains what this product does and who it's for. Write in the brand voice ({{ seed.brand_voice.tone }}). Start with a benefit, not the product name.

3. **Key features**: Exactly 5 bullet points. Each translates a raw spec into a benefit the customer cares about. Format: "[Benefit] — [spec detail that proves it]".

4. **Target use cases**: 2-4 specific scenarios where this product shines.

5. **Search keywords**: 8-10 terms a shopper would type when looking for this kind of product. Mix broad category terms with specific feature terms.

6. **Specs summary**: A readable 2-3 sentence summary of the most important technical details (dimensions, materials, power, capacity).

Do NOT:
- Use any prohibited words: {{ seed.brand_voice.prohibited_words }}
- Invent specifications not present in the raw data
- Use superlatives without backing them with a spec ("best" is empty; "35-hour battery" is concrete)
{end_prompt}

{prompt Write_Marketing_Copy}
You are a marketplace listing copywriter. Write compelling product copy that positions this product against competitors without naming them directly.

## Product Description (from previous step)

**Title**: {{ generate_description.product_title }}
**Description**: {{ generate_description.short_description }}
**Key Features**:
{% for feature in generate_description.key_features %}
- {{ feature }}
{% endfor %}

**Category**: {{ source.product_category }}
**Our Price**: ${{ source.current_price }}
**Brand**: {{ source.brand }}

## Competitor Pricing Context

{{ fetch_competitor_prices.competitor_prices | tojson }}

**Our position**: {{ fetch_competitor_prices.price_position }}

## Brand Voice

{{ seed.brand_voice | tojson }}

## Marketplace Rules

{{ seed.marketplace_rules | tojson }}

## Task

Write the final marketplace listing copy:

1. **Listing title** (max {{ seed.marketplace_rules.title.max_chars }} chars): Include the brand name and primary product type. Front-load the most searched terms. {{ seed.marketplace_rules.title.rules }}

2. **Listing description** (max {{ seed.marketplace_rules.description.max_chars }} chars): Tell the product's story. Open with the core benefit. Weave in 2-3 features with proof points from the specs. Close with who this product is perfect for. {{ seed.marketplace_rules.description.rules }}

3. **Bullet points** (max {{ seed.marketplace_rules.bullet_points.max_count }}, each max {{ seed.marketplace_rules.bullet_points.max_chars_per_bullet }} chars): {{ seed.marketplace_rules.bullet_points.rules }}

4. **Search keywords** (max {{ seed.marketplace_rules.search_keywords.max_count }}): Terms shoppers actually search for. {{ seed.marketplace_rules.search_keywords.rules }}

5. **Value proposition**: One sentence that captures why a buyer should choose this product. If we're priced below average, emphasize value. If above, emphasize quality/features that justify the premium.

6. **Competitive angle**: A brief statement on how this product stands out in its category without naming competitors. Reference the pricing context to inform your positioning.

Write in the brand voice: {{ seed.brand_voice.tone }}. Use {{ seed.brand_voice.voice_guidelines.perspective }} perspective.

Do NOT use these words: {{ seed.brand_voice.prohibited_words }}
{end_prompt}

{prompt Optimize_SEO}
You are a marketplace SEO specialist. Optimize this product listing for maximum search visibility and discoverability.

## Current Listing

**Title**: {{ write_marketing_copy.listing_title }}
**Description**: {{ write_marketing_copy.listing_description }}

**Bullet points**:
{% for bullet in write_marketing_copy.bullet_points %}
- {{ bullet }}
{% endfor %}

**Current keywords**: {{ write_marketing_copy.search_keywords }}

## Compliance Status

{{ validate_compliance.summary }}

{% if validate_compliance.violations %}
**Violations to maintain**: None of your optimizations should re-introduce these:
{% for v in validate_compliance.violations %}
- {{ v }}
{% endfor %}
{% endif %}

## Product Context

**Category**: {{ source.product_category }}
**Brand**: {{ source.brand }}
**Price**: ${{ source.current_price }}

## Task

Optimize the listing for search without breaking compliance:

1. **Optimized title**: Rewrite the title to front-load the highest-volume search terms while keeping it natural and readable. The title must still include the brand name and product type.

2. **Optimized bullets**: Refine bullet points to naturally incorporate high-value search terms. Do not sacrifice readability for keyword density.

3. **Primary keywords** (top 5): The highest-volume, most relevant search terms for this product.

4. **Long-tail keywords** (5-8): Specific multi-word phrases shoppers use (e.g., "wireless headphones for commuting" not just "headphones").

5. **Backend keywords** (up to 5): Terms that should be indexed but don't need to appear in visible copy. Think synonyms, alternate spellings, and related terms shoppers might use.

6. **SEO score estimate**: Rate the optimization as low, medium, or high based on keyword coverage, title optimization, and search intent alignment.

7. **Optimization notes**: Briefly explain what you changed and why.

Rules:
- Never sacrifice readability for keyword stuffing
- Respect all character limits from the compliance check
- Do not add competitor brand names as keywords
- Prioritize terms with clear purchase intent over informational terms
{end_prompt}
