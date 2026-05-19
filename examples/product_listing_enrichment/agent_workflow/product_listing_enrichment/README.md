# Product Listing Enrichment

<p align="center"><img src="docs/flow.png" width="700"/></p>

A seven-action pipeline that transforms raw product data into marketplace-ready listings. It alternates strictly between LLM actions (language generation) and Tool actions (deterministic operations), demonstrating how to divide work by capability: LLMs handle language, tools handle data.

## Dataset

**Source**: [Datafiniti Electronic Products and Pricing Data](https://www.kaggle.com/datasets/datafiniti/electronic-products-prices) (Kaggle)

The full dataset contains 15,000+ electronic product records with pricing information across 10 fields including brand, category, merchant, name, and source. We use a curated subset of **75 records** selected for diversity across product categories.

| Category | Records | Example Products |
|----------|---------|-----------------|
| electronics | 20 | Speakers, headphones, cameras, audio equipment |
| home_office | 20 | TVs, monitors, computers, networking gear, mounts |
| outdoor_gear | 20 | Mobile phones, wearables, fitness devices, GPS |
| kitchen | 15 | Appliances, coffee makers, blenders |

The original 8 hand-crafted records are preserved in `docs/products_handcrafted_backup.json`.

### Why a normalize step?

The raw Kaggle data has a different shape than what the pipeline expects. Rather than modifying all 6 downstream actions, prompts, and tools, we added a single `normalize_product` tool as the first step. It transforms the Kaggle schema into the pipeline's expected schema:

| Kaggle Field | Pipeline Field | Transformation |
|-------------|---------------|----------------|
| `id` | `product_id` | Prefixed with "PLE-" |
| `name` | `product_name` | Trimmed |
| `categories` | `product_category` | Keyword-mapped to: electronics, home_office, outdoor_gear, kitchen |
| `brand` | `brand` | Passthrough (default "Unknown") |
| `prices.amountMax` | `current_price` | Parsed from string to float |
| `weight`, `manufacturer`, `manufacturerNumber`, `upc`, etc. | `raw_specs` | Assembled into structured dict |
| `imageURLs` | `product_images_description` | Count-based text or fallback |

This pattern (normalize step + unchanged downstream) is the recommended way to swap datasets in agent-actions workflows.

## What You'll Learn

This example teaches five patterns that appear repeatedly in production agent workflows:

1. **Data normalization step** -- adapting external data to an existing pipeline without modifying downstream actions, prompts, or tools.
2. **LLM/Tool hybrid pipeline** -- structuring a workflow so that LLMs and tools alternate, each doing what the other cannot.
3. **Progressive context disclosure** -- controlling exactly what each action sees, and dropping context once it's been distilled into a better form.
4. **Guard-based conditional skip** -- making an action run only when a previous action's output meets a condition.
5. **Seed data injection** -- providing static reference material (brand guidelines, marketplace rules) that shapes LLM behavior without being part of the input records.

## The Problem

A marketplace seller has raw product data -- technical specs, images, a category, and a price. Turning that into a published listing requires several kinds of work:

- **Language work**: describing specs in human terms, writing persuasive copy, optimizing for search. These require understanding nuance, tone, and intent. An LLM is the right tool.
- **Data work**: looking up competitor prices, checking character limits, assembling final JSON. These are deterministic and exact. A traditional function is the right tool.

Mixing these responsibilities in a single LLM call produces unreliable results -- LLMs miscount characters and hallucinate pricing data. A strict LLM-Tool-LLM-Tool pipeline gives you the best of both.

## How It Works

The pipeline has 7 actions in strict sequence:

### Action 0: `normalize_product` (Tool)

Transforms raw Kaggle CSV-shaped records into the schema the rest of the pipeline expects. Maps categories via keyword matching, parses prices from strings, builds a structured `raw_specs` dict from weight/manufacturer/UPC fields, and generates image descriptions from URL metadata.

Observes `source.*` (raw Kaggle fields). Outputs 7 normalized fields that replace `source.*` for all downstream actions.

### Action 1: `generate_description` (LLM)

Takes the normalized specs, product images description, and brand voice seed data. The LLM translates technical specifications into a benefit-oriented description, key features, search keywords, and use cases.

Observes `normalize_product.raw_specs`, `normalize_product.product_images_description`, `normalize_product.product_name`, `normalize_product.brand`, and `seed.brand_voice`. Passes through `normalize_product.product_id`, `normalize_product.product_category`, and `normalize_product.current_price`.

### Action 2: `fetch_competitor_prices` (Tool)

A deterministic function that looks up competitor pricing based on category and price. In production this would call a pricing API.

Observes `generate_description.search_keywords`, `normalize_product.product_category`, `normalize_product.current_price`.

### Action 3: `write_marketing_copy` (LLM)

Now the LLM has both the product description (from step 1) and competitor pricing (from step 2). It writes marketplace listing copy that positions the product against the competition. `normalize_product.raw_specs` is dropped here -- already distilled into readable language in step 1.

### Action 4: `validate_compliance` (Tool)

Checks the marketing copy against marketplace rules: character limits, required fields, prohibited content.

### Action 5: `optimize_seo` (LLM, guarded)

Optimizes keywords and titles for search ranking. **Guarded**: only runs if `compliance_passed == true` from the previous step.

### Action 6: `format_listing` (Tool)

Assembles all upstream outputs into the final marketplace-ready JSON structure.

## Key Patterns Explained

### 1. Data Normalization (New)

When swapping datasets, add a normalize tool as step 0 rather than modifying every downstream action:

```yaml
- name: normalize_product
  kind: tool
  impl: normalize_product
  intent: "Transform raw Kaggle product data into the enrichment pipeline's expected schema"
  schema: normalize_product
  context_scope:
    observe:
      - source.*
```

Then update `generate_description` to depend on `normalize_product` and observe `normalize_product.*` instead of `source.*`. All other actions reference `normalize_product.*` through passthrough chains. The original 6 actions, their prompts, and their tool implementations remain untouched.

### 2. LLM/Tool Hybrid Pipeline

The core design principle: LLMs do language, tools do data. Every action is explicitly typed. LLM actions have a `prompt` reference. Tool actions have `kind: tool` and an `impl` pointing to a Python function.

### 3. Progressive Context Disclosure

Each action sees only what it needs. The `context_scope` block controls this with three directives:

- **`observe`** -- the action can read these fields
- **`passthrough`** -- forwarded unchanged, without processing
- **`drop`** -- explicitly removed from context going forward

### 4. Guard-Based Conditional Skip

The `optimize_seo` action uses a guard to skip when compliance fails:

```yaml
guard:
  condition: 'validate_compliance.compliance_passed == true'
  on_false: "skip"
```

### 5. Seed Data Injection

Static reference material (brand voice, marketplace rules) is defined once in `defaults` and available to any action via `seed.*`.

## Quick Start

```bash
pip install agent-actions-cli
export OLLAMA_API_KEY=...
agac run -a product_listing_enrichment
```

The pipeline processes each product in `agent_io/staging/products.json` through all 7 actions and writes results to `agent_io/target/`.

## Project Structure

```
product_listing_enrichment/
├── README.md
├── docs/
│   └── products_handcrafted_backup.json
├── agent_actions.yml
├── agent_workflow/
│   └── product_listing_enrichment/
│       ├── agent_config/
│       │   └── product_listing_enrichment.yml
│       ├── agent_io/
│       │   ├── staging/
│       │   │   └── products.json          # 75 Kaggle records
│       │   └── target/
│       └── seed_data/
│           ├── brand_voice.json
│           └── marketplace_rules.json
├── prompt_store/
│   └── product_listing_enrichment.md
├── schema/
│   └── product_listing_enrichment/
│       ├── normalize_product.yml           # NEW
│       ├── generate_description.yml
│       ├── fetch_competitor_prices.yml
│       ├── write_marketing_copy.yml
│       ├── validate_compliance.yml
│       ├── optimize_seo.yml
│       └── format_listing.yml
└── tools/
    ├── product_listing_enrichment/
    │   ├── normalize_product.py            # NEW
    │   ├── fetch_competitor_prices.py
    │   ├── validate_marketplace_compliance.py
    │   └── format_marketplace_listing.py
    └── shared/
        └── reprompt_validations.py
```
