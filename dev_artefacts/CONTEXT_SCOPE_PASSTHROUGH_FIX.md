# Context Scope Passthrough Fix - Complete Solution

## Root Cause

The `context_scope.passthrough` feature was not working due to **TWO RELATED ISSUES**:

### Issue 1: `model_dump(exclude_unset=True)` Excluding context_scope
The `context_scope` field was being stripped from agent configurations during validation because `model_dump(exclude_unset=True)` treats fields with default values as "unset" and excludes them from the dumped dictionary, even if they were explicitly set in the YAML.

### Issue 2: Default Empty Lists for observe/drops
When we changed to `model_dump()` without `exclude_unset`, Pydantic started including default empty lists `[]` for `observe` and `drops` fields (which have `default_factory=list`). The validator then rejected file-level tools with these fields present.

### Solution
Use `model_dump(exclude_defaults=True)` instead:
- Includes fields explicitly set in YAML (like `context_scope: {...}`)
- Excludes fields with default values (like empty `observe: []`, `drops: []`)
- Best of both worlds!

## Files Fixed

### 1. `/agent_actions/prompt_generation/config_renderer.py`

**Line 253** - Fixed in `_validate_agent_config_block()` for new format configs:
```python
# BEFORE (wrong)
validated_entries.append(entry_model.model_dump(exclude_unset=True))

# AFTER (fixed)
validated_entries.append(entry_model.model_dump(exclude_defaults=True))
```

**Line 265** - Fixed in `_validate_agent_config_block()` for old format configs:
```python
# BEFORE (wrong)
validated_entries.append(entry_model.model_dump(exclude_unset=True))

# AFTER (fixed)
validated_entries.append(entry_model.model_dump(exclude_defaults=True))
```

### 2. `/agent_actions/llm_invocation/realtime/config_handler.py`

**Line 135** - Fixed in `merge_agent_configs()`:
```python
# BEFORE (wrong)
agent_dict = agent_model.model_dump(exclude_unset=True)

# AFTER (fixed)
agent_dict = agent_model.model_dump(exclude_defaults=True)
```

## Implementation Location

The `context_scope.passthrough` implementation is in:

**`/agent_actions/preprocessing/data_processor.py`**

- Method: `_apply_context_scope_passthrough()` (lines 60-175)
- Called from: `process_item()` (line 54)
- Pattern: Follows the exact same approach as legacy `observe` feature

### Why This Location?

1. **POST-LLM execution** - After LLM has generated output, before writing to file
2. **Direct dict access** - Reads from `agent_config.get('context_scope')` avoiding Pydantic issues
3. **Proven pattern** - Mirrors how `observe` works (see `OBSERVE_IMPLEMENTATION_ANALYSIS.md`)
4. **Full context** - Has access to both original input (`contents`) and LLM output (`generated_data`)

## How It Works

```python
def _apply_context_scope_passthrough(self, generated_data: List, contents: Dict) -> List:
    # 1. Read context_scope directly from dict (like observe)
    context_scope = self.agent_config.get('context_scope')

    # 2. Extract passthrough config
    passthrough_config = context_scope.get('passthrough', {})
    # Example: {'group_by_similarity': ['similarity_group_id']}

    # 3. Collect all field names to copy from contents
    passthrough_fields = []
    for action_name, field_list in passthrough_config.items():
        for field_name in field_list:
            if field_name in contents:
                passthrough_fields.append(field_name)

    # 4. Merge fields using DataTransformer.update_schema_objects()
    #    (same method used by observe)
    for item in generated_data:
        merged = DataTransformer.update_schema_objects(
            contents,           # Source (has passthrough fields)
            item['content'],    # Target (LLM output)
            passthrough_fields  # Fields to copy
        )
```

## Debug Logging

Extensive debug logging is **currently active** in `_apply_context_scope_passthrough()` to verify the fix:

```
================================================================================
DEBUG _apply_context_scope_passthrough called
  agent_config type: <class 'dict'>
  agent_config keys: ['agent_type', 'name', 'model_vendor', ..., 'context_scope']
  context_scope value: {'passthrough': {'group_by_similarity': ['similarity_group_id']}}
  context_scope type: <class 'dict'>
  passthrough_config: {'group_by_similarity': ['similarity_group_id']}
  contents keys: ['similarity_group_id', 'facts_list', 'source_guid', ...]
  Checking action 'group_by_similarity' with fields: ['similarity_group_id']
    Found 'similarity_group_id' in contents - ADDED
  Final passthrough_fields: ['similarity_group_id']
  generated_data is list with N items
  already_structured: True
  Using STRUCTURED mode (merging into 'content' dict)
    Merged into structured item
  COMPLETED structured merge
================================================================================
```

### What to Look For in Debug Output

**BEFORE the fix (broken):**
- `context_scope value: None` ❌

**AFTER the fix (working):**
- `context_scope value: {'passthrough': {'group_by_similarity': ['similarity_group_id']}}` ✅
- `Found 'similarity_group_id' in contents - ADDED` ✅
- `Merged into structured item` ✅

## Expected Result

When running the workflow, `similarity_group_id` should now appear in the `Cluster_Validation_Agent` output:

```json
{
  "source_guid": "...",
  "content": {
    "similarity_group_id": "group_123",  // ← Should be present!
    "validation_result": "...",
    // ... other fields from LLM ...
  }
}
```

## Next Steps

1. **Run the workflow** with the fixed code
2. **Check debug output** to verify `context_scope` is no longer `None`
3. **Verify field in output** that `similarity_group_id` appears in final JSON
4. **Remove debug logging** once confirmed working (lines 76-175 in data_processor.py)

## Related Documentation

- `/dev_artefacts/OBSERVE_IMPLEMENTATION_ANALYSIS.md` - How observe works (pattern we followed)
- `/dev_artefacts/implementations/context_scope_passthrough_consolidation/` - Original implementation docs
- GitHub Issue #484 - Tool output schema requirement (related enhancement)

## Technical Notes

### Why `exclude_unset=True` Was Used

The original intention was likely to:
1. Only serialize fields explicitly set by users
2. Avoid polluting configs with default values
3. Keep serialized output minimal

### Why It Failed

Pydantic treats fields with defaults as "unset" unless explicitly assigned during initialization:

```python
# In AgentConfig schema:
context_scope: Optional[ContextScopeConfig] = Field(default=None, ...)

# When loaded from YAML:
config = AgentConfig.model_validate({
    'agent_type': 'quiz_gen',
    'context_scope': {'passthrough': {'source': ['id']}}
})

# Pydantic sees context_scope as "unset" because it has a default value
# So model_dump(exclude_unset=True) excludes it!
```

### The Fix

Use `model_dump(exclude_defaults=True)` instead of `exclude_unset=True`:
- Fields explicitly set in YAML are included (even if they have defaults)
- Fields with default values are excluded (no empty `observe: []`)
- `context_scope` with actual values makes it through to the processing pipeline
- Maintains backward compatibility for validation rules

## Testing Checklist

- [ ] Debug output shows `context_scope` is a dict (not `None`)
- [ ] Debug output shows `passthrough_config` is extracted
- [ ] Debug output shows field found in contents
- [ ] Debug output shows merge completed
- [ ] Final output JSON contains `similarity_group_id` field
- [ ] Field value matches original input from `group_by_similarity`
- [ ] No errors or exceptions during workflow execution
