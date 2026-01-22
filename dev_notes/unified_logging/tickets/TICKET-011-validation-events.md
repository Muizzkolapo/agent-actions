# TICKET-011: Add Validation Events

**Status:** 🔲 TODO
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, validation, instrumentation

## Description

Instrument validation logic to fire events for validation start, completion, errors, and warnings.

## Deliverables

- [ ] Fire `ValidationStartEvent` when validation begins
- [ ] Fire `ValidationCompleteEvent` on success
- [ ] Fire `ValidationErrorEvent` for validation failures
- [ ] Fire `ValidationWarningEvent` for warnings

## Files to Modify

```
agent_actions/validation/validator.py
agent_actions/validation/schema.py
agent_actions/validation/rules.py
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

- [ ] Schema validation fires events
- [ ] Config validation fires events
- [ ] Errors show field + value + message
- [ ] Warnings are distinguishable from errors
