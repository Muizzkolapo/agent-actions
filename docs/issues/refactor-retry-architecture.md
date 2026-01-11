# Refactor: Consolidate Retry/Recovery Architecture

## Summary

The current retry and recovery implementation is fragmented across multiple code paths, making it difficult to add new features, fix bugs consistently, and reason about the system's behavior. This issue proposes a refactoring to consolidate the retry architecture into a unified, composable design.

## Problem Statement

While implementing retry metadata propagation (tracking `was_retried`, `retry_attempts`, `error_type`, `error_message`, `exhausted` through the call chain), several architectural issues became apparent:

### 1. Duplicate Processing Paths

There are two separate processing paths that both need identical retry/exhausted handling:

- `staging_processor.py` → `StagingProcessor.staging_dynamic_creator()`
- `target_content_processor.py` → `TargetContentProcessor._process_single_item()` / `_process_single_item_async()`

When adding exhausted failure record creation, the fix was initially only applied to `target_content_processor.py`, leaving `staging_processor.py` silently dropping failed records. This is a recurring pattern where changes must be applied to multiple locations.

**Files with duplicate logic:**
```
agent_actions/preprocessing/staging/staging_processor.py:155-184
agent_actions/prompt_generation/target_content_processor.py:450-480 (async)
agent_actions/prompt_generation/target_content_processor.py:696-726 (sync)
```

### 2. Fragile Tuple-Based Return Values

The call chain passes retry state as increasingly long tuples:

```python
# client_invocation_service.py
return InvocationResult(data, was_retried, retry_attempts, error_type, error_message, exhausted)

# agent_builder.py
return (result.data, result.was_retried, result.retry_attempts, result.error_type, result.error_message, result.exhausted)

# processor_helpers.py
return (response, True, was_retried, retry_attempts, error_type, error_message, exhausted)

# data_generator.py
return (response, executed, passthrough_fields, was_retried, retry_attempts, error_type, error_message, exhausted)
```

**Problems:**
- Adding a new field requires changes to 6+ files
- Easy to mix up positional arguments
- No type safety for tuple unpacking
- Different functions return different tuple shapes (6, 7, or 8 elements)

### 3. Scattered Configuration Inheritance

The `recovery` config field wasn't being inherited from workflow `defaults` to individual actions because it wasn't in `SIMPLE_CONFIG_FIELDS`. This is a hidden configuration system that's easy to miss:

```python
# config_field_definitions.py
SIMPLE_CONFIG_FIELDS = {
    "json_mode": True,
    "granularity": "Record",
    # ... many fields ...
    "recovery": None,  # Had to add this manually
    "retry": None,     # Had to add this manually
}
```

### 4. Inconsistent Exhaustion Handling

Different code paths handle retry exhaustion differently:
- `client_invocation_service.py` returns empty list `[]` for `on_exhausted: continue`
- `staging_processor.py` was silently returning empty results (bug)
- `target_content_processor.py` creates failure records with `_failed: true`
- `batch_retry_orchestrator.py` has its own exhaustion logic

### 5. No Central "Result" Type

There's no unified type for "the result of processing a record" that includes both the data and all metadata about how it was produced. Instead, metadata is attached ad-hoc at various points.

## Proposed Solution

### Phase 1: Introduce `ProcessingResult` Dataclass

Create a unified result type that flows through the entire call chain:

```python
# agent_actions/core/processing_result.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class RetryState:
    """Immutable retry state for a single record."""
    was_retried: bool = False
    retry_attempts: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    exhausted: bool = False

    def to_metadata(self) -> Dict[str, Any]:
        """Convert to _retry_metadata dict format."""
        return {
            "was_retried": self.was_retried,
            "retry_attempts": self.retry_attempts,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "exhausted": self.exhausted,
        }

@dataclass
class ProcessingResult:
    """Result of processing a single record through an action."""
    data: List[Dict[str, Any]]
    executed: bool = True
    retry_state: RetryState = field(default_factory=RetryState)
    passthrough_fields: Dict[str, Any] = field(default_factory=dict)
    source_guid: Optional[str] = None

    @property
    def is_failure(self) -> bool:
        """Check if this result represents a failed record."""
        return self.retry_state.exhausted and not self.data

    def create_failure_record(self, idx: int) -> Dict[str, Any]:
        """Create a failure record with proper metadata."""
        # Centralized failure record creation
        ...
```

### Phase 2: Consolidate Processing Paths

Extract the common processing logic into a shared base:

```python
# agent_actions/core/record_processor.py
class RecordProcessor:
    """Base class for record processing with retry handling."""

    def process_record(
        self,
        record: Dict[str, Any],
        agent_config: Dict[str, Any],
        ...
    ) -> ProcessingResult:
        """Process a single record with unified retry handling."""
        result = self._invoke_agent(record, agent_config)

        if result.is_failure:
            return self._handle_failure(result, record, agent_config)

        return self._finalize_success(result, record, agent_config)

    def _handle_failure(self, result: ProcessingResult, ...) -> ProcessingResult:
        """Create failure record - single implementation used by all paths."""
        ...
```

Then have both processors delegate to this:

```python
# staging_processor.py
class StagingProcessor(RecordProcessor):
    def staging_dynamic_creator(self, context_data, ...):
        result = self.process_record(context_data, self.agent_config)
        # Staging-specific post-processing only
        ...

# target_content_processor.py
class TargetContentProcessor(RecordProcessor):
    def _process_single_item(self, item, ...):
        result = self.process_record(item, self.agent_config)
        # Target-specific post-processing only
        ...
```

### Phase 3: Explicit Configuration Registry

Replace the implicit `SIMPLE_CONFIG_FIELDS` dict with an explicit registration system:

```python
# agent_actions/configuration/config_registry.py
from enum import Enum, auto

class ConfigInheritance(Enum):
    INHERIT = auto()      # Inherit from defaults
    NO_INHERIT = auto()   # Action-level only
    MERGE = auto()        # Deep merge with defaults

@dataclass
class ConfigFieldSpec:
    name: str
    default: Any
    inheritance: ConfigInheritance
    validator: Optional[Callable] = None

CONFIG_REGISTRY = ConfigRegistry()

# Explicit registration with clear inheritance behavior
CONFIG_REGISTRY.register(
    ConfigFieldSpec("recovery", default=None, inheritance=ConfigInheritance.MERGE)
)
CONFIG_REGISTRY.register(
    ConfigFieldSpec("retry", default=True, inheritance=ConfigInheritance.INHERIT)
)
```

### Phase 4: Recovery Strategy Pattern

Replace scattered exhaustion handling with a strategy pattern:

```python
# agent_actions/recovery/exhaustion_strategy.py
from abc import ABC, abstractmethod

class ExhaustionStrategy(ABC):
    @abstractmethod
    def handle(self, result: ProcessingResult, context: Dict) -> ProcessingResult:
        """Handle exhausted retries."""
        pass

class ContinueStrategy(ExhaustionStrategy):
    """Create failure record and continue."""
    def handle(self, result: ProcessingResult, context: Dict) -> ProcessingResult:
        return result.create_failure_record(context["idx"])

class FailStrategy(ExhaustionStrategy):
    """Raise error to stop workflow."""
    def handle(self, result: ProcessingResult, context: Dict) -> ProcessingResult:
        raise ProcessingError(f"Retries exhausted: {result.retry_state.error_message}")
```

## Migration Path

1. **Phase 1** (Low risk): Add `ProcessingResult` and `RetryState` dataclasses alongside existing code
2. **Phase 2** (Medium risk): Migrate `staging_processor.py` and `target_content_processor.py` to use shared base
3. **Phase 3** (Low risk): Add `ConfigRegistry`, deprecate `SIMPLE_CONFIG_FIELDS`
4. **Phase 4** (Medium risk): Consolidate exhaustion handling into strategies

Each phase can be done independently and tested in isolation.

## Success Criteria

- [ ] Adding a new retry metadata field requires changes to ≤2 files (dataclass + migration)
- [ ] No duplicate failure record creation logic
- [ ] Configuration inheritance is explicit and documented
- [ ] All processing paths (staging, target, async, sync) share the same exhaustion handling
- [ ] Type hints provide IDE support for result types

## Files Affected

**Core changes:**
- `agent_actions/core/processing_result.py` (new)
- `agent_actions/core/record_processor.py` (new)
- `agent_actions/configuration/config_registry.py` (new)
- `agent_actions/recovery/exhaustion_strategy.py` (new)

**Refactored:**
- `agent_actions/preprocessing/staging/staging_processor.py`
- `agent_actions/prompt_generation/target_content_processor.py`
- `agent_actions/llm_invocation/realtime/services/client_invocation_service.py`
- `agent_actions/llm_invocation/realtime/agent_builder.py`
- `agent_actions/utilities/processor/processor_helpers.py`
- `agent_actions/prompt_generation/data_generator.py`
- `agent_actions/response_processing/config_field_definitions.py`

## Estimated Effort

- Phase 1: 1-2 days
- Phase 2: 2-3 days
- Phase 3: 1 day
- Phase 4: 1-2 days
- Testing & documentation: 2 days

**Total: ~8-10 days**

## Related Issues

- Retry metadata not propagating correctly (fixed ad-hoc)
- `dead_letter` inconsistency between online/batch (removed)
- `retry_tracker.py` removal (completed)
- Config inheritance bugs with `recovery` field (fixed ad-hoc)

## Labels

`refactoring`, `architecture`, `tech-debt`, `retry`, `recovery`
