# Bug Fix Summary: Source Reference and Where Clause Issues

**Date:** 2025-12-02
**Issues Fixed:** 2 critical bugs in batch processing
**Status:** ✅ Resolved

---

## Issue 1: AttributeError in where_clause Processing

### Symptoms
```
AttributeError: 'NoneType' object has no attribute 'get'
  File "agent_actions/llm_invocation/batch/batch_service.py", line 84
    behavior = where_config.get('behavior', 'filter')
               ^^^^^^^^^^^^^^^^
```

### Root Cause
In `batch_service.py:83-84`, the code was:
```python
where_config = agent_config.get('where_clause', {})
behavior = where_config.get('behavior', 'filter')
```

**The Problem:** When `agent_config['where_clause']` exists but is explicitly set to `None` in the YAML configuration, the `.get('where_clause', {})` method returns `None` instead of the default `{}`. This is because `.get()` only uses the default value when the **key doesn't exist**, not when the value is `None`.

### Fix Applied
**File:** `agent_actions/llm_invocation/batch/batch_service.py:83`

```python
# Before
where_config = agent_config.get('where_clause', {})

# After
where_config = agent_config.get('where_clause') or {}
```

**Explanation:** Using `or {}` ensures that if `where_clause` is `None`, it defaults to an empty dict, preventing the AttributeError.

---

## Issue 2: Source Reference Not Found During Batch Task Preparation

### Symptoms
```
ValueError: Error resolving {source.exam_name}: Reference 'source' not found. Available: [seed]
  File "agent_actions/preprocessing/prompt_utils.py", line 155
  File "agent_actions/prompt_generation/prompt_preparation_service.py", line 318
  File "agent_actions/llm_invocation/batch/batch_task_preparator.py", line 255
```

Users couldn't reference `{source.field_name}` in their prompts even though source data clearly existed in the staging files.

### Root Cause: Chicken-and-Egg Timing Problem

**The Problem:** In `staging_loader.py`, there was a critical ordering issue:

1. **Line 63:** JSON list data was loaded and `data_chunk` created with `source_guid`
2. **Line 85:** `submit_batch_job()` was called
3. **Inside submit_batch_job → prepare_batch_tasks → _prepare_single_task:**
   - Line 255: `PromptPreparationService.prepare_prompt_with_context()` was called
   - This triggered field reference replacement for `{source.exam_name}`
   - The system tried to load source data from the source folder
4. **But the source data hadn't been saved yet!**
5. **Lines 96-102:** Source data was only saved AFTER `submit_batch_job()` returned

**Sequence Diagram:**
```
staging_loader.py:
  ├─ Line 63: Create data_chunk with source_guid ✓
  ├─ Line 85: submit_batch_job() called
  │   └─ prepare_batch_tasks()
  │       └─ _prepare_single_task()
  │           └─ PromptPreparationService.prepare_prompt_with_context()
  │               └─ build_field_context_with_history()
  │                   └─ Try to load source from source folder ✗ FAILS
  │                       (source file doesn't exist yet!)
  │
  └─ Lines 96-102: Save source to source folder (TOO LATE!)
```

### Technical Details

**How Source Loading Works:**

In `context_scope_processor.py:444-478`, the `build_field_context_with_history()` method attempts to load source data:

1. Checks if `current_item` has a `source_guid`
2. Uses `file_path` to construct the path to the source folder
3. Calls `SourceDataLoader` to load the source file
4. Looks up the specific item by `source_guid`
5. If successful, adds `{'source': {...}}` to field_context
6. If fails, falls back to `source_content` parameter (if provided)

In batch mode (via `batch_task_preparator.py:255`), the call to `prepare_prompt_with_context()` does NOT provide a `source_content` parameter, so it relies entirely on loading from the source folder.

### Fix Applied
**File:** `agent_actions/preprocessing/staging_loader.py:85-92`

Moved the source data saving to BEFORE the `submit_batch_job()` call:

```python
# Lines 85-92: Save source data FIRST
for row in data_chunk:
    source_guid = row.get('source_guid')
    if source_guid:
        src_text = row.copy()
        batch_service._save_task_source([src_text], file_path, base_directory, output_directory)

# Line 94-95: NOW submit batch job (source is available)
file_name = Path(file_path).name
result = batch_service.submit_batch_job(agent_config, file_name, data_chunk, output_directory)
```

**New Sequence:**
```
staging_loader.py:
  ├─ Line 63: Create data_chunk with source_guid ✓
  ├─ Lines 86-92: Save source to source folder ✓ (MOVED HERE)
  ├─ Line 95: submit_batch_job() called
  │   └─ prepare_batch_tasks()
  │       └─ _prepare_single_task()
  │           └─ PromptPreparationService.prepare_prompt_with_context()
  │               └─ build_field_context_with_history()
  │                   └─ Load source from source folder ✓ SUCCESS!
```

---

## Files Modified

1. **`agent_actions/llm_invocation/batch/batch_service.py`**
   - Line 83: Fixed where_clause None handling

2. **`agent_actions/preprocessing/staging_loader.py`**
   - Lines 85-92: Moved source data saving before batch job submission

---

## Impact

### Before Fix
- ❌ Users couldn't use `{source.field}` references in prompts for batch-mode agents
- ❌ Agents with `where_clause: null` would crash with AttributeError
- ❌ Error: "Reference 'source' not found. Available: [seed]"

### After Fix
- ✅ Users can reference `{source.field}` in prompts for batch-mode agents
- ✅ where_clause properly handles None values
- ✅ Source data is available during task preparation
- ✅ Backward compatible with existing workflows

---

## Testing Recommendations

To verify the fix works:

1. **Test where_clause with None:**
   ```yaml
   agents:
     - name: test_agent
       where_clause: null  # Should not crash
   ```

2. **Test source references in batch mode:**
   ```yaml
   agents:
     - name: fact_extractor
       agent_type: staging
       prompt: "Extract facts from: {source.exam_name}"
   ```

3. **Test with JSON list input:**
   - Create a JSON file with a list of objects
   - Each object should have fields that will be referenced as `{source.field_name}`
   - Verify source data is loaded and available during prompt generation

---

## Related Code Locations

### Source Loading Logic
- `agent_actions/utilities/context_scope_processor.py:444-478` - `build_field_context_with_history()`
- `agent_actions/input_loading/extractors_source_data_loader.py` - `SourceDataLoader`
- `agent_actions/state_management/path_manager.py` - `PathManager`

### Batch Task Preparation
- `agent_actions/llm_invocation/batch/batch_task_preparator.py:233-277` - `_prepare_single_task()`
- `agent_actions/prompt_generation/prompt_preparation_service.py:150-343` - `prepare_prompt_with_context()`

### Field Reference Resolution
- `agent_actions/preprocessing/prompt_utils.py:96-156` - `resolve_field_reference()`, `replace_field_references()`

---

## Additional Notes

### Why This Bug Was Hard to Catch

1. **Non-obvious timing dependency:** The source saving happened after the code that needed it, but in a different function, making the dependency non-obvious
2. **Silent fallback failure:** The source loading has a try-except that catches errors silently and logs them as debug messages
3. **Only affects specific workflows:** Only happens when:
   - Using batch mode with staging agents
   - Input files are JSON lists (not chunked documents)
   - Prompts reference `{source.field}` patterns

### Why seed_data Worked But source Didn't

The error showed "Available: [seed]" because:
- `seed_data` is loaded from static files that already exist (loaded at prompt_preparation_service.py:251-284)
- `source` is dynamically loaded from the source folder during workflow execution
- Since source wasn't saved yet, only seed_data was available in the context

---

## Prevention for Future

To prevent similar issues:

1. **Principle:** Save all required data BEFORE operations that need it
2. **Review:** Any code that loads data during task/prompt preparation should verify the data exists
3. **Logging:** Consider upgrading the debug log at context_scope_processor.py:473 to a warning when source loading fails
4. **Testing:** Add integration tests that verify source data availability in batch mode

---

## Contact

If you encounter related issues:
- Check that source folder exists and has the correct structure: `base_directory/../source/`
- Verify source files are being created with correct `source_guid` values
- Enable debug logging to see source loading attempts
- Review this document for context on how source loading works

---

**End of Document**
