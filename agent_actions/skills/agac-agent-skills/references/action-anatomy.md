# Action Anatomy

## LLM Action

```yaml
- name: generate_explanation
  dependencies: [validate_data]
  intent: "Generate educational content"
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  json_mode: true
  schema:                                 # Only LLM-computed fields
    explanation: string
    key_points: array
  context_scope:
    observe:
      - validate_data.*
      - source.page_content
  guard:
    condition: 'validation_status == "PASS"'
    on_false: "filter"
  prompt: $workflow.Generate_Explanation
```

## Tool Action (UDF)

```yaml
- name: process_data
  dependencies: [extract_content]
  kind: tool
  impl: process_data_function            # Must match @udf_tool function name exactly
  intent: "Transform and enrich data"
  granularity: Record                    # Record (default) | File
  context_scope:
    observe:
      - extract_content.*
      - source.metadata
  guard:
    condition: 'status == "valid"'
    on_false: "filter"
```

UDFs have no `schema` -- output defined by return value.

## Key Fields

### dependencies
Controls execution order. All dependencies must also appear in `context_scope.observe`.

```yaml
dependencies: [parent_action]                    # Single
dependencies: [action_a, action_b, action_c]     # Merge pattern
dependencies:                                     # Cross-workflow
  - workflow: other_workflow
    action: final_action
```

### context_scope.observe
Controls data access. Can reach ANY ancestor via lineage, not just direct parents.

```yaml
context_scope:
  observe:
    - parent_action.*              # All fields from parent
    - grandparent.specific_field   # Via lineage
    - source.page_content          # Original input
```

### schema (LLM only)
Only LLM-computed fields. Forwarded fields accessed via lineage -- do NOT add them to schema.

### guard
Checks **input** (upstream output), not this action's output. Place guard on the NEXT action to filter based on an action's output.

- `on_false: "filter"` -- remove record
- `on_false: "skip"` -- skip action, pass data through

### prompt (LLM only)
Format: `$workflow_name.Prompt_Name`

## Data Lineage

```
Input:  target_id=T_in,  parent_target_id=P_in,  root_target_id=R_in
Output: target_id=NEW,   parent_target_id=T_in,   root_target_id=R_in
```

- `target_id` = new UUID per output
- `parent_target_id` = input's `target_id`
- `root_target_id` = preserved from original ancestor

## Record Matching

Two modes, no fallback. If node_id not found, returns `None` + warning.

| Mode | Use case |
|------|----------|
| Ancestor | Exact node_id match in lineage chain (sequential pipelines) |
| Merge-parent | Match via `lineage_sources` (fan-in / aggregate patterns) |

## Common Patterns

### Validation
```yaml
- name: validate_data
  schema:
    validation_status: string
- name: use_validated
  dependencies: [validate_data]
  guard:
    condition: 'validation_status == "PASS"'
```

### Merge
```yaml
- name: merge_results
  dependencies: [action_a, action_b, action_c]
  context_scope:
    observe: [action_a.*, action_b.*, action_c.*]
```

### Version Merge
```yaml
- name: aggregate
  dependencies: [versioned_action]
  version_consumption:
    source: versioned_action
    pattern: merge
  context_scope:
    observe: [versioned_action.*]   # Captures ALL versions
```
