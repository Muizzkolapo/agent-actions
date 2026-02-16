# Book Catalog Enrichment Pipeline

Enrich book catalog entries with BISAC classification, marketing descriptions, SEO keywords, recommendations, and quality scoring.

## Overview

This workflow demonstrates a production-ready catalog enrichment pipeline that combines LLM-powered content generation with grounded retrieval to prevent hallucination in recommendations.

## Workflow Diagram

```
                    ┌─────────────────────────┐
                    │     classify_genre      │
                    │        (LLM)            │
                    │  [reprompt: BISAC check]│
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     validate_bisac      │
                    │        (Tool)           │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    write_description    │
                    │        (LLM)            │
                    │ [reprompt: word count]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   validate_description  │
                    │        (Tool)           │
                    └───────────┬─────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
┌────────┴────────┐   ┌────────┴────────┐   ┌────────┴────────┐
│  generate_seo   │   │generate_search_ │   │assess_reading_  │
│     (LLM)       │   │    criteria     │   │     level       │
└────────┬────────┘   │     (LLM)       │   │     (LLM)       │
         │            └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         │            ┌────────┴────────┐            │
         │            │retrieve_candidates│           │
         │            │     (Tool)       │            │
         │            │[grounded search] │            │
         │            └────────┬────────┘            │
         │                     │                     │
         │            ┌────────┴────────┐            │
         │            │generate_recommend-│           │
         │            │     ations       │            │
         │            │     (LLM)        │            │
         │            │[from candidates] │            │
         │            └────────┬────────┘            │
         │                     │                     │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     score_quality       │
                    │        (LLM)            │
                    │   [merge all branches]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │      format_entry       │
                    │        (Tool)           │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     filter_quality      │
                    │        (Tool)           │
                    └─────────────────────────┘
```

## Key Patterns Demonstrated

### 1. Reprompt Validation
Automatic retry when LLM output fails validation:
```yaml
reprompt:
  validation: "check_valid_bisac"  # UDF that validates output
  max_attempts: 3
  on_exhausted: "return_last"
```

### 2. Grounded Retrieval (Prevents Hallucination)
Three-step pattern ensuring recommendations come from real catalog data:
```
LLM generates search criteria → Tool retrieves REAL books → LLM ranks from candidates only
```

```yaml
# Step 1: LLM generates what to search for
- name: generate_search_criteria
  schema: search_criteria
  prompt: $book_catalog_enrichment.Generate_Search_Criteria

# Step 2: Tool searches actual catalog (abstraction layer)
- name: retrieve_candidates
  kind: tool
  impl: search_book_catalog  # Can swap backend (vector/SQL/JSON)

# Step 3: LLM ranks ONLY from retrieved candidates
- name: generate_recommendations
  prompt: "...ONLY recommend books from the candidate list..."
```

### 3. Parallel Branch Processing
Multiple enrichments run concurrently, then merge:
```yaml
# These run in parallel (no dependency between them)
- name: generate_seo
  dependencies: [write_description]

- name: generate_search_criteria
  dependencies: [write_description]

- name: assess_reading_level
  dependencies: [write_description]
```

### 4. Passthrough for Data Lineage
Preserve source fields through the pipeline:
```yaml
context_scope:
  observe:
    - validate_bisac.*
  passthrough:
    - validate_bisac.isbn
    - validate_bisac.title
    - validate_bisac.authors
```

### 5. Quality Scoring with Merge
Final scoring action merges all parallel branches:
```yaml
- name: score_quality
  dependencies: [generate_recommendations]  # Waits for slowest branch
  context_scope:
    observe:
      - generate_recommendations.*
      - generate_seo.*
      - assess_reading_level.*
      - write_description.*
```

## Data Flow

```
agent_io/
├── staging/          # Place book catalog JSON here
│   └── books_sample.json
├── source/           # Auto-generated with metadata
└── target/           # Output from each action
    ├── classify_genre/
    ├── validate_bisac/
    ├── write_description/
    ├── validate_description/
    ├── generate_seo/
    ├── generate_search_criteria/
    ├── retrieve_candidates/
    ├── generate_recommendations/
    ├── assess_reading_level/
    ├── score_quality/
    ├── format_entry/
    └── filter_quality/
```

## Input Format

Place book data in `agent_io/staging/`:

```json
[
  {
    "isbn": "978-0134685991",
    "title": "Effective Java",
    "authors": ["Joshua Bloch"],
    "publisher": "Addison-Wesley",
    "publish_year": 2018,
    "page_count": 416,
    "description": "The definitive guide to Java platform best practices..."
  }
]
```

## Output

The final `filter_quality` produces enriched catalog entries:

```json
{
  "isbn": "978-0134685991",
  "title": "Effective Java",
  "authors": ["Joshua Bloch"],

  "classification": {
    "bisac_codes": ["COM051010"],
    "bisac_names": ["Programming / Object-Oriented"]
  },

  "marketing": {
    "description": "Master Java with this essential guide...",
    "hook_sentence": "Write better Java code today.",
    "key_benefits": ["Best practices", "Modern patterns"],
    "target_audience": "Intermediate Java developers"
  },

  "seo": {
    "primary_keywords": ["java programming", "effective java"],
    "meta_title": "Effective Java - Best Practices Guide",
    "meta_description": "..."
  },

  "recommendations": {
    "similar_books": [
      {"isbn": "978-...", "title": "Clean Code", "relationship": "Complements with code quality focus"}
    ],
    "reading_path": "Read Effective Java first, then Clean Code"
  },

  "reading_level": {
    "level": "Intermediate",
    "prerequisites": ["Basic Java syntax", "OOP concepts"],
    "estimated_reading_time": "20 hours"
  },

  "quality": {
    "overall_score": 4.5,
    "ready_for_publication": true
  }
}
```

## Seed Data

Reference data in `seed_data/`:
- `book_catalog.json` - Full catalog for grounded retrieval searches

## Running the Workflow

```bash
# Run the pipeline
agac run -a book_catalog_enrichment
```

## Tools

| Tool | Purpose |
|------|---------|
| `validate_bisac_codes` | Validate and normalize BISAC classification |
| `validate_description` | Check marketing description quality |
| `search_book_catalog` | Grounded retrieval from catalog (swappable backend) |
| `format_catalog_entry` | Structure final enriched entry |
| `filter_by_quality` | Filter entries below quality threshold |

## Reprompt Validations

Defined in `tools/reprompt_validations.py`:

| Validation | Purpose |
|------------|---------|
| `check_valid_bisac` | Validates BISAC codes against known list |
| `check_description_word_count` | Ensures marketing description has 50+ words |

## Customization

- **BISAC validation**: Update valid codes in `validate_bisac_codes.py`
- **Quality thresholds**: Modify `filter_by_quality.py`
- **Search backend**: Swap `search_book_catalog.py` implementation (vector/SQL/API)
- **Reprompt attempts**: Adjust `max_attempts` in workflow YAML

## Why Grounded Retrieval?

Without grounding, LLMs will hallucinate book recommendations - inventing titles, authors, and ISBNs that don't exist. The grounded retrieval pattern:

1. **Generates search criteria** - LLM describes what similar books would look like
2. **Retrieves real candidates** - Tool searches actual catalog database
3. **Ranks from candidates only** - LLM selects from verified real books

This ensures every recommended book actually exists in your catalog.
