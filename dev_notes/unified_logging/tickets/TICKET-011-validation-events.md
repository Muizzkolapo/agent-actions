# TICKET-011: Add Validation Events

**Status:** ✅ DONE
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, validation, instrumentation

## Description

Instrument validation logic to fire events for validation start, completion, errors, and warnings.

## Deliverables

- [x] Fire `ValidationStartEvent` when validation begins
- [x] Fire `ValidationCompleteEvent` on success
- [x] Fire `ValidationErrorEvent` for validation failures
- [x] Fire `ValidationWarningEvent` for warnings

## Files Modified

```
agent_actions/logging/events/types.py         # Updated event classes with validator, value fields
agent_actions/validation/base_validator.py    # Added event firing infrastructure
agent_actions/validation/schema_validator.py  # Instrumented with validation events
agent_actions/validation/config_validator.py  # Instrumented with validation events
```

## Event Data

### ValidationStartEvent (V001)

```python
fire_event(ValidationStartEvent(
    target="agent_config",
    validator="schema",
))
```

### ValidationCompleteEvent (V002)

```python
fire_event(ValidationCompleteEvent(
    target="agent_config",
    validator="schema",
    elapsed_time=0.05,
))
```

### ValidationErrorEvent (V003)

```python
fire_event(ValidationErrorEvent(
    target="agent_config",
    field="model",
    error="Invalid model name",
    value="gpt-5",
))
```

### ValidationWarningEvent (V004)

```python
fire_event(ValidationWarningEvent(
    target="agent_config",
    field="temperature",
    warning="Temperature > 1.0 may produce inconsistent results",
    value=1.5,
))
```

## Console Output

Validation errors should show clearly:

```
10:30:45 | VALIDATION ERROR in agent_config.model: Invalid model name (got: "gpt-5")
```

## Acceptance Criteria

- [x] Schema validation fires events
- [x] Config validation fires events
- [x] Errors show field + value + message
- [x] Warnings are distinguishable from errors

## Implementation Notes

### Changes Made

1. **Updated Validation Event Classes** (`agent_actions/logging/events/types.py`):
   - `ValidationStartEvent`: Now takes `target` and `validator` fields
   - `ValidationCompleteEvent`: Now takes `target`, `validator`, `elapsed_time`, `warnings`, and `errors` fields
   - `ValidationErrorEvent`: Now takes `target`, `field`, `error`, and `value` fields
   - `ValidationWarningEvent`: Now takes `target`, `field`, `warning`, and `value` fields

2. **Enhanced Base Validator** (`agent_actions/validation/base_validator.py`):
   - Added `_validation_target`, `_validation_start_time`, and `_fire_events` instance variables
   - Added `validator_name` property for consistent event naming
   - Updated `add_error()` to fire `ValidationErrorEvent` with field and value info
   - Updated `add_warning()` to fire `ValidationWarningEvent` with field and value info
   - Updated `_prepare_validation()` to fire `ValidationStartEvent` and record start time
   - Added `_complete_validation()` to fire `ValidationCompleteEvent` with elapsed time and counts

3. **Instrumented Schema Validator** (`agent_actions/validation/schema_validator.py`):
   - Updated `validate()` to use new event infrastructure
   - Updated `_process_schema_file()` to provide field info in errors

4. **Instrumented Config Validator** (`agent_actions/validation/config_validator.py`):
   - Updated `validate()` to use new event infrastructure
   - Updated all error/warning calls to include field and value information

### Console Output Example

```
10:30:45 | DEBUG | Validating agent_config (SchemaValidator)
10:30:45 | ERROR | VALIDATION ERROR in agent_config.model: Invalid model name (got: "gpt-5")
10:30:45 | WARN  | VALIDATION WARNING in agent_config.temperature: Temperature > 1.0 may produce inconsistent results (value: 1.5)
10:30:45 | DEBUG | Validation failed: agent_config in 0.05s (1 warnings, 1 errors)
```
