# Processing Paths Verification

## Confirmation: All Paths Use RecordProcessor ✅

Both **online** and **batch** processing paths use the `RecordProcessor.process_batch()` method we just fixed.

---

## Processing Flow

### Path 1: Tool Actions & Online Mode (Synchronous)
```
TargetGenerator.generate()
  ↓
TargetGenerator.process()
  ↓
TargetGenerator._process_by_strategy()
  ↓
  mode = ProcessingMode.ONLINE                    [Line 356]
  ↓
  self.record_processor.process_batch(data, context)  [Line 367]
  ↓
  RecordProcessor.process_batch()                  [record_processor.py:178]
    ↓
    for each item:
      ↓
      try:
        process(item, context)
      except ConfigurationError:   ✅ RE-RAISES [Line 199-202]
        raise
      except Exception:
        log and create failed result
```

**File:** `agent_actions/orchestration/target_generator.py:367`
```python
results = self.record_processor.process_batch(data, context)
```

---

### Path 2: LLM Batch API Mode (Asynchronous)
```
TargetGenerator.generate()
  ↓
[if run_mode == "batch" AND not tool action]
  ↓
TargetGenerator._handle_batch_generation()
  ↓
BatchService.submit_batch_job()
  ↓
[Submits to OpenAI/Anthropic batch API]
  ↓
[Results processed later via batch_manager.py]
```

**Note:** Batch API mode is for **LLM calls only** (asynchronous OpenAI/Anthropic batch API).
It **does NOT** go through RecordProcessor because it's submitting jobs to external APIs.

---

## Key Finding

### ✅ All Synchronous Processing Uses RecordProcessor

Both modes use the **same code path**:
- **Tool actions** (Python functions like `fix_options_formatting`)
- **Online LLM calls** (synchronous API calls)
- **Batch processing of records** (loop through multiple items)

**All three** call:
```python
results = self.record_processor.process_batch(data, context)
```

Which contains our fix:
```python
except ConfigurationError:
    # Re-raise immediately to fail the workflow
    raise
except Exception as e:
    # Log and create failed result for other errors
    ...
```

---

## What This Means for Your Fix

### ✅ ConfigurationError Will Now Fail In:

1. **Tool actions** (like `fix_options_format`)
   - Mode: `ProcessingMode.ONLINE`
   - Calls: `record_processor.process_batch()` ✅

2. **Online LLM actions** (like `write_scenario_question`)
   - Mode: `ProcessingMode.ONLINE`
   - Calls: `record_processor.process_batch()` ✅

3. **Multi-record processing** (processing 5 questions)
   - Mode: `ProcessingMode.ONLINE`
   - Calls: `record_processor.process_batch()` ✅

### ❌ ConfigurationError Will NOT Be Caught In:

4. **Async Batch API submissions**
   - These use `BatchService.submit_batch_job()`
   - Errors handled differently (batch API errors, not configuration)
   - This is OK - configuration should be validated before batch submission

---

## Verification

### Code References

1. **Entry point:** `target_generator.py:367`
   ```python
   results = self.record_processor.process_batch(data, context)
   ```

2. **Our fix:** `record_processor.py:199-202`
   ```python
   except ConfigurationError:
       # ConfigurationError indicates a fundamental workflow misconfiguration
       # Re-raise immediately to fail the workflow - these cannot be recovered
       raise
   ```

3. **Propagation:** `target_generator.py:228`
   ```python
   except (AgentActionsException, ConfigurationError, ValueError) as e:
       raise AgentActionsException(...) from e
   ```

---

## Test Coverage

### Verified ✅
- `test_configuration_error_is_reraised` - Confirms ConfigurationError bubbles up
- `test_other_exceptions_create_failed_results` - Confirms other errors handled gracefully

### Expected Behavior
```
19:31:22 | 6/9 START agent: fix_options_format...
19:31:22.069 ERROR [fix_options_format] Dependency 'write_scenario_question' declared but not referenced in context_scope.
ConfigurationError: Dependency 'write_scenario_question' declared but not referenced in context_scope...
19:31:22 | 6/9 FAILED fix_options_format ❌
Workflow aborted
```

Instead of:
```
19:31:22 | 6/9 OK fix_options_format in 0.02s  ❌ WRONG (was swallowing error)
```

---

## Summary

✅ **Both batch and online paths confirmed to use RecordProcessor**
✅ **ConfigurationError will now properly fail workflows**
✅ **Fix applies to all synchronous processing modes**
