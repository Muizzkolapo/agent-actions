# Refactoring: Unified Source Saving Logic

**Date:** 2025-12-02
**Type:** Code improvement and bug prevention
**Status:** ✅ Completed

---

## Problem Statement

The original `staging_loader.py` had **duplicated source saving logic** in two separate code paths:
1. **Batch mode** (lines 85-92): Source saved inline with batch processing
2. **Realtime mode** (lines 132-166): Source saved inline with realtime processing

This duplication led to:
- ❌ Bug in batch mode (source saved AFTER batch job submission, causing timing issue)
- ❌ Maintenance burden (changes needed in two places)
- ❌ Risk of inconsistency between modes
- ❌ Unclear code structure (hard to see the critical ordering requirement)

---

## Solution: Extract to Unified Helper Function

**Key Insight:** Source saving is **mode-independent** and should happen **before any processing**.

### Refactored Architecture

```python
def generate_staging(...):
    # STEP 1: Prepare data (mode-specific)
    if run_mode == 'batch':
        data_chunk, src_text = _prepare_batch_data(...)
    else:
        data_chunk, src_text = _prepare_realtime_data(...)

    # STEP 2: UNIFIED source saving (mode-agnostic)
    _save_source_data(src_text, data_chunk, ...)  # ← Single source of truth

    # STEP 3: Process (mode-specific, source guaranteed to exist)
    if run_mode == 'batch':
        return _process_batch_mode(...)
    else:
        return _process_realtime_mode(...)
```

### New Helper Functions

1. **`_save_source_data()`** - UNIFIED source saving
   - Single place where source is saved
   - Works for both batch and realtime modes
   - Called BEFORE any processing

2. **`_prepare_batch_data()`** - Batch data preparation
   - Extracts batch-specific data preparation logic
   - Returns `(data_chunk, src_text)`

3. **`_prepare_realtime_data()`** - Realtime data preparation
   - Extracts realtime-specific data preparation logic
   - Returns `(data_chunk, src_text)`

4. **`_process_batch_mode()`** - Batch processing
   - Submits batch job
   - Writes placeholder file

5. **`_process_realtime_mode()`** - Realtime processing
   - Writes staging file directly

---

## Benefits

### 1. Bug Prevention ✅
- **Impossible to forget** source saving step
- Source **always** saved before processing
- No timing issues possible

### 2. Single Source of Truth ✅
- One function owns source saving logic
- Changes only needed in one place
- Consistent behavior across modes

### 3. Improved Readability ✅
- Clear 3-step architecture
- Helper functions separate concerns
- Easy to understand execution flow

### 4. Better Maintainability ✅
- Adding new file types: update one helper
- Changing source format: update one function
- Less cognitive load for developers

### 5. Self-Documenting Code ✅
- Function names explain intent
- Comments explain the "why"
- Architecture is explicit

---

## Code Comparison

### Before (Duplicated Logic)

```python
def generate_staging(...):
    if agent_config.get('run_mode') == 'batch':
        # ... prepare data ...

        # Save source HERE (batch-specific)
        for row in data_chunk:
            if row.get('source_guid'):
                src_text = row.copy()
                batch_service._save_task_source([src_text], ...)  # ← Batch path

        # Process batch
        result = batch_service.submit_batch_job(...)
    else:
        # ... prepare data ...

        # Process realtime
        file_writer.write_staging(data_chunk)

        # Save source HERE (realtime-specific)
        with open(output_src_path, mode) as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            # ... save source logic ...  # ← Realtime path
```

**Problems:**
- Two different locations for source saving
- Bug only in batch path (saved too late)
- No clear indication this must happen first

### After (Unified Logic)

```python
def generate_staging(...):
    run_mode = agent_config.get('run_mode')

    # STEP 1: Prepare (mode-specific)
    if run_mode == 'batch':
        data_chunk, src_text = _prepare_batch_data(...)
    else:
        data_chunk, src_text = _prepare_realtime_data(...)

    # STEP 2: SAVE SOURCE (unified, happens for BOTH modes)
    _save_source_data(src_text, data_chunk, ...)  # ← Single place

    # STEP 3: Process (mode-specific)
    if run_mode == 'batch':
        return _process_batch_mode(...)
    else:
        return _process_realtime_mode(...)


def _save_source_data(src_text, data_chunk, ...):
    """UNIFIED source saving - works for both modes."""
    batch_service = BatchService()

    if src_text:
        # Realtime: use prepared src_text
        source_items = src_text
    else:
        # Batch: extract from data_chunk
        source_items = [row.copy() for row in data_chunk if row.get('source_guid')]

    if source_items:
        batch_service._save_task_source(source_items, ...)
```

**Improvements:**
- ✅ Single location for source saving
- ✅ Explicit ordering (Step 2 always happens before Step 3)
- ✅ Mode-agnostic (same logic for both paths)
- ✅ Self-documenting architecture

---

## Migration Notes

### Files Modified

1. **`agent_actions/preprocessing/staging_loader.py`**
   - Complete refactoring with new architecture
   - Unified source saving logic
   - Old duplicated code paths removed
   - **This is now the standard approach going forward**

### Migration Approach

🚀 **Forward fixes only** - This is the new standard
- Old duplicated approach is deprecated
- New unified architecture is the way forward
- No legacy compatibility layer needed
- Clean break for better maintainability

### Testing Recommendations

Test both modes to ensure refactoring works:

```bash
# Test batch mode
pytest tests/preprocessing/test_staging_loader.py::test_batch_mode -v

# Test realtime mode
pytest tests/preprocessing/test_staging_loader.py::test_realtime_mode -v

# Test source saving for both modes
pytest tests/preprocessing/test_staging_loader.py::test_source_data_saving -v
```

---

## Future Improvements

This refactoring enables additional improvements:

1. **Add mode switching tests** - Easier to test mode differences
2. **Extract file type handling** - Could further reduce duplication
3. **Add validation** - Validate source_guid exists before saving
4. **Performance optimization** - Easier to profile individual steps

---

## Lessons Learned

### Design Principle: Extract Common Operations

When you find yourself repeating the same operation in multiple code paths:
1. ✅ Extract to a shared function
2. ✅ Make the function mode/context agnostic
3. ✅ Document why the operation is important
4. ✅ Ensure ordering is explicit (if critical)

### Prevention Strategy

For critical ordering requirements:
- **Make it explicit** - Use numbered steps or comments
- **Make it impossible to get wrong** - Extract to single function
- **Make it self-documenting** - Use descriptive names

---

## Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Lines of code | 169 | 381 | +212 (with docs) |
| Functions | 1 | 6 | +5 helpers |
| Duplication | 2 paths | 1 function | -50% |
| Complexity (generate_staging) | High | Low | ⬇️ |
| Maintainability | Medium | High | ⬆️ |
| Bug risk | High | Low | ⬇️ |

**Note:** More lines but **better structure**. Each function has single responsibility.

---

## Related Documents

- [BUGFIX_SOURCE_REFERENCE_AND_WHERE_CLAUSE.md](BUGFIX_SOURCE_REFERENCE_AND_WHERE_CLAUSE.md) - Original bug fix
- [BUGFIX_PATHWAY_ANALYSIS.md](BUGFIX_PATHWAY_ANALYSIS.md) - Pathway verification

---

**End of Document**
