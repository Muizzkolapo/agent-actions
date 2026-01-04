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

1. **Restructure input data** - Extract the array as the source file:
   ```python
   # Transform wrapper to flat array
   data = json.load(open("wrapper.json"))
   records = data["scraped_links"]  # Extract the array
   json.dump(records, open("source/data.json", "w"))
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
agent_workflow/
└── my_workflow/
    ├── agent_config/
    │   └── my_workflow.yml
    └── agent_io/
        ├── source/              # Input data
        │   └── data.json
        ├── staging/             # Processed source
        │   └── data.json
        └── target/              # Node outputs
            ├── node_0_action_name/
            │   └── data.json
            ├── node_1_action_name/
            │   └── data.json
            └── final_workflow_output/
                └── data.json
```

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
@udf_tool(input_type=MyInput)
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

## Best Practices

1. **Preserve source_guid** - Never modify, enables tracing
2. **Add, don't replace** - Enrich records with new fields
3. **Use meaningful field names** - `syllabus_alignment_score` not `score1`
4. **Document field sources** - Comment which node adds which field
5. **Check lineage for debugging** - Full processing path available
6. **Use guards early** - Filter bad data before expensive processing
