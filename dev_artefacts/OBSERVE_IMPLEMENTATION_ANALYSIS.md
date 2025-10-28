# How `observe` Works on Main Branch - Complete Analysis

**Date:** 2025-10-28
**Branch Analyzed:** main
**Purpose:** Understand how `observe` successfully passes through fields to identify why `context_scope.passthrough` is failing

---

## Executive Summary

The `observe` feature works because it operates **AFTER** the LLM runs, in the **data processing phase**, not during config parsing. The key insight: `observe` reads directly from the raw `agent_config` dict (not a Pydantic model), and merges fields from `contents` into `generated_data` using `DataTransformer.update_schema_objects()`.

---

## Data Flow Architecture

### Complete Pipeline

```
YAML Config
    ↓
Config Loader (parses YAML to dict)
    ↓
Agent Config Dict (contains 'observe': [...])
    ↓
TargetContentProcessor.__init__(agent_config)  ← Config passed as dict
    ↓
DataProcessor.__init__(agent_config)  ← Same config dict
    ↓
[LLM Execution happens]
    ↓
DataProcessor.process_item(contents, generated_data, ...)
    ↓
transform_with_observe(generated_data, contents, agent_config, ...)  ← KEY FUNCTION
    ↓
DataTransformer.update_schema_objects(contents, llm_output, observe_fields)  ← MERGE
    ↓
Final Output (with observed fields merged in)
```

---

## Files Involved

### 1. Configuration Definition
**File:** `agent_actions/utilities/constants.py`
```python
OBSERVE_KEY = "observe"
```

### 2. Data Processing Entry Point
**File:** `agent_actions/preprocessing/data_processor.py`

**Key Method:**
```python
def process_item(self, contents: Dict, generated_data: List[Dict],
                 source_guid: str, idx: int=0) -> List[Dict]:
    """Process generated data with observe transformations."""
    try:
        return transform_with_observe(
            generated_data,  # LLM output
            contents,        # Original input with fields to observe
            source_guid,
            self.agent_config,  # ← Contains 'observe' field
            idx
        )
    except Exception as e:
        self.handle_processing_error(...)
```

**Call Site:** Line 48
**Caller:** `TargetContentProcessor._process_single_item()` at line 350

---

### 3. Transform Logic
**File:** `agent_actions/utilities/utils_processor_helpers.py`

**Function:** `transform_with_observe()` (line 95)

**Signature:**
```python
def transform_with_observe(
    data: list,              # LLM output
    context_data: dict,      # Original contents
    source_guid: str,
    agent_config: Dict,      # ← Raw dict, NOT Pydantic model
    idx: int = 0
) -> list:
```

**Implementation:**
```python
def transform_with_observe(data, context_data, source_guid, agent_config, idx=0):
    if not isinstance(data, list):
        data = [data] if data is not None else []

    # Get observe fields directly from dict
    observe = agent_config.get(OBSERVE_KEY, [])  # ← Direct dict access!

    if not observe:
        return data  # No transformation needed

    # Extract content if nested
    context_for_observe = context_data
    if isinstance(context_data, dict) and 'content' in context_data:
        context_for_observe = context_data['content']

    # Merge observed fields into each output item
    updated = []
    for item in data:
        if isinstance(item, dict):
            # Merge observe fields from context into item
            merged = DataTransformer.update_schema_objects(
                context_for_observe,  # Source of observe fields
                item,                 # LLM output
                observe              # Field names to copy
            )
            updated.append(merged)

    return updated
```

**Key Points:**
1. **Direct dict access:** `agent_config.get(OBSERVE_KEY, [])` - no Pydantic model
2. **Post-LLM execution:** Called AFTER LLM generates data
3. **Simple merge:** Uses `update_schema_objects` to copy fields

---

### 4. Field Merging Logic
**File:** `agent_actions/preprocessing/data_transformer.py`

**Method:** `update_schema_objects()` (line 56)

```python
@staticmethod
def update_schema_objects(
    data_old: Dict[str, Any],     # Source (original contents)
    data_new: Dict[str, Any],     # Target (LLM output)
    keys_to_update: List[str]     # Fields to copy (observe list)
) -> Dict[str, Any]:
    """
    Merge fields from data_old into data_new.

    Rules:
    - If types match: replace data_new value with data_old value
    - If types differ: create list with both values
    - If key not in data_new: add it
    """
    result = copy.deepcopy(data_new)

    for key in keys_to_update:
        if key in data_old:
            old_value = data_old[key]
            new_value = result.get(key)

            if new_value is not None:
                if isinstance(old_value, type(new_value)):
                    result[key] = copy.deepcopy(old_value)  # Replace
                else:
                    result[key] = [new_value, copy.deepcopy(old_value)]  # Merge
            else:
                result[key] = copy.deepcopy(old_value)  # Add

    return result
```

---

## Call Chain Analysis

### Where is `transform_with_observe` called?

**1. Primary Call Site:**
```
TargetContentProcessor._process_single_item()
    ↓ (line 350)
DataProcessor.process_item(contents, generated_data, source_guid)
    ↓ (line 48)
transform_with_observe(generated_data, contents, source_guid, agent_config, idx)
```

**2. Usage in Other Processors:**
- `ResponseTransformer` (agent_actions/preprocessing/response_transformer.py)
- `PPResponseTransformer` (agent_actions/preprocessing/pp_response_transformer.py)
- `TargetDataProcessor` (agent_actions/prompt_generation/target_data_processor.py)

---

## Why `observe` Works But `context_scope.passthrough` Doesn't

### `observe` Success Factors:

| Factor | Implementation |
|--------|----------------|
| **Config Access** | Direct dict: `agent_config.get('observe', [])` |
| **Execution Timing** | POST-LLM in data processing phase |
| **Data Source** | `contents` parameter passed to `process_item()` |
| **Merge Logic** | Simple `update_schema_objects()` function |
| **No Validation** | No Pydantic model parsing/validation |

### `context_scope.passthrough` Failure Points:

| Issue | Root Cause |
|-------|------------|
| **Config is `None`** | `agent_config['context_scope']` returns `None` |
| **Not in dict** | Pydantic model field, not raw dict value |
| **Validation Error?** | Possible schema validation setting it to `None` |
| **Wrong Location** | Attempted in `DataGenerator` (PRE-LLM), not in `DataProcessor` (POST-LLM) |

---

## Key Differences

### `observe` (Working)

```python
# In data_processor.py - POST LLM
def process_item(self, contents, generated_data, ...):
    # agent_config is a plain dict
    observe = self.agent_config.get('observe', [])  # ✅ Works
    return transform_with_observe(generated_data, contents, ...)
```

### `context_scope.passthrough` (Broken)

```python
# In target_content_processor.py - POST LLM
def _apply_passthrough_fields(self, generated_data, original_contents):
    # agent_config is a plain dict
    context_scope = self.agent_config.get('context_scope')  # ❌ Returns None!
    passthrough_config = context_scope.get('passthrough', {})  # ❌ Crashes
```

---

## Solution Path

### Option 1: Follow `observe` Pattern Exactly

**Location:** `agent_actions/preprocessing/data_processor.py`

**Change:**
```python
def process_item(self, contents, generated_data, source_guid, idx=0):
    # First apply observe (legacy)
    result = transform_with_observe(generated_data, contents, source_guid,
                                     self.agent_config, idx)

    # Then apply context_scope.passthrough (new)
    result = self._apply_context_scope_passthrough(result, contents)

    return result

def _apply_context_scope_passthrough(self, generated_data, contents):
    """Apply context_scope.passthrough like observe does."""
    # Read directly from dict like observe does
    context_scope = self.agent_config.get('context_scope')

    if not context_scope or not isinstance(context_scope, dict):
        return generated_data

    passthrough_config = context_scope.get('passthrough', {})
    if not passthrough_config:
        return generated_data

    # Collect all passthrough fields
    passthrough_fields = []
    for action_name, field_list in passthrough_config.items():
        for field_name in field_list:
            if field_name in contents:
                passthrough_fields.append(field_name)

    if not passthrough_fields:
        return generated_data

    # Use same merge logic as observe
    if isinstance(generated_data, list):
        return [
            DataTransformer.update_schema_objects(contents, item, passthrough_fields)
            if isinstance(item, dict) else item
            for item in generated_data
        ]
    elif isinstance(generated_data, dict):
        return DataTransformer.update_schema_objects(contents, generated_data,
                                                     passthrough_fields)
    else:
        return generated_data
```

---

### Option 2: Fix Config Parsing

**Issue:** `context_scope` is being set to `None` during config parsing/validation

**Investigation Needed:**
1. Check config loader/parser
2. Check Pydantic model validation
3. Check if there's a preprocessing step clearing it

**Files to Check:**
- `agent_actions/prompt_generation/config_loader.py`
- `agent_actions/response_processing/config_schema.py`
- Any validators on `AgentConfig` class

---

## Recommended Implementation

### Use Option 1 (Follow `observe` Pattern)

**Reasons:**
1. ✅ **Proven to work** - `observe` has been in production
2. ✅ **Same location** - POST-LLM in data processor
3. ✅ **Same mechanism** - Direct dict access, no Pydantic issues
4. ✅ **Minimal changes** - Add one method to DataProcessor
5. ✅ **Backward compatible** - Works alongside `observe`

**Implementation File:**
- `agent_actions/preprocessing/data_processor.py`

**Lines to Change:**
- Line 48: Wrap `transform_with_observe` result
- Add new method: `_apply_context_scope_passthrough()`

**Import Needed:**
```python
from agent_actions/preprocessing/data_transformer import DataTransformer
```

---

## Testing Strategy

### Test Case 1: Basic Passthrough
```yaml
- name: test_agent
  context_scope:
    passthrough:
      source: [id, url]
```

**Expected:** `id` and `url` from input appear in output

### Test Case 2: Dependency Passthrough
```yaml
- name: test_agent
  dependencies: [group_by_similarity]
  context_scope:
    passthrough:
      group_by_similarity: [similarity_group_id]
```

**Expected:** `similarity_group_id` from dependency output appears in final output

### Test Case 3: List Output (File Granularity)
```yaml
- name: tool_action
  kind: tool
  granularity: file  # Returns list

- name: next_agent
  context_scope:
    passthrough:
      tool_action: [field_from_tool]
```

**Expected:** Each item in list output has `field_from_tool`

---

## Files Summary

| File | Role | Lines Modified |
|------|------|----------------|
| `agent_actions/utilities/constants.py` | Constant definition | N/A (read only) |
| `agent_actions/preprocessing/data_processor.py` | **MAIN IMPLEMENTATION** | 48, +new method |
| `agent_actions/utilities/utils_processor_helpers.py` | Transform logic (reference) | N/A (read only) |
| `agent_actions/preprocessing/data_transformer.py` | Field merging (reuse) | N/A (reuse existing) |

---

## Conclusion

The `observe` feature succeeds because:
1. It operates POST-LLM in the data processing phase
2. It reads from raw `agent_config` dict (no Pydantic issues)
3. It uses simple, proven merge logic
4. It has direct access to both `contents` and `generated_data`

To fix `context_scope.passthrough`, we should:
1. **Follow the same pattern** in `DataProcessor.process_item()`
2. **Reuse existing infrastructure** (`DataTransformer.update_schema_objects`)
3. **Avoid Pydantic model issues** by reading from dict directly
4. **Apply POST-LLM** where both input and output are available

This approach is minimal, proven, and backward compatible.
