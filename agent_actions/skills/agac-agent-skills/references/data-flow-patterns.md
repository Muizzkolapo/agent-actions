# Data Flow Patterns

## Source Data Format

Source must be a **flat array of records**, not a wrapper object.

```json
[
  {"id": "abc123", "page_content": "Content here..."},
  {"id": "def456", "page_content": "More content..."}
]
```

Wrapper objects (`{"exam_name": "...", "scraped_links": [...]}`) fail with:
```
PreFlightValidationError: Template references undefined variables
missing_references=['source.page_content']
```

Fixes: extract array to staging, add File-mode preprocessing tool, or iterate with `{% for link in source.scraped_links %}`.

## Directory Structure

```
agent_workflow/<workflow>/
  agent_config/<workflow>.yml       # Names must match (underscores, not hyphens)
  agent_io/
    staging/     # INPUT: your raw files
    source/      # AUTO-GENERATED: framework adds metadata (don't touch)
    target/      # OUTPUT: per-action subdirectories
  seed_data/     # Reference data for grounded retrieval
tools/<workflow>/                   # UDFs
prompt_store/                       # Prompt templates
schema/                             # Output schemas
```

Flow: `staging/ -> source/ (adds source_guid, node_id, lineage) -> target/<action>/`

## Metadata Fields

| Field | Changes per node | Purpose |
|-------|:---:|---------|
| `source_guid` | Never | Original content UUID |
| `target_id` | New each node | This node's output UUID |
| `node_id` | New each node | Node identifier (includes index when flattened) |
| `lineage` | Grows | Array of all visited node_ids |

## Data Shapes

### Record mode (default)
UDF receives one record, `content` wrapper stripped:
```json
{
  "extract_claims": {"claims": ["claim 1"], "confidence": 0.85},
  "seed": {"rubric": {"min_score": 7}}
}
```
Access: `data["extract_claims"]["claims"]`

### File mode
UDF receives ALL records as list, `content` wrapper retained:
```json
[
  {"content": {"extract_claims": {"claims": ["claim 1"]}}, "source_guid": "abc-123", "lineage": [...]},
  {"content": {"extract_claims": {"claims": ["claim 2"]}}, "source_guid": "abc-123", "lineage": [...]}
]
```
Access: `record["content"]["extract_claims"]["claims"]`

### Version merge
After `version_consumption: {pattern: merge}`, namespaced by expanded action name:
```json
{
  "score_quality_1": {"score": 8},
  "score_quality_2": {"score": 6},
  "score_quality_3": {"score": 9}
}
```

### Seed data
Under `seed` namespace, keyed by `seed_path:` name:
```json
{"seed": {"rubric": {"min_score": 7, "categories": ["accuracy", "clarity"]}}}
```
Access: `data["seed"]["rubric"]["min_score"]`

## Cross-Workflow Chaining

Declare `upstream` at workflow level. Upstream actions injected as virtual completed actions -- downstream reads directly from upstream's output directories.

```yaml
name: enrich
upstream:
  - workflow: ingest
    actions: [extract, classify]

actions:
  - name: enrich_text
    dependencies: [extract]
    context_scope:
      observe: [extract.*, classify.category]
```

```bash
agac run -a ingest                  # Run upstream only
agac run -a enrich                  # Run downstream (upstream must exist)
agac run -a ingest --downstream     # Run ingest then everything after
agac run -a enrich --upstream       # Run ingest first, then enrich
```

## Grounded Retrieval

Prevent hallucination by constraining LLM to real data: LLM generates search criteria -> tool retrieves real candidates -> LLM ranks from candidates only.

```yaml
- name: generate_search_criteria
  schema: search_criteria           # {query_text, categories, keywords}

- name: retrieve_candidates
  kind: tool
  impl: search_catalog              # Returns real items from DB/seed

- name: rank_results
  dependencies: [retrieve_candidates]
  context_scope:
    observe: [retrieve_candidates.results]  # LLM sees only real items
```

Seed catalog: `defaults.context_scope.seed_path.catalog: $file:catalog.json` in `seed_data/`.

## Passthrough at Merge Points

Parallel branches merging lose upstream data without explicit passthrough:

```yaml
- name: score_quality
  dependencies: [enrich_metadata, generate_summary]
  context_scope:
    passthrough:
      - source.id
      - enrich_metadata.enriched_data
      - generate_summary.summary_text
```

| Scenario | Need passthrough? |
|----------|:-:|
| LLM action followed by tool needing full context | Yes |
| Parallel branches merging before formatting | Yes |
| Sequential LLM actions adding fields | Usually no |
| Tool actions (UDFs return full data) | Usually no |

## Gotchas

- Source data must be flat array, not wrapper object
- Use underscores in names (`incident_triage` not `incident-triage`)
- Never modify `source_guid`
- UDFs should add fields, not replace: `data['new_field'] = x; return data`
- `source/` is auto-generated -- don't place files there manually
