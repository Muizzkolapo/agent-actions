# Feature 399 - Bug Fix (Proper): Exclude Directive Using Drops Pathway

## Issue Discovered
**Date:** 2025-10-29
**Reporter:** User testing with QanaLabs workflow

### Problem
The `context_scope.exclude` directive was **NOT** removing excluded fields from the context sent to the LLM. While excluded fields were correctly removed from `prompt_context` (for prompt rendering), they were still appearing in the `[Context Data Preview]` sent to the agent.

### Root Cause - First Attempt (Wrong Path)
Initially tried to fix this in `data_generator._format_prompt()` by filtering the `contents` dict. However, this was the **wrong approach** because:
- The `drops` directive doesn't filter in `_format_prompt()`
- Filtering happens later in the pipeline, in `run_dynamic_agent()`

### Root Cause - Correct Understanding
After tracing how `drops` works, discovered the correct pathway:

**Flow:**
1. `data_generator._format_prompt()` returns `(formatted_prompt, contents, llm_context, passthrough_fields)`
2. `data_generator.create_agent_with_data()` calls `run_dynamic_agent(..., contents, ...)`
3. **`run_dynamic_agent()` applies `drops` via `apply_drops()`** before passing context to agent
4. `agent_builder.create_dynamic_agent()` receives the filtered context

**Key Insight:** The `exclude` directive should follow the same pathway as `drops` - filter in `run_dynamic_agent()` using `DataTransformer.remove_schema_objects()`.

---

## Correct Fix Applied

**File Modified:** `agent_actions/utilities/utils_processor_helpers.py` (lines 61-78)

### Implementation

Added context_scope exclusion logic **right after** `apply_drops()`, using the same mechanism:

```python
# Apply drops (existing)
if isinstance(context, dict) and 'content' in context and isinstance(context['content'], dict):
    content_dict = context['content']
    processed_context = apply_drops(content_dict, agent_config)
else:
    processed_context = apply_drops(context, agent_config)

# Apply context_scope exclusions (NEW - same pathway as drops)
context_scope = agent_config.get('context_scope', {})
if context_scope and isinstance(processed_context, dict):
    from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
    from agent_actions.preprocessing.data_transformer import DataTransformer

    # Get all field names that should be excluded from context
    fields_to_exclude = []
    for field_ref in context_scope.get('exclude', []):
        try:
            _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
            fields_to_exclude.append(field_name)
        except ValueError:
            continue

    # Remove excluded fields from context (same as drops)
    if fields_to_exclude:
        processed_context = DataTransformer.remove_schema_objects(processed_context, fields_to_exclude)

response = agent_builder.create_dynamic_agent(..., processed_context, ...)
```

### Why This Works

1. **Same pathway as drops**: Filters context in `run_dynamic_agent()` before agent execution
2. **Uses same utility**: `DataTransformer.remove_schema_objects()` (same as drops)
3. **Consistent behavior**: Exclude works just like drops - removes fields from context sent to LLM
4. **Correct timing**: Filters after all guards/conditions but before agent execution

---

## Files Reverted

**File:** `agent_actions/prompt_generation/data_generator.py`

Reverted the changes made in the first attempt (lines 231-258 removed). The filtering logic does NOT belong in `_format_prompt()`.

**File:** `tests/integration/test_context_scope_e2e.py`

Reverted test changes that checked `filtered_contents` (lines 100-101 removed). The tests work correctly with the original implementation.

---

## Test Results

All tests pass with the correct fix:

```bash
# Integration tests
tests/integration/test_context_scope_e2e.py::TestContextScopeEndToEnd::test_include_directive_e2e PASSED
tests/integration/test_context_scope_e2e.py::TestContextScopeEndToEnd::test_exclude_directive_e2e PASSED
tests/integration/test_context_scope_e2e.py::TestContextScopeEndToEnd::test_passthrough_directive_e2e PASSED
tests/integration/test_context_scope_e2e.py::TestContextScopeEndToEnd::test_combined_directives_e2e PASSED
tests/integration/test_context_scope_e2e.py::TestContextScopeEndToEnd::test_backward_compatibility PASSED

# Unit tests
tests/utilities/test_context_scope_processor.py::TestContextScopeProcessor::test_apply_context_scope_all_directives PASSED
tests/utilities/test_context_scope_processor.py::TestContextScopeProcessor::test_format_llm_context PASSED
tests/utilities/test_context_scope_processor.py::TestContextScopeProcessor::test_merge_passthrough_fields PASSED

Total: 8/8 tests PASSED ✅
```

---

## Comparison: Wrong vs. Right Approach

### Wrong Approach (First Attempt)
```python
# In data_generator._format_prompt()
if context_scope and isinstance(contents, dict):
    fields_to_remove = set(...)
    contents = {k: v for k, v in contents.items() if k not in fields_to_remove}
return (formatted_prompt, contents, llm_context, passthrough_fields)
```

**Problems:**
- Filtering too early in the pipeline
- Inconsistent with how `drops` works
- `contents` gets passed through multiple layers before reaching agent

### Right Approach (Current Fix)
```python
# In run_dynamic_agent() - same place as apply_drops()
processed_context = apply_drops(context, agent_config)

# NEW: Apply context_scope exclusions using same mechanism
context_scope = agent_config.get('context_scope', {})
if context_scope:
    fields_to_exclude = [...]
    processed_context = DataTransformer.remove_schema_objects(processed_context, fields_to_exclude)

response = agent_builder.create_dynamic_agent(..., processed_context, ...)
```

**Benefits:**
- Filtering at the right place in the pipeline
- Consistent with `drops` implementation
- Uses same utility function (`DataTransformer.remove_schema_objects`)
- Direct filtering right before agent execution

---

## Impact

### Before Fix
- ❌ **Security risk**: Excluded sensitive fields still sent to LLM
- ❌ **Wrong pathway**: Filtering in wrong place
- ❌ **Inconsistent**: Different from how drops works

### After Fix
- ✅ **Security**: Excluded fields blocked from LLM
- ✅ **Correct pathway**: Same as drops
- ✅ **Consistent**: Uses same mechanism as drops

---

## Key Learning

**Always trace how existing features work before implementing similar features.**

The user's suggestion to "trace how drop currently work" was exactly right. By tracing `drops`, we discovered:
1. Where filtering happens (`run_dynamic_agent`, not `_format_prompt`)
2. What function to use (`DataTransformer.remove_schema_objects`)
3. How to structure the code (same pattern as drops)

This saved us from a wrong implementation that would have had subtle bugs.

---

## Files Changed (Final)

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `agent_actions/utilities/utils_processor_helpers.py` | +18 lines (61-78) | Apply exclude filtering (same pathway as drops) |

**Total:** 18 lines added

---

## Summary

The `context_scope.exclude` directive now works correctly by following the same pathway as `drops`:
1. Filtering happens in `run_dynamic_agent()` right after `apply_drops()`
2. Uses `DataTransformer.remove_schema_objects()` (same utility as drops)
3. Filters context before passing to `agent_builder.create_dynamic_agent()`

This ensures excluded fields are truly blocked from the LLM, matching the security guarantees of the `drops` directive.

**Status:** ✅ Fixed using correct pathway
**Date:** 2025-10-29
**Credit:** User's suggestion to trace drops implementation
