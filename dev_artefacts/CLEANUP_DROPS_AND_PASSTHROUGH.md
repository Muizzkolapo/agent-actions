# Cleanup: Removed drops and context_scope.passthrough

## Summary

Per user request:
> "remove the support for passthrough, completely remove support for drop such that it does not even appear at all in any code error handling deprecation message, but we keep observe as is for now"

### What Was Removed
1. ✅ **`drops` field** - Completely removed from entire codebase
2. ✅ **`context_scope.passthrough`** - Removed passthrough mode from ContextScopeConfig

### What Was Kept
1. ✅ **`observe` field** - Fully functional for field passthrough
2. ✅ **`context_scope.include`** - Whitelist mode for LLM input
3. ✅ **`context_scope.exclude`** - Blacklist mode to filter heavy fields

## Files Modified

### 1. `/agent_actions/response_processing/config_schema.py`

**Removed `drops` field:**
```python
# REMOVED
drops: List[str] = Field(default_factory=list)

# KEPT
observe: List[str] = Field(default_factory=list)
```

**Removed `passthrough` from ContextScopeConfig:**
```python
# BEFORE
class ContextScopeConfig(BaseModel):
    include: Optional[Dict[str, List[str]]] = ...
    exclude: Optional[Dict[str, List[str]]] = ...
    passthrough: Optional[Dict[str, List[str]]] = ...  # ❌ REMOVED

# AFTER
class ContextScopeConfig(BaseModel):
    include: Optional[Dict[str, List[str]]] = ...
    exclude: Optional[Dict[str, List[str]]] = ...
    # passthrough removed - use 'observe' field instead
```

**Removed deprecation validator:**
- Removed entire `reject_observe_and_drops()` validator (40+ lines)
- This validator was rejecting observe/drops usage

### 2. `/agent_actions/preprocessing/data_processor.py`

**Removed `_apply_context_scope_passthrough()` method:**
- Removed entire method (120+ lines)
- Reverted `process_item()` to only use `transform_with_observe()`

```python
# AFTER (simplified)
def process_item(self, contents: Dict, generated_data: List[Dict], source_guid: str, idx: int=0) -> List[Dict]:
    try:
        return transform_with_observe(generated_data, contents, source_guid, self.agent_config, idx)
    except Exception as e:
        self.handle_processing_error(...)
```

### 3. `/agent_actions/response_processing/action_expander.py`

**Removed drops handling:**
```python
# REMOVED all drops-related code
# defaults_drops = defaults.get('drops', [])
# action_drops = action.get('drops', [])
# combined_drops = ...
# agent['drops'] = drops

# KEPT observe handling
defaults_observe = defaults.get('observe', [])
action_observe = action.get('observe', [])
combined_observe = list(dict.fromkeys(defaults_observe + action_observe))
observe = template_replacer(combined_observe)
agent['observe'] = observe
```

### 4. `/agent_actions/validation/config_validator.py`

**Removed drops from validation:**
```python
# REMOVED 'drops' from allowed keys
_OPTIONAL_AGENT_KEYS: Set[str] = {..., OBSERVE_KEY, ...}  # No 'drops'

# REMOVED drops validation error
if model_vendor == 'tool' and granularity == 'file':
    if OBSERVE_KEY in entry_ci:
        self.add_error(...)
    # Removed: if 'drops' in entry_ci: self.add_error(...)
```

### 5. `/agent_actions/utilities/constants.py`

**Removed DROPS_KEY constant:**
```python
# REMOVED
# DROPS_KEY = "drops"

# KEPT
OBSERVE_KEY = "observe"
```

### 6. `/agent_actions/state_management/signatures.py`

**Removed dropped_fields from OutputSignature:**
```python
# BEFORE
class OutputSignature(BaseModel):
    schema_fields: List[str] = []
    observe_fields: List[str] = []
    dropped_fields: List[str] = []  # ❌ REMOVED

# AFTER
class OutputSignature(BaseModel):
    schema_fields: List[str] = []
    observe_fields: List[str] = []
```

### 7. `/agent_actions/state_management/signature_computer.py`

**Removed drops computation:**
```python
# BEFORE
dropped_fields = agent_config.get('drops', agent_config.get('drops', []))
return OutputSignature(schema_fields=..., observe_fields=..., dropped_fields=dropped_fields)

# AFTER
return OutputSignature(schema_fields=..., observe_fields=...)
```

## What Still Works

✅ **`observe` field** - For field passthrough (copy to output)
✅ **`context_scope.include`** - Whitelist fields for LLM
✅ **`context_scope.exclude`** - Blacklist heavy fields from LLM
✅ **Config validation** - All other validations intact
✅ **Workflow execution** - Tested successfully

## Migration Guide

### For users who were using `drops`:
`drops` is no longer supported. Use `context_scope.exclude` instead:

```yaml
# OLD (no longer works)
- name: my_agent
  drops: [page_content, raw_html]

# NEW (use context_scope.exclude)
- name: my_agent
  context_scope:
    exclude:
      source: [page_content, raw_html]
```

### For users who were using `context_scope.passthrough`:
`passthrough` mode is no longer supported. Use `observe` instead:

```yaml
# OLD (no longer works)
- name: my_agent
  context_scope:
    passthrough:
      source: [id, url]

# NEW (use observe)
- name: my_agent
  observe: [id, url]
```

## Test Results

Tested with `qanalabs_quiz_gen` workflow:
```
🎉 Workflow Complete

- fact_extractor: completed
- flatten_the_facts: completed
- cluster_list: completed
- group_by_similarity: completed
- Cluster_Validation_Agent: completed
- flatten_clusters: completed
- classify_feynman: completed
- generate_summary: completed
```

## Why This Cleanup

1. **`drops` was unused** - No production usage
2. **`context_scope.passthrough` was broken** - Never worked correctly
3. **Simpler mental model** - Use `observe` for passthrough, `context_scope` for LLM filtering
4. **Reduced complexity** - Removed ~200 lines of untested code

## Final State

| Feature | Status | Purpose |
|---------|--------|---------|
| `observe` | ✅ Kept | Copy fields to output without sending to LLM |
| `context_scope.include` | ✅ Kept | Whitelist fields for LLM input |
| `context_scope.exclude` | ✅ Kept | Blacklist fields from LLM input |
| `drops` | ❌ Removed | Deprecated - use `context_scope.exclude` |
| `context_scope.passthrough` | ❌ Removed | Deprecated - use `observe` |
