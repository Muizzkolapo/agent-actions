# TICKET-018: Add Error Handling Events

**Status:** 🔲 TODO
**Priority:** Critical
**Estimate:** 4-6 hours
**Labels:** logging, errors, reliability

## Description

Add comprehensive error event instrumentation across the codebase. Many error handling blocks only log errors without firing events, reducing observability.

## Deliverables

- [ ] Add LLM error events (JSON parse, connection, server)
- [ ] Add batch processing error events
- [ ] Add data loading/parsing error events
- [ ] Add guard/filter evaluation error events
- [ ] Add retry/recovery error events
- [ ] Fix executor error event gap (CRITICAL)
- [x] Fix processor error event gap (CRITICAL) - TemplateVariableError now re-raises

## Critical Gap 1: Processor Template Error Handling (FIXED)

**File:** `agent_actions/processing/processor.py` (lines 239-248)

**Issue:** Processor caught TemplateVariableError as generic Exception and swallowed it, allowing workflow to report success despite template errors.

**Fix Applied (2026-01-22):**
```python
except ConfigurationError:
    # Re-raise immediately to fail the workflow
    raise
except TemplateVariableError:
    # Template errors are code bugs, not data errors
    # Re-raise immediately to fail the workflow
    raise
except Exception as e:
    # Only catch transient/data errors here
    ...
```

**Remaining Work:** Add event firing before re-raise:
```python
except TemplateVariableError as e:
    # TODO: Add event firing (TICKET-018)
    fire_event(TemplateRenderingFailedEvent(
        agent_name=context.agent_name,
        missing_variables=e.missing_variables,
        error_message=str(e),
    ))
    raise
```

## Critical Gap 2: Executor Error Handling

**File:** `agent_actions/workflow/executor.py` (lines 533-571, 683-721)

**Issue:** Executor catches exceptions but **does NOT fire AgentFailedEvent**. It only logs and updates state, relying on coordinator to catch broader exceptions.

**Fix:**
```python
except (OSError, IOError, ValueError, TypeError, KeyError, RuntimeError, AttributeError) as e:
    logger.error("Agent failed: %s", str(e), exc_info=True)

    # ADD THIS:
    fire_event(AgentFailedEvent(
        agent_name=context.agent_name,
        error_type=type(e).__name__,
        error_message=str(e),
    ))

    raise
```

## Template Rendering Error Events

### Files to modify:
- `agent_actions/processing/processor.py` (lines 243-248) - PARTIAL: Re-raise added, event firing needed
- `agent_actions/prompt/service.py` - May have other template rendering errors

### Event types:

```python
class TemplateRenderingFailedEvent(ErrorLevel, BaseEvent):
    """T001 - Template rendering failed due to undefined variables"""
    def __init__(self, agent_name: str, missing_variables: List[str], error_message: str):
        super().__init__(
            message=f"Template for '{agent_name}' references undefined variables: {', '.join(missing_variables)}",
            category="template",
            data={
                "agent_name": agent_name,
                "missing_variables": missing_variables,
                "error_message": error_message,
            },
        )

class TemplateSyntaxError(ErrorLevel, BaseEvent):
    """T002 - Template syntax error"""
    def __init__(self, agent_name: str, error: str):
        super().__init__(
            message=f"Template syntax error in '{agent_name}': {error}",
            category="template",
            data={"agent_name": agent_name, "error": error},
        )
```

### Example (processor.py:243-248):
```python
except TemplateVariableError as e:
    logger.error(f"[{context.agent_name}] Template error: {str(e)}")

    # ADD THIS:
    fire_event(TemplateRenderingFailedEvent(
        agent_name=context.agent_name,
        missing_variables=e.missing_variables,
        error_message=str(e),
    ))

    raise  # Already added - re-raises to fail workflow
```

## LLM Error Events

### Files to modify:
- `agent_actions/llm/providers/openai/client.py`
- `agent_actions/llm/providers/groq/client.py`
- `agent_actions/llm/providers/anthropic/client.py`
- Similar for mistral, gemini, cohere

### Event types:

```python
class LLMJSONParseError(ErrorLevel, BaseEvent):
    """L005 - LLM returned unparseable JSON"""
    def __init__(self, provider: str, model: str, error: str):
        super().__init__(
            message=f"{provider}/{model} returned invalid JSON: {error}",
            category="llm",
            data={"provider": provider, "model": model, "error": error},
        )

class LLMConnectionError(ErrorLevel, BaseEvent):
    """L006 - Connection/timeout error"""
    def __init__(self, provider: str, error: str):
        super().__init__(
            message=f"{provider} connection error: {error}",
            category="llm",
            data={"provider": provider, "error": error},
        )

class LLMServerError(ErrorLevel, BaseEvent):
    """L007 - Server error (5xx)"""
    def __init__(self, provider: str, status_code: int, error: str):
        super().__init__(
            message=f"{provider} server error ({status_code}): {error}",
            category="llm",
            data={"provider": provider, "status_code": status_code, "error": error},
        )
```

### Example gap (groq/client.py:108-118):
```python
except json.JSONDecodeError as e:
    logger.warning("Groq returned invalid JSON...")

    # ADD THIS:
    fire_event(LLMJSONParseError(
        provider="groq",
        model=self.model,
        error=str(e),
    ))

    return [{"raw_response": response_temp, "_parse_error": str(e)}]
```

## Batch Processing Error Events

### Files to modify:
- `agent_actions/llm/batch/services/submission.py` (lines 115-119)
- `agent_actions/workflow/managers/batch.py` (lines 106-123)
- `agent_actions/llm/batch/processing/result_processor.py`

### Event types:

```python
class BatchSubmissionFailedEvent(ErrorLevel, BaseEvent):
    """B004 - Batch submission failed"""

class BatchStatusCheckFailedEvent(WarnLevel, BaseEvent):
    """B005 - Failed to check batch status"""

class BatchResultProcessingFailedEvent(ErrorLevel, BaseEvent):
    """B006 - Failed to process batch results"""

class BatchPartialFailureEvent(WarnLevel, BaseEvent):
    """B007 - Some batch items failed"""
```

## Data Loading/Parsing Error Events

### Files to modify:
- `agent_actions/input/loaders/json.py` (lines 52-69)
- `agent_actions/input/loaders/yaml.py`
- `agent_actions/input/loaders/xml.py`

### Event types:

```python
class DataParsingError(ErrorLevel, BaseEvent):
    """D001 - Data parsing failed"""
    def __init__(self, file_path: str, format: str, error: str):
        super().__init__(
            message=f"Failed to parse {format} from {file_path}: {error}",
            category="data",
            data={"file_path": file_path, "format": format, "error": error},
        )

class DataLoadingError(ErrorLevel, BaseEvent):
    """D002 - Data loading failed"""

class DataValidationError(ErrorLevel, BaseEvent):
    """D003 - Data validation failed"""
```

## Guard/Filter Error Events

### Files to modify:
- `agent_actions/input/preprocessing/filtering/guard_filter.py` (lines 132-150)

### Event types:

```python
class GuardEvaluationTimeoutEvent(WarnLevel, BaseEvent):
    """G001 - Guard evaluation timeout"""
    def __init__(self, guard_clause: str, timeout_seconds: float):
        super().__init__(
            message=f"Guard evaluation timed out after {timeout_seconds}s: {guard_clause}",
            category="guard",
            data={"guard_clause": guard_clause, "timeout_seconds": timeout_seconds},
        )

class GuardEvaluationError(ErrorLevel, BaseEvent):
    """G002 - Guard evaluation error"""
```

### Example gap (guard_filter.py:132-150):
```python
except FutureTimeoutError:
    error_msg = f"Guard condition evaluation timed out..."
    logger.warning(error_msg)

    # ADD THIS:
    fire_event(GuardEvaluationTimeoutEvent(
        guard_clause=agent_config.guard.where,
        timeout_seconds=timeout,
    ))

    return FilterResult(success=False, error=error_msg, ...)
```

## Retry/Recovery Error Events

### Files to modify:
- `agent_actions/processing/recovery/retry.py` (lines 171-186)
- `agent_actions/processing/recovery/reprompt.py`

### Event types:

```python
class RetryExhaustedEvent(WarnLevel, BaseEvent):
    """R001 - Retries exhausted"""
    def __init__(self, attempt: int, reason: str, error: str):
        super().__init__(
            message=f"Retry exhausted after {attempt} attempts: {reason}",
            category="recovery",
            data={"attempt": attempt, "reason": reason, "error": error},
        )

class RepromptValidationFailedEvent(WarnLevel, BaseEvent):
    """R002 - Reprompt validation failed"""

class RecoveryError(ErrorLevel, BaseEvent):
    """R003 - Recovery mechanism failed"""
```

## Priority Order

1. ~~**CRITICAL**: Fix processor.py TemplateVariableError gap~~ ✅ FIXED (2026-01-22)
2. **CRITICAL**: Fix executor.py AgentFailedEvent gap
3. **HIGH**: Add template rendering event firing (processor.py)
4. **HIGH**: LLM error events (JSON parse, connection, server)
5. **HIGH**: Batch processing error events
6. **MEDIUM**: Data loading/parsing errors
7. **MEDIUM**: Guard evaluation errors
8. **MEDIUM**: Retry/recovery errors

## Acceptance Criteria

- [x] Processor re-raises TemplateVariableError (fails workflow)
- [ ] Processor fires TemplateRenderingFailedEvent before re-raise
- [ ] Executor fires AgentFailedEvent on exceptions
- [ ] All LLM errors fire events before logging/wrapping
- [ ] Batch errors have event visibility
- [ ] Data parsing failures fire events
- [ ] Guard evaluation failures fire events
- [ ] Retry exhaustion fires events
- [ ] Tests verify event firing for all error paths
- [ ] Tests verify template errors fail workflow (not swallowed)
