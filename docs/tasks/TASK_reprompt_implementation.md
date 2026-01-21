# Implementation Task: Reprompt Mechanism

## Overview

Implement the **Reprompt** mechanism from RFC_recovery.md for both Online and Batch modes. Reprompt handles application-layer validation failures where LLM responses fail business logic checks (wrong format, forbidden words, missing fields).

## Key Difference from Retry

| Aspect | Retry | Reprompt |
|--------|-------|----------|
| **Trigger** | Network error, missing results | UDF validation failure |
| **Action** | Resubmit same request | Re-send with feedback |
| **Layer** | Transport (infrastructure) | Application (business logic) |
| **Input** | Original prompt (unchanged) | Original prompt + validation feedback |

## RFC Requirements Summary

### Configuration
```yaml
actions:
  - name: classify_book
    reprompt:
      validation: check_no_forbidden_words   # UDF name (required)
      max_attempts: 2                        # Default: 2
      on_exhausted: return_last              # return_last | raise
```

### UDF Contract
```python
from agent_actions import reprompt_validation

@reprompt_validation("Response must not contain the word 'boy'")
def check_no_forbidden_words(response: dict) -> bool:
    """
    Validate LLM response.

    Args:
        response: Parsed LLM response (dict)

    Returns:
        True if valid (pass), False to trigger reprompt
    """
    text = response.get("description", "").lower()
    return "boy" not in text
```

### Feedback Message Format
```
---
Your response failed validation: Response must not contain the word 'boy'

Your response: {"description": "A boy and his dog..."}

Please correct and respond again.
```

### Recovery Metadata
```json
{
  "_recovery": {
    "retry": {...},  // From retry implementation
    "reprompt": {
      "attempts": 2,
      "passed": true,
      "validation": "check_no_forbidden_words"
    }
  }
}
```

## Current Architecture Context

### Existing Infrastructure (From Retry Implementation)

| Component | File | Status |
|-----------|------|--------|
| Recovery Types | `agent_actions/core/types.py` | ✅ RecoveryMetadata, RetryMetadata exist |
| Online Processing | `agent_actions/core/record_processor.py` | ✅ Has retry integration |
| Batch Processing | `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | ✅ Has retry loop |
| Batch Reconciler | `agent_actions/llm_invocation/batch/processing/batch_result_reconciler.py` | ✅ Can track failed validation records |
| Retry Service | `agent_actions/core/retry_service.py` | ✅ Template for RepromptService |

### Integration Points

**Online Mode:**
- `RecordProcessor._execute_llm()` - After LLM execution, before returning response
- Flow: Execute → Retry (if enabled) → **Reprompt (if enabled)** → Return

**Batch Mode:**
- `BatchProcessingService.process_with_recovery()` - After retry loop completes
- Flow: Submit → Retrieve → Retry Loop → **Validation + Reprompt Loop** → Return

## Implementation Steps

### Step 1: Add Reprompt Configuration to Schema

**File:** `agent_actions/configuration/new_format_schema.py`

```python
class RepromptConfig(BaseModel):
    """Reprompt configuration for validation-based recovery."""
    validation: str  # UDF name (required)
    max_attempts: int = 2
    on_exhausted: Literal["return_last", "raise"] = "return_last"

class ActionConfig(BaseModel):
    # ... existing fields ...
    retry: Optional[RetryConfig] = None
    reprompt: Optional[RepromptConfig] = None  # NEW
```

**Validation:**
- `validation` field must be non-empty string
- `max_attempts` must be >= 1
- `on_exhausted` must be valid literal

---

### Step 2: Create UDF Decorator and Registry

**New File:** `agent_actions/core/reprompt_validation.py`

```python
"""
Reprompt validation UDF system.

Provides decorator for registering validation functions and
feedback message management.
"""

from typing import Dict, Callable, Any
import logging

logger = logging.getLogger(__name__)

# Global registry: UDF name -> (function, message)
_VALIDATION_REGISTRY: Dict[str, tuple[Callable[[Dict], bool], str]] = {}


def reprompt_validation(feedback_message: str):
    """
    Decorator to register reprompt validation UDFs.

    Args:
        feedback_message: Message shown to LLM when validation fails

    Returns:
        Decorator function

    Example:
        @reprompt_validation("Response must not contain forbidden words")
        def check_no_forbidden_words(response: dict) -> bool:
            return "forbidden" not in str(response).lower()
    """
    def decorator(func: Callable[[Dict], bool]) -> Callable[[Dict], bool]:
        func_name = func.__name__
        _VALIDATION_REGISTRY[func_name] = (func, feedback_message)
        logger.debug(f"Registered reprompt validation: {func_name}")
        return func
    return decorator


def get_validation_function(name: str) -> tuple[Callable[[Dict], bool], str]:
    """
    Get validation function and feedback message by name.

    Args:
        name: UDF function name

    Returns:
        Tuple of (function, feedback_message)

    Raises:
        ValueError: If UDF not registered
    """
    if name not in _VALIDATION_REGISTRY:
        raise ValueError(
            f"Validation UDF '{name}' not found. "
            f"Available: {list(_VALIDATION_REGISTRY.keys())}"
        )
    return _VALIDATION_REGISTRY[name]


def list_validation_functions() -> list[str]:
    """List all registered validation function names."""
    return list(_VALIDATION_REGISTRY.keys())
```

**Design Notes:**
- Similar to how MCP tools are registered
- Stores both function AND feedback message
- Global registry accessible across modules
- Clear error when UDF not found

---

### Step 3: Create RepromptService

**New File:** `agent_actions/core/reprompt_service.py`

```python
"""
Reprompt service for validation-based recovery.

Validates LLM responses using UDFs and re-executes with feedback
when validation fails.
"""

from dataclasses import dataclass
from typing import Callable, Any, Optional, Tuple
import logging
import json

from .reprompt_validation import get_validation_function

logger = logging.getLogger(__name__)


@dataclass
class RepromptResult:
    """Result of reprompt execution."""
    response: Any
    attempts: int
    passed: bool  # Whether validation ultimately passed
    validation_name: str
    exhausted: bool = False


class RepromptService:
    """
    Service for validating and reprompting LLM responses.

    Wraps LLM execution with validation loop:
    1. Execute LLM
    2. Validate response with UDF
    3. If fails, append feedback and re-execute
    4. Repeat until pass or max_attempts exhausted
    """

    def __init__(self, validation_name: str, max_attempts: int = 2,
                 on_exhausted: str = "return_last"):
        """
        Initialize reprompt service.

        Args:
            validation_name: Name of validation UDF
            max_attempts: Maximum reprompt attempts (default: 2)
            on_exhausted: Behavior when exhausted ("return_last" | "raise")
        """
        self.validation_name = validation_name
        self.max_attempts = max_attempts
        self.on_exhausted = on_exhausted

        # Get validation function and feedback message
        self.validation_func, self.feedback_message = get_validation_function(validation_name)

    def execute(
        self,
        llm_operation: Callable[[], Tuple[Any, bool]],
        original_prompt: str,
        context: str = ""
    ) -> RepromptResult:
        """
        Execute LLM operation with reprompt loop.

        Args:
            llm_operation: Callable that executes LLM (returns (response, executed))
            original_prompt: Original prompt (for appending feedback)
            context: Context string for logging

        Returns:
            RepromptResult with final response and metadata

        Raises:
            RuntimeError: If on_exhausted="raise" and validation exhausted
        """
        attempts = 0
        current_prompt = original_prompt
        last_response = None

        while attempts < self.max_attempts:
            attempts += 1

            # Execute LLM (may return executed=False if guards skip)
            response, executed = llm_operation()

            # If guard skipped execution, return immediately
            if not executed:
                logger.info(f"[{context}] Guard skipped execution, bypassing reprompt")
                return RepromptResult(
                    response=response,
                    attempts=0,  # No validation attempts
                    passed=True,  # Treat as pass
                    validation_name=self.validation_name,
                    exhausted=False
                )

            last_response = response

            # Validate response
            try:
                is_valid = self.validation_func(response)
            except Exception as e:
                logger.error(f"[{context}] Validation UDF error: {e}")
                is_valid = False

            if is_valid:
                logger.info(
                    f"[{context}] Validation passed on attempt {attempts}/{self.max_attempts}"
                )
                return RepromptResult(
                    response=response,
                    attempts=attempts,
                    passed=True,
                    validation_name=self.validation_name,
                    exhausted=False
                )

            # Validation failed
            logger.warning(
                f"[{context}] Validation failed on attempt {attempts}/{self.max_attempts}"
            )

            # Check if exhausted
            if attempts >= self.max_attempts:
                break

            # Prepare feedback message for next attempt
            feedback = self._build_feedback_message(response)
            current_prompt = f"{original_prompt}\n\n{feedback}"

            # TODO: Update llm_operation to use current_prompt for next iteration
            # This requires refactoring how we pass prompts to LLM

        # Exhausted all attempts
        logger.error(
            f"[{context}] Reprompt exhausted after {attempts} attempts "
            f"(validation: {self.validation_name})"
        )

        if self.on_exhausted == "raise":
            raise RuntimeError(
                f"Reprompt validation exhausted after {attempts} attempts "
                f"(validation: {self.validation_name})"
            )

        # on_exhausted = "return_last"
        return RepromptResult(
            response=last_response,
            attempts=attempts,
            passed=False,
            validation_name=self.validation_name,
            exhausted=True
        )

    def _build_feedback_message(self, failed_response: Any) -> str:
        """
        Build feedback message to append to prompt.

        Args:
            failed_response: The response that failed validation

        Returns:
            Formatted feedback message
        """
        # Format response as JSON for clarity
        try:
            response_str = json.dumps(failed_response, indent=2)
        except Exception:
            response_str = str(failed_response)

        return f"""---
Your response failed validation: {self.feedback_message}

Your response: {response_str}

Please correct and respond again."""


def create_reprompt_service_from_config(
    reprompt_config: Optional[dict]
) -> Optional[RepromptService]:
    """
    Create RepromptService from action config.

    Args:
        reprompt_config: Reprompt configuration dict (or None)

    Returns:
        RepromptService instance or None if not enabled
    """
    if not reprompt_config:
        return None

    return RepromptService(
        validation_name=reprompt_config["validation"],
        max_attempts=reprompt_config.get("max_attempts", 2),
        on_exhausted=reprompt_config.get("on_exhausted", "return_last")
    )
```

**Design Challenges:**

1. **Prompt Mutation Problem:**
   - Current `llm_operation()` is a closure over the original prompt
   - We need to update the prompt for each reprompt attempt
   - **Solution Options:**
     - A) Pass `current_prompt` to `llm_operation` (requires signature change)
     - B) Make `llm_operation` accept a prompt parameter
     - C) Store prompt in shared context object that operation reads from

2. **Integration with Retry:**
   - Reprompt wraps LLM execution (which may have retry)
   - Flow: Reprompt Loop { Retry Loop { LLM Call } }
   - Each reprompt attempt gets its own retry protection

---

### Step 4: Extend Recovery Metadata Types

**File:** `agent_actions/core/types.py`

```python
@dataclass
class RepromptMetadata:
    """Metadata for reprompt recovery."""
    attempts: int  # Number of validation attempts
    passed: bool  # Whether validation ultimately passed
    validation: str  # UDF name that triggered reprompt


@dataclass
class RecoveryMetadata:
    """Complete recovery metadata for a record."""
    retry: Optional[RetryMetadata] = None
    reprompt: Optional[RepromptMetadata] = None  # NEW

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output."""
        result = {}
        if self.retry:
            result["retry"] = {
                "attempts": self.retry.attempts,
                "failures": self.retry.failures,
                "succeeded": self.retry.succeeded,
                "reason": self.retry.reason,
                "timestamp": self.retry.timestamp,
            }
        if self.reprompt:  # NEW
            result["reprompt"] = {
                "attempts": self.reprompt.attempts,
                "passed": self.reprompt.passed,
                "validation": self.reprompt.validation,
            }
        return result
```

---

### Step 5: Integrate Reprompt into Online Processing

**File:** `agent_actions/core/record_processor.py`

**Current Flow:**
```
_execute_llm() -> (response, executed, passthrough_fields, recovery_metadata)
  └─> RetryService.execute() [if retry enabled]
      └─> run_dynamic_agent()
```

**New Flow:**
```
_execute_llm() -> (response, executed, passthrough_fields, recovery_metadata)
  └─> RepromptService.execute() [if reprompt enabled]
      └─> RetryService.execute() [if retry enabled]
          └─> run_dynamic_agent()
```

**Implementation:**

Modify `_execute_llm()`:
```python
def _execute_llm(
    self, content: Any, prep_result, context: ProcessingContext
) -> Tuple[Any, bool, Dict, Optional[RecoveryMetadata]]:
    """
    Execute LLM invocation with optional retry and reprompt.

    Flow:
    1. Check for reprompt config
    2. If enabled, wrap LLM call with RepromptService
    3. RepromptService internally calls retry-wrapped LLM
    4. Combine retry + reprompt metadata
    """
    from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent
    from agent_actions.core.reprompt_service import create_reprompt_service_from_config

    tools_path = context.agent_config.get("tools", {}).get("path")

    # Check for reprompt configuration
    reprompt_config = context.agent_config.get("reprompt")
    reprompt_service = create_reprompt_service_from_config(reprompt_config)

    # Check for retry configuration (existing)
    retry_config = context.agent_config.get("retry")
    retry_service = create_retry_service_from_config(retry_config)

    # Build recovery metadata
    recovery_metadata = RecoveryMetadata()

    if reprompt_service:
        # Wrap LLM execution with reprompt
        def llm_with_retry():
            if retry_service:
                # Retry-wrapped LLM call
                retry_result = retry_service.execute(...)
                # Update recovery_metadata.retry
                return retry_result.response
            else:
                # Direct LLM call
                return run_dynamic_agent(...)

        reprompt_result = reprompt_service.execute(
            llm_operation=llm_with_retry,
            original_prompt=prep_result.formatted_prompt,
            context=f"action={context.agent_name}"
        )

        # Update recovery metadata
        if reprompt_result.attempts > 0:
            recovery_metadata.reprompt = RepromptMetadata(
                attempts=reprompt_result.attempts,
                passed=reprompt_result.passed,
                validation=reprompt_result.validation_name
            )

        response, executed = reprompt_result.response
        return response, executed, prep_result.passthrough_fields, recovery_metadata

    else:
        # No reprompt, use existing retry-only flow
        # ... (existing retry code)
```

**Design Notes:**
- Reprompt wraps retry (not the other way around)
- Each reprompt attempt gets independent retry protection
- Metadata tracks both retry and reprompt separately

---

### Step 6: Integrate Reprompt into Batch Processing

**File:** `agent_actions/llm_invocation/batch/services/batch_processing_service.py`

**Current Flow:**
```
process_with_recovery():
  1. Submit initial batch
  2. Retrieve results
  3. Retry loop (for missing records)
  4. Return consolidated results
```

**New Flow:**
```
process_with_recovery():
  1. Submit initial batch
  2. Retrieve results
  3. Retry loop (for missing records)
  4. Reprompt loop (for validation failures)  # NEW
  5. Return consolidated results
```

**Implementation:**

```python
def process_with_recovery(
    self,
    tasks: List[BatchTask],
    batch_name: str,
    output_directory: str,
    retry_config: Optional[Dict] = None,
    reprompt_config: Optional[Dict] = None,  # NEW
    on_exhausted: str = "return_last",
) -> List[BatchResult]:
    """
    Process batch with retry and reprompt recovery.

    Args:
        tasks: Batch tasks
        batch_name: Batch identifier
        output_directory: Output directory
        retry_config: Retry configuration
        reprompt_config: Reprompt configuration (NEW)
        on_exhausted: Exhausted behavior

    Returns:
        List of BatchResult with recovery metadata
    """
    # Phase 1: Submit and retrieve with retry (existing)
    results = self._process_with_retry(...)

    # Phase 2: Validate and reprompt (NEW)
    if reprompt_config:
        results = self._process_with_reprompt(
            results=results,
            original_tasks=tasks,
            batch_name=batch_name,
            output_directory=output_directory,
            reprompt_config=reprompt_config,
            on_exhausted=on_exhausted
        )

    return results


def _process_with_reprompt(
    self,
    results: List[BatchResult],
    original_tasks: List[BatchTask],
    batch_name: str,
    output_directory: str,
    reprompt_config: Dict,
    on_exhausted: str
) -> List[BatchResult]:
    """
    Validate results and reprompt failures.

    Flow:
    1. Validate all results with UDF
    2. Identify failed records
    3. Build reprompt tasks (original prompt + feedback)
    4. Submit as new batch
    5. Consolidate results
    6. Repeat until all pass or max_attempts exhausted
    """
    from agent_actions.core.reprompt_validation import get_validation_function

    validation_name = reprompt_config["validation"]
    max_attempts = reprompt_config.get("max_attempts", 2)
    validation_func, feedback_message = get_validation_function(validation_name)

    # Track per-record reprompt attempts
    reprompt_attempts: Dict[str, int] = {r.custom_id: 0 for r in results}

    # Build lookup: custom_id -> original task
    task_map = {t.custom_id: t for t in original_tasks}

    attempt = 0
    while attempt < max_attempts:
        attempt += 1

        # Validate all results
        failed_results = []
        for result in results:
            if not result.success:
                continue  # Already failed (e.g., retry exhausted)

            try:
                is_valid = validation_func(result.content)
            except Exception as e:
                logger.error(f"Validation UDF error for {result.custom_id}: {e}")
                is_valid = False

            if not is_valid:
                failed_results.append(result)

        if not failed_results:
            logger.info("All records passed validation")
            break

        logger.warning(
            f"Reprompt attempt {attempt}/{max_attempts}: "
            f"{len(failed_results)} records failed validation"
        )

        # Check if this is the last attempt
        if attempt >= max_attempts:
            # Handle exhausted records
            for failed_result in failed_results:
                reprompt_attempts[failed_result.custom_id] = attempt

                if on_exhausted == "raise":
                    raise RuntimeError(
                        f"Reprompt validation exhausted for {failed_result.custom_id}"
                    )

                # on_exhausted = "return_last": keep last response, add metadata
                if not failed_result.recovery_metadata:
                    failed_result.recovery_metadata = RecoveryMetadata()

                failed_result.recovery_metadata.reprompt = RepromptMetadata(
                    attempts=attempt,
                    passed=False,
                    validation=validation_name
                )
            break

        # Build reprompt tasks
        reprompt_tasks = []
        for failed_result in failed_results:
            original_task = task_map[failed_result.custom_id]

            # Build feedback message
            feedback = self._build_reprompt_feedback(
                failed_response=failed_result.content,
                feedback_message=feedback_message
            )

            # Create new task with feedback appended
            reprompt_task = BatchTask(
                custom_id=failed_result.custom_id,
                prompt=original_task.prompt,  # Keep original system prompt
                user_content=f"{original_task.user_content}\n\n{feedback}",
                model_config=original_task.model_config,
                metadata=original_task.metadata
            )
            reprompt_tasks.append(reprompt_task)

            # Track attempts
            reprompt_attempts[failed_result.custom_id] = attempt

        # Submit reprompt batch
        reprompt_batch_name = f"{batch_name}_reprompt_{attempt}"
        reprompt_results = self._submit_and_retrieve_batch(
            tasks=reprompt_tasks,
            batch_name=reprompt_batch_name,
            output_directory=output_directory
        )

        # Consolidate: replace failed results with reprompt results
        result_map = {r.custom_id: r for r in results}
        for reprompt_result in reprompt_results:
            result_map[reprompt_result.custom_id] = reprompt_result

        results = list(result_map.values())

    # Add reprompt metadata to all records that were reprompted
    for result in results:
        if reprompt_attempts[result.custom_id] > 0:
            if not result.recovery_metadata:
                result.recovery_metadata = RecoveryMetadata()

            # Check final validation status
            try:
                passed = validation_func(result.content)
            except Exception:
                passed = False

            result.recovery_metadata.reprompt = RepromptMetadata(
                attempts=reprompt_attempts[result.custom_id],
                passed=passed,
                validation=validation_name
            )

    return results


def _build_reprompt_feedback(self, failed_response: Any, feedback_message: str) -> str:
    """Build feedback message for reprompt."""
    import json
    try:
        response_str = json.dumps(failed_response, indent=2)
    except Exception:
        response_str = str(failed_response)

    return f"""---
Your response failed validation: {feedback_message}

Your response: {response_str}

Please correct and respond again."""
```

**Design Notes:**
- Reprompt loop runs AFTER retry loop completes
- Per-record attempt tracking (independent of retry)
- Only successful records are validated (skip retry-exhausted)
- Reprompt tasks resubmitted as new batches

---

### Step 7: Update Manifest and Status Tracking

**File:** `agent_actions/orchestration/manifest_manager.py`

Add reprompt stats to manifest:
```python
"actions": {
  "classify_genre": {
    "status": "completed",
    "record_count": 10,
    "recovery_stats": {
      "retry_count": 1,
      "reprompt_count": 2  # NEW
    }
  }
}
```

**File:** `agent_actions/orchestration/agent_status.py`

Add reprompt to agent status:
```python
{
  "classify_genre": {
    "status": "completed",
    "recovery": {
      "retried": 1,
      "reprompted": 2,  # NEW
      "failed": 0
    }
  }
}
```

---

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `agent_actions/core/reprompt_validation.py` | UDF decorator and registry |
| Create | `agent_actions/core/reprompt_service.py` | Reprompt orchestration service |
| Modify | `agent_actions/configuration/new_format_schema.py` | Add RepromptConfig |
| Modify | `agent_actions/core/types.py` | Add RepromptMetadata |
| Modify | `agent_actions/core/record_processor.py` | Integrate online reprompt |
| Modify | `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | Integrate batch reprompt |
| Modify | `agent_actions/orchestration/manifest_manager.py` | Add reprompt stats |
| Modify | `agent_actions/orchestration/agent_status.py` | Add reprompt tracking |
| Create | `tests/unit/core/test_reprompt_validation.py` | UDF decorator tests |
| Create | `tests/unit/core/test_reprompt_service.py` | Reprompt service tests |
| Create | `tests/integration/test_reprompt_online.py` | Online integration tests |
| Create | `tests/integration/test_reprompt_batch.py` | Batch integration tests |
| Create | `tests/integration/test_retry_and_reprompt.py` | Combined recovery tests |

---

## Test Strategy (TDD)

### Phase 1: Unit Tests (Write First)

**UDF Registration Tests** (`test_reprompt_validation.py`):
```python
def test_decorator_registers_function()
def test_decorator_stores_message()
def test_get_validation_function_success()
def test_get_validation_function_not_found()
def test_list_validation_functions()
def test_udf_returns_true()
def test_udf_returns_false()
def test_udf_raises_exception()
```

**Reprompt Service Tests** (`test_reprompt_service.py`):
```python
def test_validation_passes_first_attempt()
def test_validation_fails_then_passes()
def test_validation_exhausted_return_last()
def test_validation_exhausted_raise()
def test_feedback_message_format()
def test_reprompt_metadata_recorded()
def test_guard_skips_execution()
def test_create_service_from_config()
```

### Phase 2: Integration Tests

**Online Integration** (`test_reprompt_online.py`):
```python
def test_reprompt_online_no_validation_needed()
def test_reprompt_online_fails_then_passes()
def test_reprompt_online_exhausted_returns_last()
def test_reprompt_online_exhausted_raises()
def test_reprompt_online_metadata_in_output()
```

**Batch Integration** (`test_reprompt_batch.py`):
```python
def test_reprompt_batch_all_pass()
def test_reprompt_batch_partial_failure()
def test_reprompt_batch_consolidates_results()
def test_reprompt_batch_multiple_rounds()
def test_reprompt_batch_exhausted_partial()
def test_reprompt_batch_feedback_per_record()
```

**Combined Recovery** (`test_retry_and_reprompt.py`):
```python
def test_retry_then_reprompt()
def test_reprompt_then_retry()  # Network error during reprompt
def test_both_exhausted()
def test_retry_passes_reprompt_fails()
def test_retry_fails_skips_reprompt()
def test_recovery_metadata_both_present()
```

### Phase 3: End-to-End Tests

**Workflow Integration**:
```python
def test_workflow_reprompt_online_e2e()
def test_workflow_reprompt_batch_e2e()
def test_manifest_records_reprompt_stats()
def test_agent_status_records_reprompt()
def test_output_includes_recovery_metadata()
```

---

## Design Challenges and Solutions

### Challenge 1: Prompt Mutation in Reprompt Loop

**Problem:** Each reprompt attempt needs to modify the prompt (append feedback), but current `llm_operation()` closure captures original prompt.

**Options:**

**Option A: Pass prompt to llm_operation**
```python
def llm_operation(prompt: str) -> Tuple[Any, bool]:
    return run_dynamic_agent(..., formatted_prompt=prompt)

# In RepromptService
current_prompt = original_prompt
while attempts < max_attempts:
    response, executed = llm_operation(current_prompt)
    # ...
    feedback = build_feedback(response)
    current_prompt = f"{original_prompt}\n\n{feedback}"
```

**Option B: Prompt context object**
```python
class PromptContext:
    def __init__(self, base_prompt: str):
        self.base_prompt = base_prompt
        self.feedback_history = []

    def get_current_prompt(self) -> str:
        if not self.feedback_history:
            return self.base_prompt
        return f"{self.base_prompt}\n\n" + "\n\n".join(self.feedback_history)

# In RepromptService
prompt_ctx = PromptContext(original_prompt)
while attempts < max_attempts:
    response = llm_operation()  # Reads from prompt_ctx
    # ...
    prompt_ctx.add_feedback(build_feedback(response))
```

**Recommendation:** Option A (explicit prompt parameter) - clearer, less stateful

---

### Challenge 2: Reprompt + Retry Interaction

**Problem:** Both reprompt and retry wrap LLM execution. Which wraps which?

**Options:**

**Option A: Reprompt wraps Retry**
```
RepromptLoop {
    RetryLoop {
        LLM Call
    }
}
```
- Each reprompt attempt gets independent retry protection
- Network error during reprompt triggers retry
- More resilient

**Option B: Retry wraps Reprompt**
```
RetryLoop {
    RepromptLoop {
        LLM Call
    }
}
```
- Retry operates on entire reprompt sequence
- If reprompt succeeds, retry not invoked
- Less LLM calls

**Recommendation:** Option A - matches RFC expectation ("Network error during reprompt triggers retry")

---

### Challenge 3: Batch Reprompt Context Preservation

**Problem:** When reprompting a batch record, we need:
- Original prompt (system message)
- Original user content
- Previous response (for feedback)
- All tracking IDs (custom_id, target_id, etc.)

**Solution:** Store original tasks in context_map or pass through pipeline

```python
# In batch_processing_service.py
def _process_with_reprompt(self, results, original_tasks, ...):
    # Build lookup
    task_map = {t.custom_id: t for t in original_tasks}

    # For each failed validation
    for failed_result in failed_results:
        original_task = task_map[failed_result.custom_id]

        # Build reprompt task preserving context
        reprompt_task = BatchTask(
            custom_id=original_task.custom_id,  # Preserve
            prompt=original_task.prompt,        # Keep system prompt
            user_content=f"{original_task.user_content}\n\n{feedback}",
            model_config=original_task.model_config,
            metadata=original_task.metadata
        )
```

---

### Challenge 4: Exhausted Record Output Schema

**Problem:** When reprompt exhausted with `on_exhausted=return_last`, the last response failed validation. Should we:
- Return invalid content (may break downstream)
- Return empty content (signals failure clearly)
- Return content + warning flag

**Recommendation:** Return last response + `_recovery.reprompt.passed=false`
- Preserves maximum information
- Downstream can check `passed` flag
- Matches retry behavior (exhausted records get `_recovery` metadata)

---

## Open Questions

### 1. Should reprompt respect retry's on_exhausted?

If retry exhausted with `on_exhausted=raise`, should reprompt even run?

**Options:**
- A) Skip reprompt if retry exhausted (current implementation)
- B) Run reprompt anyway (maybe validation can pass on failed content?)

**Recommendation:** A - failed transport means no valid content to validate

---

### 2. Should we limit total cost (retry + reprompt)?

**Problem:** `max_attempts: 3` retry + `max_attempts: 2` reprompt = 6 total LLM calls

**Options:**
- A) Independent limits (current)
- B) Global `max_total_attempts` across both
- C) Cost budget (max tokens/dollars)

**Recommendation:** A for v1, document cost implications

---

### 3. Should reprompt support multiple UDFs?

**Current:** Single UDF per action
```yaml
reprompt:
  validation: check_format
```

**Future:** Chain of validators?
```yaml
reprompt:
  validation:
    - check_format
    - check_no_forbidden_words
    - check_business_rules
```

**Recommendation:** Single UDF for v1, design extensibility for v2

---

### 4. How to handle non-dict responses?

**Problem:** UDF contract expects `response: dict`, but LLM might return string or list

**Options:**
- A) Wrap non-dict in `{"_raw": response}`
- B) Require schema enforcement (JSON mode)
- C) Support multiple UDF signatures: `(dict)`, `(str)`, `(Any)`

**Recommendation:** A - consistent with guard evaluation pattern

---

## Implementation Order

1. **Phase 1: Foundation** (TDD)
   - Create `reprompt_validation.py` with decorator and registry
   - Write unit tests for decorator system
   - Verify UDF registration works

2. **Phase 2: Core Service** (TDD)
   - Create `reprompt_service.py`
   - Write unit tests for validation loop
   - Verify feedback message generation

3. **Phase 3: Schema** (TDD)
   - Add RepromptConfig to schema
   - Add RepromptMetadata to types
   - Write validation tests

4. **Phase 4: Online Integration** (TDD)
   - Modify RecordProcessor._execute_llm()
   - Write integration tests
   - Verify metadata in output

5. **Phase 5: Batch Integration** (TDD)
   - Modify BatchProcessingService
   - Write integration tests
   - Verify batch consolidation

6. **Phase 6: Tracking** (Final)
   - Update manifest and status tracking
   - Write end-to-end tests
   - Verify recovery stats

---

## Success Criteria

### Functional
- [ ] UDF decorator registers validation functions
- [ ] Online reprompt validates and re-executes
- [ ] Batch reprompt resubmits failed records
- [ ] Feedback message appended correctly
- [ ] Recovery metadata tracked in `_recovery.reprompt`
- [ ] `on_exhausted` behavior respected
- [ ] Works with retry (combined recovery)

### Performance
- [ ] Only failed records reprompted (not entire batch)
- [ ] Reprompt attempts tracked per-record
- [ ] No unnecessary LLM calls

### Testing
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] End-to-end workflow tests pass
- [ ] Edge cases covered (exhausted, combined recovery)

### Documentation
- [ ] UDF decorator usage documented
- [ ] Configuration schema updated
- [ ] Recovery metadata structure documented
- [ ] Examples added to docs

---

## Rollout Plan

### Stage 1: Internal Testing
- Implement with sample UDFs
- Test on small datasets
- Verify cost implications

### Stage 2: Beta Release
- Document UDF contract
- Add examples to docs
- Gather feedback on UDF API

### Stage 3: Production
- Full test coverage
- Performance benchmarks
- Migration guide from manual validation

---

## Future Enhancements (Out of Scope)

1. **Multiple validators per action** (chain of UDFs)
2. **Conditional reprompt** (only for specific content types)
3. **Custom feedback templates** (beyond default message)
4. **Reprompt strategies** (incremental hints vs full feedback)
5. **Cost tracking** (reprompt-specific token usage)
6. **Exhausted handlers** (dead letter queue, human review)

---

## References

- **RFC:** `/Users/muizz/Documents/codeshop/agent-actions/docs/specs/RFC_recovery.md`
- **Retry Implementation:** PR #718 (feature-recovery branch)
- **Related Types:** `agent_actions/core/types.py` (RecoveryMetadata)
- **Retry Service:** `agent_actions/core/retry_service.py` (template for RepromptService)
