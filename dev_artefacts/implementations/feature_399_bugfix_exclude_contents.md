# Feature 399 - Bug Fix: Exclude Directive Not Filtering Contents

## Issue Discovered
**Date:** 2025-10-29
**Reporter:** User testing with QanaLabs workflow

### Problem
The `context_scope.exclude` directive was **NOT** removing excluded fields from the `contents` dict sent to the LLM. While excluded fields were correctly removed from `prompt_context` (preventing them from being used in prompt rendering), they were still appearing in the `[Context Data Preview]` sent to the agent.

### Example
Given this config:
```yaml
context_scope:
  exclude:
    - group_by_similarity.grouped_facts
    - group_by_similarity.num_similar_facts
    - group_by_similarity.page_content
```

**Expected:** These fields should be blocked from the LLM entirely
**Actual:** Fields appeared in the context data sent to the LLM

### Debug Output Showing Bug
```
[Context Data Preview]
--------------------------------------------------
{
  "grouped_facts": [...],     // ❌ Should be excluded!
  "num_similar_facts": 5,      // ❌ Should be excluded!
  "page_content": "...",       // ❌ Should be excluded!
  ...
}
```

---

## Root Cause

In `data_generator.py:230`, the `_format_prompt()` method returned the **original `contents` dict unchanged**:

```python
# BEFORE (buggy):
return (formatted_prompt, contents, llm_context, passthrough_fields)
```

The `apply_context_scope()` method correctly removed fields from `prompt_context`, but the `contents` dict (which becomes the context data sent to the agent) was never filtered.

**Why this matters:**
- `prompt_context`: Used for `{action.field}` rendering in prompts
- `contents`: Sent to the LLM as context data (shown in debug as `[Context Data Preview]`)

The bug meant excluded fields were removed from prompts but **still visible to the LLM** in the context data, defeating the security purpose of the `exclude` directive.

---

## Fix Applied

**File Modified:** `agent_actions/prompt_generation/data_generator.py` (lines 231-258)

### Implementation

Added filtering logic to remove all context_scope fields (exclude, include, passthrough) from the `contents` dict before returning it:

```python
# Apply exclusions to contents dict (remove excluded fields from context data)
if context_scope and isinstance(contents, dict):
    from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
    # Get all field references that should be removed from contents
    fields_to_remove = set()
    for field_ref in context_scope.get('exclude', []):
        try:
            _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
            fields_to_remove.add(field_name)
        except ValueError:
            continue
    for field_ref in context_scope.get('include', []):
        try:
            _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
            fields_to_remove.add(field_name)
        except ValueError:
            continue
    for field_ref in context_scope.get('passthrough', []):
        try:
            _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
            fields_to_remove.add(field_name)
        except ValueError:
            continue

    # Create filtered contents without excluded fields
    if fields_to_remove:
        contents = {k: v for k, v in contents.items() if k not in fields_to_remove}

return (formatted_prompt, contents, llm_context, passthrough_fields)
```

### Why All Three Directives?

All three directives (exclude, include, passthrough) should remove fields from `contents`:

1. **exclude**: Security - LLM should never see these fields
2. **include**: Efficiency - Fields moved to `llm_context` (additional context), not needed in main context
3. **passthrough**: Efficiency - Fields go directly to output, LLM doesn't need them

---

## Test Updates

**File Modified:** `tests/integration/test_context_scope_e2e.py` (lines 87-101)

### Enhanced Exclude Test

Added assertions to verify excluded fields are removed from `filtered_contents`:

```python
# Execute _format_prompt
formatted_prompt, filtered_contents, llm_context, passthrough_fields = generator._format_prompt(
    contents, source_content=source_content
)

# Validate: api_key and credentials NOT in filtered_contents (sent to LLM)
assert 'api_key' not in filtered_contents, "Excluded field 'api_key' should be removed from contents"
assert 'credentials' not in filtered_contents, "Excluded field 'credentials' should be removed from contents"
```

---

## Test Results

All tests pass after fix:

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

## Impact

### Before Fix
- ❌ **Security risk**: Excluded sensitive fields (API keys, credentials, PII) still sent to LLM
- ❌ **Inefficiency**: Include/passthrough fields unnecessarily duplicated in context
- ❌ **Violated design intent**: Exclude meant to block fields from LLM entirely

### After Fix
- ✅ **Security**: Excluded fields truly blocked from LLM
- ✅ **Efficiency**: No duplicate data in context
- ✅ **Design intent**: All three directives work as documented

---

## Backward Compatibility

✅ **No breaking changes** - Workflows without `context_scope` work unchanged

---

## Files Changed

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `agent_actions/prompt_generation/data_generator.py` | +28 lines (231-258) | Filter contents dict |
| `tests/integration/test_context_scope_e2e.py` | +2 lines (100-101) | Enhanced test assertions |

**Total:** 30 lines added

---

## Summary

This bug fix ensures the `context_scope` feature works as designed:
- **exclude**: Blocks sensitive data from LLM entirely (security)
- **include**: Sends large reference data as additional context only
- **passthrough**: Merges lineage fields to output only

The fix was discovered through user testing with the QanaLabs quiz generation workflow and demonstrates the importance of end-to-end testing with real configs.

**Status:** ✅ Fixed and tested
**Date:** 2025-10-29
