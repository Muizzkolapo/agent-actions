# Aggregation Patterns

How to merge outputs from parallel branches using `reduce_key` and fan-in dependencies.

## When You Need Aggregation

| Scenario | Pattern |
|----------|---------|
| Multiple validators produce results for the same item | `reduce_key` |
| Parallel branches that share a common record ID | `reduce_key` |
| Collecting all version outputs into one record | `version_consumption` (not reduce_key) |
| Sequential pipeline, one action after another | Plain `dependencies` (no aggregation needed) |

## reduce_key Configuration

```yaml
- name: aggregate_reviews
  dependencies: [validate_text, validate_image, validate_audio]
  reduce_key: content_id              # Groups records by this field
  context_scope:
    observe:
      - validate_text.*
      - validate_image.*
      - validate_audio.*
```

`reduce_key` tells the framework: "Before running this action, merge all input records that share the same `content_id` value into a single record."

## How Merging Works

### Key resolution priority

The framework picks the grouping key in this order:
1. Explicit `reduce_key` (if provided)
2. `parent_target_id` (fallback)
3. `source_guid` (final fallback)

### Merge algorithm

Records with the same key are deep-merged:

| Field | Merge behavior |
|-------|----------------|
| `content` (dict) | Deep merged — keys from all records combined |
| `lineage` (list) | Deduplicated merge — entries added if node_id not already present |
| Other metadata | First-wins — existing value retained |

### Example

Three parallel validators produce:

From `validate_text`:
```json
{"content": {"validate_text": {"text_score": 8}}, "source_guid": "abc"}
```

From `validate_image`:
```json
{"content": {"validate_image": {"image_score": 7}}, "source_guid": "abc"}
```

From `validate_audio`:
```json
{"content": {"validate_audio": {"audio_score": 9}}, "source_guid": "abc"}
```

After merge with `reduce_key: content_id` (or even without it, since they share `source_guid`):

```json
{
  "content": {
    "validate_text": {"text_score": 8},
    "validate_image": {"image_score": 7},
    "validate_audio": {"audio_score": 9}
  },
  "source_guid": "abc"
}
```

The aggregating action receives one merged record per unique key value, with all branch outputs namespaced in `content`.

## reduce_key vs Fan-In (No reduce_key)

| | Fan-In (default) | Aggregation (reduce_key) |
|---|---|---|
| **Dependencies** | First dep is primary, others matched by lineage | All deps are input sources |
| **Execution count** | Driven by primary dependency's record count | Driven by unique key values |
| **Record matching** | Lineage-based (deterministic node_id match) | Key-based (group by field value) |
| **Use when** | Different views of the same record (same source_guid) | Independent records that share a business key |

### Fan-in (no reduce_key)

```yaml
# Primary dependency drives execution count
- name: score_quality
  dependencies: [generate_seo, generate_recommendations, assess_reading_level]
  # generate_seo is primary (first in list)
  # Others matched via lineage
```

### Aggregation (with reduce_key)

```yaml
# All dependencies contribute equally, grouped by key
- name: aggregate_reviews
  dependencies: [validator_a, validator_b, validator_c]
  reduce_key: content_id
```

## UDF for Aggregated Data

The merge tool receives fields namespaced by action name:

```python
@udf_tool()
def aggregate_reviews(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Each upstream action's fields are under its namespace
    text_score = data["validate_text"]["text_score"]
    image_score = data["validate_image"]["image_score"]
    audio_score = data["validate_audio"]["audio_score"]

    scores = [text_score, image_score, audio_score]
    avg = sum(scores) / len(scores) if scores else 0

    return [{
        "average_score": avg,
        "all_scores": {
            "text": text_score,
            "image": image_score,
            "audio": audio_score,
        },
        "verdict": "pass" if avg >= 7 else "fail",
    }]
```

## Aggregation with LLM (No UDF)

You can aggregate with an LLM action instead of a tool. The merged data is available in the prompt via Jinja:

```yaml
- name: summarize_reviews
  dependencies: [validate_text, validate_image, validate_audio]
  reduce_key: content_id
  prompt: |
    Summarize these validation results:

    Text review: score={{ validate_text.text_score }}
    Image review: score={{ validate_image.image_score }}
    Audio review: score={{ validate_audio.audio_score }}

    Provide an overall assessment.
  schema:
    overall_assessment: string
    recommended_action: string
  context_scope:
    observe:
      - validate_text.*
      - validate_image.*
      - validate_audio.*
```

## Multiple Files (Parallel Branches)

When parallel branches write to separate files, `reduce_key` merges across files before passing to the action. The framework:

1. Loads records from all dependency output files
2. Groups by `reduce_key` (or `parent_target_id` / `source_guid`)
3. Deep-merges records with the same key
4. Passes merged records to the action

This happens transparently — you don't need to handle multi-file logic.

## Overriding Primary Dependency

In fan-in without `reduce_key`, the first dependency in the list drives execution count. Override with `primary_dependency`:

```yaml
- name: generate_report
  dependencies: [analyze_sentiment, analyze_entities, analyze_topics]
  primary_dependency: analyze_entities     # This one drives execution count
  context_scope:
    observe:
      - analyze_sentiment.*
      - analyze_entities.*
      - analyze_topics.*
```

Use this when the default primary (first in list) has fewer records than you want to iterate over.

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| No `reduce_key` when branches produce independent records | Records not merged, action sees partial data | Add `reduce_key` with the shared field |
| `reduce_key` field doesn't exist in records | Records pass through unmerged | Verify upstream actions produce the field |
| Using `reduce_key` for version consumption | Wrong merge behavior | Use `version_consumption: {source: action, pattern: merge}` instead |
| Missing `observe` for all branches | Merged content missing some namespaces | Add `observe: [branch_name.*]` for every dependency |
