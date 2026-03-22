# Book Catalog Enrichment

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that turns raw book metadata into production-ready catalog entries — BISAC classification, marketing copy, SEO metadata, reading level, grounded recommendations, and per-user views.

## Install

```bash
pip install agent-actions
```

Optionally install the AI coding assistant skills to get workflow-aware help inside your editor:

```bash
agac skills install --claude   # Claude Code
agac skills install --codex    # OpenAI Codex
```

## Run

```bash
agac run -a book_catalog_enrichment
```

The workflow runs against the included 80-book sample in `agent_io/staging/`. To enrich your own books, drop a JSON file there first:

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

Output is written to `agent_io/target/select_for_users/`.

## Learn More

See [`agent_workflow/book_catalog_enrichment/README.md`](agent_workflow/book_catalog_enrichment/README.md) for the full pipeline design, patterns, and customization guide.
