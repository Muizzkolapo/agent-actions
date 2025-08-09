# Batch Dispatch Function Data Structure Fix

## Problem
Dispatch functions (called via `dispatch_task()` in prompts) were failing in batch mode with errors like:
```
Error executing user function 'generate_single_distractor_edit_prompt_1': 'options'
```

The issue occurred when:
1. Agent stage 1 produces output with dispatch results merged at the top level
2. This output gets wrapped by `transform_structure` as: `{"source_guid": "...", "content": {...}}`
3. Agent stage 2 in batch mode receives this wrapped structure
4. When dispatch functions try to access fields like `data['options']`, they fail because the field is nested at `data['content']['options']`

## Root Cause
**Inconsistent data structure between online and batch processing for dispatch functions:**

**Online Processing:**
1. Receives wrapped data: `{"source_guid": "...", "content": {"options": [...]}}`
2. **Extracts content**: `contents = item['content']` (in target_content_processor.py:251)
3. Passes unwrapped content to `run_dynamic_agent(contents, ...)`
4. Dispatch functions receive flat structure: `{"options": [...], "question": "..."}`

**Batch Processing (Before Fix):**
1. Receives wrapped data: `{"source_guid": "...", "content": {"options": [...]}}`
2. **Used wrapped data directly**: `processed_row = apply_remove_collection(row, ...)`
3. Passes wrapped structure to `inject_function_outputs_into_prompt(json.dumps(processed_row))`
4. Dispatch functions receive wrapped structure and fail accessing nested fields

## Solution
Modified `prepare_batch_tasks_from_data()` in `agent_actions/services/batch_service.py` to extract content from wrapped structures before processing, matching online behavior.

## Code Changes
```python
# Before: Used wrapped row directly
processed_row = apply_remove_collection(row, agent_config)

# After: Extract content from wrapped structure first
if 'source_guid' in row and 'content' in row:
    # Wrapped structure - extract the content
    row_content = row['content']
else:
    # Already unwrapped or different structure
    row_content = row

processed_row = apply_remove_collection(row_content, agent_config)
```

## Impact
- Dispatch functions now receive the same flat data structure in both online and batch modes
- Fixes `KeyError` failures when dispatch functions try to access fields like 'options', 'question', etc.
- Maintains consistency between online and batch processing workflows
- No changes required to existing dispatch function implementations

## Testing Recommendation
Test workflows with `add_dispatch: true` in both online and batch modes to verify dispatch functions work consistently.