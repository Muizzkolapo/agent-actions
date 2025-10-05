# Implement Unified Field Referencing Pattern `{reference.field}`

## Problem

Currently, field access in agent prompts uses **inconsistent and unclear patterns**:

1. **`source_context{{['field']}}`** - Awkward syntax for accessing original workflow input
   ```yaml
   prompt: "Process source_context{{['page_content']}}"
   ```

2. **`return_collection[field]`** - Ambiguous source, unclear which agent's output
   ```yaml
   prompt: "Analyze return_collection[metrics]"  # From which agent?
   ```

3. **No explicit dependency field access** - Can't reference specific fields from dependency outputs
   ```yaml
   depends_on: [extractor]
   prompt: "How do I access extractor.metrics?"  # Not possible
   ```

**Issues:**
- ❌ Inconsistent syntax across different reference types
- ❌ `return_collection` doesn't show data source
- ❌ `source_context{{}}` is verbose and unintuitive
- ❌ No way to explicitly reference dependency fields
- ❌ Difficult for users to understand where data comes from
- ❌ Makes validation impossible (related to #412)

## Proposed Solution

**Implement a unified `{reference.field}` pattern** for all field access in prompts:

```yaml
agents:
  - name: extractor
    prompt: "Extract data from {source.page_content}"
    output_schema:
      metrics: { type: object }
      summary: { type: string }
      internal_id: { type: string }
    drops: [internal_id]

  - name: analyzer
    depends_on: [extractor]
    prompt: |
      Original source: {source.page_content}

      Analyze these metrics: {extractor.metrics}
      Using summary: {extractor.summary}

      Custom processing: dispatch_task(process_data)
```

### The Pattern

| Pattern | Purpose | Example | Replaces |
|---------|---------|---------|----------|
| `{source.field}` | Access original workflow input | `{source.page_content}` | `source_context{{['page_content']}}` |
| `{agent.field}` | Access dependency agent output | `{extractor.metrics}` | `return_collection[metrics]` |
| `dispatch_task()` | Call user functions | `dispatch_task(process)` | _(keep as is)_ |

### Benefits

✅ **Consistent:** All field references use same `{reference.field}` syntax
✅ **Explicit:** Immediately see where data comes from
✅ **Clear:** Simple dot notation everyone understands
✅ **Validated:** Enables field validation (see #412)
✅ **Intuitive:** Follows standard programming conventions
✅ **Migration-friendly:** Clear upgrade path from old patterns

## Implementation Details

### 1. Pattern Recognition

Add to `PromptUtils.replace_placeholders()`:

```python
# Pattern: {reference.field} or {reference.nested.field}
pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\}'

# Examples matched:
# {source.page_content}
# {extractor.metrics}
# {extractor.data.count}  (nested fields)
```

### 2. Reference Resolution

```python
def resolve_field_reference(reference: str, context: dict) -> Any:
    """
    Resolve {reference.field} to actual value.

    Args:
        reference: String like "extractor.metrics" or "source.page_content"
        context: Dict with:
            - 'source': Original workflow input
            - 'extractor': Extractor agent output
            - 'analyzer': Analyzer agent output
            - etc.

    Returns:
        Resolved field value
    """
    parts = reference.split('.')
    reference_name = parts[0]  # 'extractor' or 'source'
    field_path = parts[1:]      # ['metrics'] or ['data', 'count']

    # Get reference data
    if reference_name not in context:
        raise ValueError(f"Reference '{reference_name}' not found. Available: {list(context.keys())}")

    data = context[reference_name]

    # Navigate field path
    for field in field_path:
        if isinstance(data, dict) and field in data:
            data = data[field]
        else:
            raise ValueError(f"Field '{'.'.join(field_path)}' not found in '{reference_name}'")

    return data
```

### 3. Context Building

At agent execution time, build context with all available references:

```python
context = {
    'source': workflow_input,  # Original input
    **{agent: output for agent, output in dependency_outputs.items()}
}

# Example context:
# {
#   'source': {'page_content': '...', 'metadata': {...}},
#   'extractor': {'metrics': {...}, 'summary': '...'},
#   'preprocessor': {'cleaned_text': '...'}
# }
```

### 4. Migration Strategy

**Phase 1: Add new pattern (backward compatible)**
- Implement `{reference.field}` pattern
- Keep `source_context{{}}` and `return_collection[]` working
- Log deprecation warnings

**Phase 2: Deprecate old patterns**
- Add migration guide
- Show warnings in CLI when old patterns detected
- Provide auto-migration tool

**Phase 3: Remove old patterns**
- Remove `source_context{{}}` support
- Remove `return_collection[]` support
- Clean up code

### 5. Special References

| Reference | Description | Example |
|-----------|-------------|---------|
| `{source.field}` | Original workflow input | `{source.page_content}` |
| `{workflow.field}` | Workflow-level metadata | `{workflow.name}` |
| `{loop.index}` | Current loop iteration (if in loop) | `{loop.index}` |
| `{loop.item}` | Current loop item | `{loop.item.id}` |

## Examples

### Example 1: Basic Dependency Access

**Before:**
```yaml
- name: analyzer
  depends_on: [extractor]
  prompt: "Analyze return_collection[metrics]"  # Unclear source
```

**After:**
```yaml
- name: analyzer
  depends_on: [extractor]
  prompt: "Analyze {extractor.metrics}"  # Clear source
```

### Example 2: Source Access

**Before:**
```yaml
- name: processor
  prompt: |
    Process this content:
    source_context{{['page_content']}}
```

**After:**
```yaml
- name: processor
  prompt: |
    Process this content:
    {source.page_content}
```

### Example 3: Multiple Dependencies

**Before:**
```yaml
- name: combiner
  depends_on: [extractor, classifier]
  prompt: "Combine return_collection[data] with return_collection[labels]"  # Very unclear!
```

**After:**
```yaml
- name: combiner
  depends_on: [extractor, classifier]
  prompt: "Combine {extractor.data} with {classifier.labels}"  # Crystal clear!
```

### Example 4: Nested Fields

```yaml
- name: reporter
  depends_on: [analyzer]
  prompt: |
    Total count: {analyzer.results.count}
    Accuracy: {analyzer.results.metrics.accuracy}
    Top error: {analyzer.results.errors.0.message}
```

### Example 5: Loop Context

```yaml
- name: process_items
  loop:
    over: {source.items}
  prompt: |
    Processing item #{loop.index}
    Item ID: {loop.item.id}
    Item data: {loop.item.content}
```

## Implementation Phases

### Phase 1: Core Pattern Implementation (Critical)
- [ ] Implement `{reference.field}` regex pattern matching
- [ ] Build reference resolution logic
- [ ] Add context building with source + dependencies
- [ ] Handle nested field access (dot notation)
- [ ] Add error handling for missing references/fields

### Phase 2: Special References (Medium)
- [ ] Add `{source.field}` for workflow input
- [ ] Add `{loop.index}` and `{loop.item}` for loops
- [ ] Add `{workflow.field}` for workflow metadata

### Phase 3: Migration Support (High)
- [ ] Keep `source_context{{}}` working temporarily
- [ ] Keep `return_collection[]` working temporarily
- [ ] Add deprecation warnings
- [ ] Create migration documentation
- [ ] Build auto-migration tool

### Phase 4: Testing (Critical)
- [ ] Unit tests for pattern matching
- [ ] Unit tests for reference resolution
- [ ] Integration tests with real workflows
- [ ] Test nested field access
- [ ] Test missing reference/field errors
- [ ] Test backward compatibility

### Phase 5: Documentation (High)
- [ ] Update prompt documentation
- [ ] Add migration guide
- [ ] Create examples for all patterns
- [ ] Document special references
- [ ] Add troubleshooting section

## Breaking Changes

**This is a breaking change** but necessary for clarity and validation.

**Migration Path:**
1. Automatic migration tool: `agent-actions migrate-prompts`
2. Deprecation warnings in v2.x
3. Removal of old patterns in v3.0

**Migration Tool Output:**
```bash
$ agent-actions migrate-prompts

✅ Migrated: source_context{{['page_content']}} → {source.page_content}
✅ Migrated: return_collection[metrics] → {extractor.metrics}
⚠️  Manual review needed: return_collection[data] (ambiguous - multiple dependencies)

3 patterns migrated, 1 requires manual review
```

## Related Issues

- **Blocks:** #412 - Input signature validation requires explicit field referencing
- **Improves:** Prompt clarity and debuggability across all workflows
- **Enables:** Future type validation and IDE autocomplete

## Success Criteria

- ✅ `{reference.field}` pattern implemented and working
- ✅ `{source.field}` accesses original workflow input
- ✅ `{agent.field}` accesses dependency outputs
- ✅ Nested field access works: `{agent.data.field.subfield}`
- ✅ Clear error messages for missing references/fields
- ✅ Backward compatibility maintained (with deprecation warnings)
- ✅ Migration tool available
- ✅ Documentation complete
- ✅ All tests passing
- ✅ Enables #412 field validation

## Estimated Effort

- **Core implementation:** 8-12 hours
- **Testing:** 4-6 hours
- **Migration support:** 4-6 hours
- **Documentation:** 3-4 hours
- **Total:** ~20-28 hours (2.5-3.5 days)

## Priority

**High** - Blocks #412 and is critical for prompt clarity and validation
