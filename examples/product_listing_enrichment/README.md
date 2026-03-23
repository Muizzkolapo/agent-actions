# Product Listing Enrichment

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that transforms raw product specs into marketplace-ready listings with competitive positioning, compliance validation, and SEO optimization.

**Pattern**: Tool + LLM Hybrid -- alternating between LLM reasoning and deterministic tool operations.

## The Pattern

LLM does language. Tools do data. Neither does the other's job.

```
 Raw Specs
    |
    v
 [1. generate_description]     LLM   -- Interpret specs into human language
    |
    v
 [2. fetch_competitor_prices]  TOOL  -- Look up market pricing data
    |
    v
 [3. write_marketing_copy]     LLM   -- Write copy with competitive positioning
    |
    v
 [4. validate_compliance]      TOOL  -- Check character limits & rules
    |
    v
 [5. optimize_seo]             LLM   -- Refine for search (guarded: only if compliant)
    |
    v
 [6. format_listing]           TOOL  -- Package final marketplace JSON
    |
    v
 Marketplace-Ready Listing
```

Why this alternation matters:

| Step | Type | Why this type? |
|------|------|----------------|
| generate_description | LLM | Translating raw specs ("40mm driver, 20Hz-40kHz") into benefits ("Rich, detailed audio across the full spectrum") requires language understanding |
| fetch_competitor_prices | Tool | Price lookups are data operations -- deterministic, no hallucination risk |
| write_marketing_copy | LLM | Crafting persuasive copy that weaves in competitive positioning requires creative reasoning |
| validate_compliance | Tool | Counting characters and checking field presence is exact math -- LLMs are unreliable at counting |
| optimize_seo | LLM | Understanding search intent and keyword relevance requires language understanding |
| format_listing | Tool | Assembling JSON structure is mechanical -- no creativity needed |

## Context Flow

Each action sees only what it needs. Context narrows as the pipeline progresses:

```
Source data (raw_specs, images, price, category, brand)
  |
  +-- generate_description
  |     sees: raw_specs, images, brand_voice
  |     produces: product_title, short_description, key_features, search_keywords
  |
  +-- fetch_competitor_prices
  |     sees: search_keywords, category, current_price
  |     produces: competitor_prices, price_position, average_competitor_price
  |
  +-- write_marketing_copy
  |     sees: generate_description.*, competitor pricing, brand_voice, marketplace_rules
  |     DROPS: source.raw_specs (already distilled by step 1)
  |     produces: listing_title, listing_description, bullet_points, search_keywords
  |
  +-- validate_compliance
  |     sees: write_marketing_copy.*, marketplace_rules
  |     produces: compliance_passed (bool), field_results, violations
  |
  +-- optimize_seo (GUARDED: only runs if compliance_passed == true)
  |     sees: write_marketing_copy.*, validate_compliance.*, category
  |     produces: optimized_title, primary_keywords, long_tail_keywords, backend_keywords
  |
  +-- format_listing
        sees: everything upstream + source passthrough fields
        produces: final marketplace-ready JSON
```

Key context decisions:
- **`source.raw_specs` is dropped** after step 1 -- the LLM already distilled it into readable language. Sending raw JSON to the copywriter wastes tokens and confuses the prompt.
- **`optimize_seo` is guarded** -- if the copy fails compliance, there is no point optimizing it for search. The guard (`compliance_passed == true`) prevents wasted LLM calls.
- **Seed data** (`brand_voice`, `marketplace_rules`) is injected at the workflow level and available to any action that needs it.

## Data

### Input (8 products across 4 categories)

| ID | Product | Category |
|----|---------|----------|
| PLE-001 | SoundWave Pro ANC Headphones | electronics |
| PLE-002 | ChefElite 12-Cup Food Processor | kitchen |
| PLE-003 | TrailMaster 55L Expedition Backpack | outdoor_gear |
| PLE-004 | ErgoDesk Pro Standing Desk Converter | home_office |
| PLE-005 | PureStream UV Water Purifier Bottle | outdoor_gear |
| PLE-006 | SmartBrew Precision Pour-Over Coffee System | kitchen |
| PLE-007 | LumoPanel LED Desk Lamp | home_office |
| PLE-008 | ThermoForge Cast Iron Dutch Oven 6Qt | kitchen |

Products have varying spec richness -- some have 12+ fields (PLE-006), others have 7 (PLE-005) -- to test how the pipeline handles different input quality.

### Seed Data

- **`brand_voice.json`** -- Tone guidelines, prohibited words, preferred phrases, target audience
- **`marketplace_rules.json`** -- Character limits (title: 200, description: 2000, bullets: 5x250), required fields, prohibited content rules

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a product_listing_enrichment
```

The workflow runs against the included 8-product sample in `agent_io/staging/`. To enrich your own products, drop a JSON file there:

```json
[
  {
    "product_id": "MY-001",
    "product_name": "Your Product Name",
    "product_category": "electronics",
    "brand": "YourBrand",
    "current_price": 99.99,
    "raw_specs": {
      "weight": "250g",
      "battery_life": "10 hours"
    },
    "product_images_description": "Product shown on a white background."
  }
]
```

Output is written to `agent_io/target/format_listing/`.

## File Structure

```
product_listing_enrichment/
|-- .env.example                          # API key template
|-- agent_actions.yml                     # Project config (model, schema/tool paths)
|-- README.md
|
|-- agent_workflow/product_listing_enrichment/
|   |-- agent_config/
|   |   +-- product_listing_enrichment.yml  # Workflow definition (6 actions)
|   |-- agent_io/staging/
|   |   +-- products.json                   # 8 sample products
|   +-- seed_data/
|       |-- brand_voice.json                # Tone & style guidelines
|       +-- marketplace_rules.json          # Character limits & field rules
|
|-- prompt_store/
|   +-- product_listing_enrichment.md       # 3 LLM prompts (describe, write, optimize)
|
|-- schema/product_listing_enrichment/
|   |-- generate_description.yml            # Step 1 output schema
|   |-- fetch_competitor_prices.yml         # Step 2 output schema
|   |-- write_marketing_copy.yml            # Step 3 output schema
|   |-- validate_compliance.yml             # Step 4 output schema
|   |-- optimize_seo.yml                    # Step 5 output schema
|   +-- format_listing.yml                  # Step 6 output schema
|
+-- tools/
    |-- __init__.py
    +-- product_listing_enrichment/
        |-- __init__.py
        |-- fetch_competitor_prices.py      # Mock competitor pricing lookup
        |-- validate_marketplace_compliance.py  # Character limit & rule checker
        +-- format_marketplace_listing.py   # Final JSON packager
```

## Customization

### Swap the pricing tool for a real API

Replace `fetch_competitor_prices.py` with a tool that calls your pricing API or database. The schema contract stays the same -- return `competitor_prices`, `price_position`, and `average_competitor_price`.

### Adjust marketplace rules

Edit `seed_data/marketplace_rules.json` to match your marketplace (Amazon, Shopify, eBay). The compliance tool reads limits dynamically from this file.

### Change the brand voice

Edit `seed_data/brand_voice.json` to match your brand. The LLM prompts reference `seed_data.brand_voice` for tone, prohibited words, and formatting rules.
