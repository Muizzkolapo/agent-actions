# agent-actions Examples

Six workflows demonstrating agent-actions patterns — from single-vendor local models to multi-vendor parallel pipelines with human review.

## Examples

| Example | Actions | Vendors | Key Patterns |
|---------|---------|---------|--------------|
| [review_analyzer](./review_analyzer) | 8 | Groq, Ollama, OpenAI | Parallel consensus voting (3 scorers), version merge, guards, progressive context (observe/drop/passthrough), seed data |
| [incident_triage](./incident_triage) | 11 | Groq, Ollama, OpenAI | Parallel severity voting (3 classifiers), conditional escalation (SEV1/SEV2 guard), multi-seed data, parallel impact branches |
| [product_listing_enrichment](./product_listing_enrichment) | 6 | Gemini, OpenAI | Strict LLM/Tool alternation, progressive context (drop raw_specs after distillation), guard-based skip, seed data |
| [support_resolution](./support_resolution) | 7 | Ollama | `json_mode: false`, `output_field` (no schema needed), works with any model including local 3B, guard as cost control |
| [contract_reviewer](./contract_reviewer) | 4 | OpenAI | Map-Reduce (split → per-clause analysis → FILE granularity aggregate), context scoping with drop |
| [book_catalog_enrichment](./book_catalog_enrichment) | 15 | Ollama, Groq, OpenAI | HITL review, reprompt validation, grounded recommendations (LLM → Tool search → LLM rank), 4-way parallel fan-out |

## Quick Start

```bash
pip install agent-actions

# Pick any example and run it
cd examples/review_analyzer
agac run -a review_analyzer
```

All workflows default to `record_limit: 2` for quick testing. Remove or increase that setting in the workflow YAML to process full datasets.

## Requirements

- Python 3.10+
- API keys for the vendors each example uses (see the example's README)
- For Ollama examples: `ollama pull llama3.2:latest`

## Pattern Index

| Pattern | Examples |
|---------|----------|
| Parallel voting + merge | review_analyzer, incident_triage |
| Guards (conditional execution) | All except contract_reviewer |
| Multi-vendor model selection | review_analyzer, incident_triage, product_listing_enrichment, book_catalog_enrichment |
| Retry + reprompt validation | All (retry); review_analyzer, incident_triage, product_listing_enrichment, contract_reviewer, book_catalog_enrichment (reprompt) |
| Seed data injection | All |
| Progressive context (observe/drop/passthrough) | All |
| Map-Reduce + FILE granularity | contract_reviewer |
| HITL (human-in-the-loop) review | book_catalog_enrichment |
| Grounded retrieval (anti-hallucination) | book_catalog_enrichment |
| Non-JSON mode + output_field | support_resolution |
| Local model support (Ollama) | support_resolution, review_analyzer, incident_triage, book_catalog_enrichment |

## Project Structure

Every example follows the same layout:

```
<example>/
├── README.md                         # What it does, patterns taught, quick start
├── agent_actions.yml                 # Project-level config
├── docs/
│   └── flow.png                      # Pipeline diagram
├── agent_workflow/
│   └── <workflow>/
│       ├── agent_config/
│       │   └── <workflow>.yml        # Workflow definition (actions, deps, guards)
│       ├── agent_io/
│       │   ├── staging/              # Input data
│       │   └── target/               # Output per action
│       └── seed_data/                # Reference data injected into context
├── prompt_store/
│   └── <workflow>.md                 # LLM prompt templates
├── schema/
│   └── <workflow>/                   # Output schemas per action
└── tools/
    ├── <workflow>/                   # Tool implementations (UDFs)
    └── shared/                       # Shared reprompt validations
        └── reprompt_validations.py
```
