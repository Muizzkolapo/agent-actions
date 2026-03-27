# Data Flow Patterns

How data flows through agent-actions workflow nodes.

## Source Data Format (Critical)

**Source data must be a flat array of records**, not a wrapper object.

### Correct Format

```json
[
  {
    "id": "abc123",
    "page_content": "Content here...",
    "referenced_in": [{"section": "...", "objective": "..."}]
  },
  {
    "id": "def456",
    "page_content": "More content...",
    "referenced_in": [{"section": "...", "objective": "..."}]
  }
]
```

Prompts access fields directly: `{{ source.page_content }}`, `{{ source.referenced_in }}`

### Wrong Format

```json
{
  "exam_name": "My Exam",
  "scraped_links": [
    {"id": "abc123", "page_content": "..."},
    {"id": "def456", "page_content": "..."}
  ]
}
```

This fails because `source` is the wrapper object, not individual records.

**Error you'll see:**
```
PreFlightValidationError: Template references undefined variables
missing_references=['source.page_content']
```

### Fix Options

1. **Restructure input data** - Extract the array and place in staging:
   ```python
   # Transform wrapper to flat array
   data = json.load(open("wrapper.json"))
   records = data["scraped_links"]  # Extract the array
   json.dump(records, open("agent_io/staging/data.json", "w"))  # Place in staging/
   ```

2. **Add preprocessing tool action** - First action extracts items:
   ```yaml
   - name: extract_items
     kind: tool
     impl: extract_scraped_links
     granularity: file
   ```

3. **Change prompt paths** - If wrapper is intentional:
   ```jinja2
   {% for link in source.scraped_links %}
     {{ link.page_content }}
   {% endfor %}
   ```

## Directory Structure

```
project/
├── agent_actions.yml            # Project configuration
├── agent_workflow/
│   └── my_workflow/             # Directory name must match workflow name!
│       ├── agent_config/
│       │   └── my_workflow.yml  # YAML filename must match workflow name!
│       ├── agent_io/
│       │   ├── staging/         # INPUT: Place your files here
│       │   │   └── data.json
│       │   ├── source/          # METADATA: Framework adds tracking fields
│       │   │   └── data.json    # (auto-generated from staging/)
│       │   └── target/          # OUTPUT: Node results
│       │       ├── node_0_action_name/
│       │       │   └── data.json
│       │       └── final_action/
│       │           └── data.json
│       └── seed_data/           # Reference data for grounded retrieval
├── prompt_store/                # Prompt templates
├── schema/                      # Output schemas
└── tools/
    └── my_workflow/             # UDFs organized by workflow
```

**CRITICAL:** Use underscores in names (not hyphens): `incident_triage`, not `incident-triage`

### Data Flow: staging/ → source/ → target/

1. **staging/** - Your raw input files go here
   - Place JSON/CSV files with your data
   - This is the starting point

2. **source/** - Framework processes staging/ and adds metadata
   - Adds `source_guid`, `node_id`, `lineage` fields
   - DO NOT place files here manually

3. **target/** - Each action writes output to its own subdirectory
   - Node directories named: `node_{index}_{action_name}/`

## Metadata Fields

Every record maintains these tracking fields:

| Field | Description | Changes Per Node |
|-------|-------------|------------------|
| `source_guid` | Original content UUID | Never changes |
| `target_id` | This node's output UUID | New each node |
| `node_id` | Node identifier | New each node |
| `lineage` | Array of all visited node_ids | Grows each node |

### source_guid

Constant UUID tracking the original source record.

```json
"source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f"
```

Use for: Tracing records back to source, audit trails.

### node_id

Identifies the processing node. Includes index when flattening:

```
node_0_693094fb-53d1-48d6-bdc9-781a4989d35c      # Single output
node_1_361c54c6-7080-4527-9a00-aaeccfd0e6ba_0   # Flattened, index 0
node_1_361c54c6-7080-4527-9a00-aaeccfd0e6ba_1   # Flattened, index 1
```

### lineage

Complete processing path as array:

```json
"lineage": [
  "node_0_693094fb-53d1-48d6-bdc9-781a4989d35c",
  "node_1_361c54c6-7080-4527-9a00-aaeccfd0e6ba_0",
  "node_2_e546c260-de10-4f20-8950-e09f01ea468f"
]
```

## Data Transformation Patterns

### Record Multiplication (Flattening)

When a node outputs multiple records from one input:

**Before (Node 0):**
```json
{
  "content": {
    "questions": [
      {"question_text": "Q1", "answer_text": "A1"},
      {"question_text": "Q2", "answer_text": "A2"}
    ]
  },
  "source_guid": "abc123"
}
```

**After (Node 1 - Flatten):**
```json
[
  {
    "content": {"question_text": "Q1", "answer_text": "A1"},
    "source_guid": "abc123",
    "node_id": "node_1_xxx_0"
  },
  {
    "content": {"question_text": "Q2", "answer_text": "A2"},
    "source_guid": "abc123",
    "node_id": "node_1_xxx_1"
  }
]
```

### Progressive Enrichment

Each node adds fields, preserving existing ones:

```
Node 0: { questions: [...] }
Node 1: { question_text, answer_text }
Node 2: { + quiz_type, classification_reason }
Node 6: { + target_word_counts, options, answer }
Node 11: { + distractor_1, distractor_2, distractor_3 }
Node 12: { + syllabus_alignment_score }
```

### Field Preservation

UDFs should preserve and enrich, not replace:

```python
@udf_tool()
def my_function(data: dict) -> dict:
    data['new_field'] = compute_something(data)  # Add
    return data  # Return all fields
```

## Workflow Stages

### 1. Extraction Phase

- Input: Raw source content
- Output: Structured data
- Actions: `extract_*`, `parse_*`

### 2. Transformation Phase

- Input: Structured data
- Output: Enriched records
- Actions: `flatten_*`, `classify_*`, `enrich_*`

### 3. Generation Phase

- Input: Enriched records
- Output: Generated content
- Actions: `generate_*`, `write_*`, `create_*`

### 4. Quality Control Phase

- Input: Generated content
- Output: Scored/filtered records
- Actions: `score_*`, `filter_*`, `validate_*`

### 5. Formatting Phase

- Input: Validated content
- Output: Final format
- Actions: `format_*`, `combine_*`, `convert_*`

## Tracing Data Issues

### By source_guid

Find all outputs from same source:

```bash
grep "abc123" agent_io/target/*/data.json
```

### By lineage

Check processing path for debugging:

```python
# If error at node_5, check what node_4 produced
lineage = record['lineage']
previous_node = lineage[-2]  # Get second-to-last
```

### By node output

Compare input vs output at each stage:

```bash
# Input to node_2
cat agent_io/target/node_1_*/data.json | jq '.[0]'

# Output from node_2
cat agent_io/target/node_2_*/data.json | jq '.[0]'
```

## Cross-Workflow Data Flow

When workflows chain:

```yaml
# downstream_workflow.yml
- name: first_action
  dependencies:
    - workflow: upstream_workflow
      action: final_action
```

Data from `upstream_workflow.final_action` becomes input.

## Grounded Retrieval Pattern

Use this pattern when LLM output needs to reference **real data** (products, documents, records) instead of hallucinating.

### Problem: LLM Hallucination

```yaml
# BAD - LLM invents fake IDs/data
- name: generate_recommendations
  prompt: "Recommend 5 similar items..."
  # LLM returns: {"id": "FAKE-123", "name": "Made Up Item"}
```

### Solution: 3-Step Grounded Retrieval

```yaml
# STEP 1: LLM generates SEARCH CRITERIA (not final data)
- name: generate_search_criteria
  schema: search_criteria
  prompt: $workflow.Generate_Search_Criteria
  # Output: {query_text, categories, keywords, exclude_id}

# STEP 2: TOOL retrieves REAL candidates from data source
- name: retrieve_candidates
  kind: tool
  impl: search_catalog
  # Output: {results: [...real items from DB...], metadata: {...}}

# STEP 3: LLM RANKS from retrieved candidates only
- name: rank_results
  dependencies: [retrieve_candidates]
  schema: ranked_results
  prompt: $workflow.Rank_Results
  context_scope:
    observe:
      - retrieve_candidates.results  # LLM can ONLY see real items
  # Output: Ranked subset with explanations
```

### Key Components

**1. Search Criteria Schema:**
```yaml
name: search_criteria
fields:
  - id: query_text
    type: string
    description: "Natural language search query"
  - id: categories
    type: array
    items: {type: string}
  - id: keywords
    type: array
    items: {type: string}
  - id: exclude_id
    type: string
    description: "Current item's ID to exclude from results"
```

**2. Retrieval Tool:**
```python
class SearchCatalogOutput(TypedDict, total=False):
    results: list[ResultItem]  # Use nested TypedDict, NOT dict[str, Any]
    metadata: SearchMetadata

@udf_tool()
def search_catalog(data: dict) -> dict:
    # Load from seed_data, vector DB, or SQL
    catalog = load_catalog()
    matches = score_and_filter(catalog, data)
    return {"results": matches, "metadata": {...}}
```

**3. Ranking Prompt:**
```markdown
{prompt Rank_Results}
Select the TOP 5 most relevant items from these candidates.

## AVAILABLE CANDIDATES (you MUST choose from these only)
{% for item in retrieve_candidates.results %}
- ID: {{ item.id }}
  Name: "{{ item.name }}"
  Category: {{ item.category }}
{% endfor %}

⚠️ DO NOT invent items. Only use IDs from the list above.
{end_prompt}
```

### Seed Data for Catalog

```yaml
defaults:
  context_scope:
    seed_path:
      catalog: $file:catalog.json
```

Place catalog in: `agent_workflow/my_workflow/seed_data/catalog.json`

### Benefits

- ✅ **Zero hallucination** - All IDs/names are real
- ✅ **Auditable** - Can trace which candidates were retrieved
- ✅ **Swappable backend** - JSON file → Vector DB → SQL without workflow changes
- ✅ **Testable** - Fixed catalog = deterministic outputs

## Context Passthrough for Merging Branches

When parallel branches merge, use `context_scope.passthrough` to preserve upstream data.

### Problem: Lost Data at Merge Point

```yaml
# Parallel branches
- name: enrich_metadata
  dependencies: [validate_input]

- name: generate_summary
  dependencies: [validate_input]

# Merge point - only gets its own schema output!
- name: score_quality
  dependencies: [enrich_metadata, generate_summary]
  schema: score_quality
  # ERROR: downstream tool receives empty data
```

### Solution: Explicit Passthrough

```yaml
- name: score_quality
  dependencies: [enrich_metadata, generate_summary, classify_content]
  schema: score_quality
  prompt: $workflow.Score_Quality
  context_scope:
    passthrough:
      # Source metadata
      - source.id
      - source.name
      - source.category
      # From upstream actions
      - validate_input.validated_fields
      - enrich_metadata.enriched_data
      - generate_summary.summary_text
      - classify_content.classification
```

### When to Use Passthrough

| Scenario | Use Passthrough |
|----------|----------------|
| LLM action followed by tool that needs full context | ✅ Yes |
| Parallel branches merging before final formatting | ✅ Yes |
| Sequential LLM actions where each adds fields | Usually automatic |
| Tool actions (UDFs return full data) | Usually not needed |

## Best Practices

1. **Preserve source_guid** - Never modify, enables tracing
2. **Add, don't replace** - Enrich records with new fields
3. **Use meaningful field names** - `quality_score` not `score1`
4. **Document field sources** - Comment which node adds which field
5. **Check lineage for debugging** - Full processing path available
6. **Use guards early** - Filter bad data before expensive processing
7. **Use grounded retrieval** - When LLM output must reference real data
8. **Use passthrough at merge points** - Prevent data loss when branches converge
