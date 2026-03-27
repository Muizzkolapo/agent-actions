# book_catalog_enrichment

## What This Workflow Does and Why It Exists

Publishers, digital bookstores, and library systems routinely receive books with only the minimum metadata a vendor bothered to include: an ISBN, a title, some author names, and a one-line description. That is not enough to sell a book.

To publish a book in a modern catalog you need:

- A BISAC category code so retailers and libraries can shelve and surface it correctly
- A 150–250 word marketing description with a hook sentence, clear benefits, and a target audience
- SEO keywords, a meta title, and a meta description for discoverability
- A reading level assessment — difficulty, prerequisites, and estimated reading time — so the right reader finds it
- Similar title recommendations so browsers keep buying
- A quality gate that prevents half-enriched records from going live
- Separate, clean data views tailored to what SEO teams, product managers, and engineers each actually need

Doing this manually for thousands of books is slow and produces inconsistent results. This workflow automates the full enrichment pipeline end-to-end.

---

## Design Decisions

### 1. Each concern gets its own specialist

Rather than one large prompt that tries to do everything, each enrichment task is a separate LLM action with a focused prompt and schema. Classification doesn't know about SEO. The description writer doesn't know about reading level. This keeps prompts short, makes each action independently testable, and means you can swap models per action based on cost/quality tradeoffs.

### 2. Validation is built in, not bolted on

After every LLM step that produces a structured output, a deterministic tool action validates it. `validate_bisac` checks that codes are exactly 9 characters in the right prefix set. `validate_description` checks word count, benefit count, and scans for placeholder text. Both trigger automatic reprompting if the output fails — the LLM retries up to 3 times before the framework accepts the best available result.

### 3. Recommendations are grounded, not hallucinated

A naive prompt would ask the LLM to "suggest similar books" and get plausible-sounding but invented titles. Instead the pipeline uses a three-step grounded retrieval pattern:

```
LLM generates search criteria → Tool searches real seed catalog → LLM ranks from real candidates only
```

The ranking prompt explicitly forbids inventing titles. Every recommendation is a real book from `seed_data/book_catalog.json` — your catalog, not the model's training data.

### 4. Independent branches run in parallel

After the description is written, three enrichment tasks have no dependency on each other: SEO generation, search criteria generation, and reading level assessment. They run concurrently. `score_quality` waits for all three branches before proceeding.

### 5. Quality gates before output

A quality filter marks each record `passes_filter: true/false` based on minimum thresholds (score ≥ 3.0, ≥ 3 enriched fields, marked publication-ready). Records that fail are dropped before the final output step — you never get a half-enriched entry in production output.

### 6. Output is shaped per consumer

The final tool action builds three views from each enriched record — one for the SEO team, one for product management, one for engineering integrations. No consumer has to filter out fields they don't need or know the internal field names of the pipeline.

---

## Pipeline

```
                    ┌─────────────────────────┐
                    │     classify_genre      │  LLM
                    │  [reprompt: BISAC fmt]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     validate_bisac      │  Tool
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    write_description    │  LLM
                    │  [reprompt: word count] │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   validate_description  │  Tool
                    └───────────┬─────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
┌────────┴────────┐   ┌────────┴────────┐   ┌────────┴────────┐
│  generate_seo   │   │ generate_search │   │ assess_reading_ │  LLM × 3
│                 │   │    _criteria    │   │     level       │  (parallel)
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         │            ┌────────┴────────┐            │
         │            │retrieve_candid- │  Tool       │
         │            │     ates        │             │
         │            │[seed catalog]   │            │
         │            └────────┬────────┘            │
         │                     │                     │
         │            ┌────────┴────────┐            │
         │            │  generate_reco- │  LLM        │
         │            │  mmendations    │             │
         │            │[from real books]│            │
         │            └────────┬────────┘            │
         │                     │                     │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     score_quality       │  LLM  [merge all branches]
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │      format_entry       │  Tool
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │     filter_quality      │  Tool
                    └───────────┬─────────────┘
                                │  guard: passes_filter
                    ┌───────────┴─────────────┐
                    │    select_for_users     │  Tool
                    │  seo / mgmt / dev views │
                    └─────────────────────────┘
```

## Actions

| # | Name | Type | What it produces |
|---|------|------|-----------------|
| 1 | `classify_genre` | LLM | Primary + secondary BISAC codes |
| 2 | `validate_bisac` | Tool | Normalized, validated BISAC codes |
| 3 | `write_description` | LLM | 150–250 word marketing description, hook sentence, benefits |
| 4 | `validate_description` | Tool | Validation result and issue list |
| 5 | `generate_seo` | LLM | Primary/long-tail keywords, meta title, meta description |
| 6a | `generate_search_criteria` | LLM | Genre + keyword search parameters |
| 6b | `retrieve_candidates` | Tool | Real candidate books from seed catalog |
| 6c | `generate_recommendations` | LLM | Top 5 ranked from real candidates only |
| 7 | `assess_reading_level` | LLM | Difficulty, prerequisites, reading time |
| 8 | `score_quality` | LLM | 1–5 quality score across 4 dimensions |
| 9 | `format_entry` | Tool | Single consolidated catalog record |
| 10 | `filter_quality` | Tool | `passes_filter` boolean + reason |
| 11 | `select_for_users` | Tool | SEO, management, and developer views |

---

## Key Patterns

### Reprompt Validation

```yaml
reprompt:
  validation: "check_valid_bisac"
  max_attempts: 3
  on_exhausted: "return_last"
```

Registered `@reprompt_validation` UDFs run against the LLM output before it is accepted. If validation fails, the framework reprompts with the failure reason. Used on `classify_genre` (BISAC format) and `write_description` (minimum word count).

### Grounded Retrieval

```
LLM generates search criteria → Tool retrieves REAL books → LLM ranks from candidates only
```

The ranking prompt contains an explicit rule: *"DO NOT invent or hallucinate book titles — use exact titles from candidates."* Every recommendation traces back to a real entry in `seed_data/book_catalog.json`.

### Passthrough for Data Lineage

Source fields travel forward through the pipeline so deep actions can still read the original `isbn`, `title`, etc.:

```yaml
context_scope:
  passthrough:
    - source.isbn
    - source.title
    - source.authors
    - source.publisher
    - source.publish_year
    - source.page_count
    - source.description
```

Downstream actions access these as `write_description.isbn`, `write_description.title`, etc.

### Quality Gate

```yaml
guard:
  condition: 'passes_filter'
  on_false: filter
```

Only records that pass the quality thresholds (score ≥ 3.0, ≥ 3 enriched fields, marked publication-ready) reach `select_for_users`.

---

## Inputs

**Main input** (`agent_io/staging/`) — the books to enrich. Drop your catalog extract here. Each record flows through all 11 actions.

```json
[
  {
    "isbn": "9780134685991",
    "title": "Effective Java",
    "authors": ["Joshua Bloch"],
    "publisher": "Addison-Wesley Professional",
    "publish_year": 2018,
    "page_count": 412,
    "description": "Best practices for the Java platform."
  }
]
```

**Side input** (`seed_data/book_catalog.json`) — a read-only reference catalog used exclusively by `retrieve_candidates` for grounded recommendation lookups. Never written to. Ships with ~80 curated technical books. Extend it with data from [Open Library](https://openlibrary.org/developers/api), [Google Books API](https://developers.google.com/books), or [ISBNdb](https://isbndb.com).

Required side input format:
```json
{
  "isbn": "978-...",
  "title": "...",
  "authors": ["..."],
  "genres": ["COM051000"],
  "description": "...",
  "keywords": ["..."]
}
```

**Output** — per-action results in `agent_io/target/<action_name>/`. Final consumer output is `target/select_for_users/`.

### select_for_users output shape

```json
{
  "isbn": "9780134685991",
  "title": "Effective Java",
  "seo_view": {
    "meta_title": "Effective Java: Best Practices for the Java Platform",
    "meta_description": "Master Java development...",
    "seo_keywords": ["effective java", "java best practices"],
    "target_audience": "Intermediate to senior Java developers",
    "marketing_description": "...",
    "hook_sentence": "Write Java code that lasts.",
    "key_selling_points": ["78 best-practice items", "Covers modern Java"]
  },
  "management_view": {
    "catalog_id": "CAT-685991",
    "quality_score": 4.2,
    "publication_ready": true,
    "primary_category": "Programming / General",
    "enriched_fields": ["classification", "marketing_description", "seo_keywords", "recommendations", "reading_level"],
    "filter_reason": "Passed all quality checks"
  },
  "developer_view": {
    "bisac_codes": ["COM051280", "COM051000"],
    "difficulty_level": "Intermediate",
    "experience_required": "2-4 years",
    "prerequisites": ["Basic Java syntax", "OOP concepts"],
    "reading_time_hours": "20 hours",
    "similar_titles": [{"isbn": "...", "title": "Clean Code"}],
    "reading_path": "Read Effective Java first, then Clean Code for style."
  }
}
```

---

## Customization

| What | Where |
|------|-------|
| BISAC valid prefixes | `tools/book_catalog_enrichment/validate_bisac_codes.py` |
| Quality filter thresholds | `tools/book_catalog_enrichment/filter_by_quality.py` |
| Reprompt attempts | `max_attempts` in `agent_config/book_catalog_enrichment.yml` |
| Search backend (vector DB / SQL) | `tools/book_catalog_enrichment/search_book_catalog.py` |
| User view field selection | `tools/book_catalog_enrichment/select_for_users.py` |
| Prompts | `prompt_store/book_catalog_enrichment.md` |
| Models per action | `model_name` / `model_vendor` in `agent_config/book_catalog_enrichment.yml` |
