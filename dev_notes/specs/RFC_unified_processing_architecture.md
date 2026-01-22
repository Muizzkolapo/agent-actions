# RFC: Unified Record Processing Architecture

**Status**: Draft
**Author**: Architecture Review
**Date**: 2025-01-12

## Executive Summary

Replace the duplicate `StagingProcessor` and `TargetContentProcessor` paths with a single `RecordProcessor` that handles all record processing uniformly. Since we're in development with no users, we can make breaking changes freely.

## Problem Statement

We have two nearly-identical processing paths:

```
StagingProcessor.staging_dynamic_creator()     → First-stage processing
TargetContentProcessor._process_single_item()  → Subsequent-stage processing
```

Both do:
- Guard evaluation
- Prompt preparation
- LLM invocation via `run_dynamic_agent()`
- Response transformation
- Lineage tracking
- Metadata enrichment

The differences are superficial:
- Input format (raw vs structured)
- Return type (tuple vs list)
- Lineage method name (`add_context_lineage_tracking` vs `add_lineage_tracking`)

## Proposed Solution

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     RecordProcessor                          │
│                                                              │
│   process(item, context) → ProcessingResult                  │
│                                                              │
│   Handles ALL processing:                                    │
│   - First-stage (raw input)                                  │
│   - Subsequent-stage (structured input)                      │
│   - Online mode                                              │
│   - Batch mode                                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   ProcessingResult                           │
│                                                              │
│   data: List[Dict]              # Processed records          │
│   status: ProcessingStatus      # success/skipped/failed     │
│   source_guid: str              # Input record identifier    │
│   node_id: str                  # Generated node ID          │
│   source_snapshot: Dict         # Original input (optional)  │
│   retry_state: RetryState       # Retry metadata             │
│   passthrough_fields: Dict      # Fields to carry forward    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  EnrichmentPipeline                          │
│                                                              │
│   LineageEnricher → MetadataEnricher → LoopIdEnricher →     │
│   PassthroughEnricher → RequiredFieldsEnricher               │
└─────────────────────────────────────────────────────────────┘
```

### Core Types

```python
# agent_actions/core/types.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ProcessingStatus(Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"      # Guard skip behavior
    FILTERED = "filtered"    # Guard filter behavior
    FAILED = "failed"
    EXHAUSTED = "exhausted"  # Retries exhausted


class ProcessingMode(Enum):
    ONLINE = "online"
    BATCH = "batch"


@dataclass
class RetryState:
    attempts: int = 0
    last_error: Optional[str] = None
    exhausted: bool = False


@dataclass
class ProcessingResult:
    """Single result type for all processing."""

    status: ProcessingStatus
    data: List[Dict[str, Any]] = field(default_factory=list)

    # Identity
    source_guid: Optional[str] = None
    node_id: Optional[str] = None

    # For first-stage: preserve original input for source saving
    source_snapshot: Optional[Dict[str, Any]] = None

    # Execution state
    executed: bool = True
    skip_reason: Optional[str] = None

    # Passthrough
    passthrough_fields: Dict[str, Any] = field(default_factory=dict)

    # Error handling
    error: Optional[str] = None
    retry_state: RetryState = field(default_factory=RetryState)

    # LLM response (for metadata extraction)
    raw_response: Optional[Any] = None

    @classmethod
    def success(cls, data: List[Dict], **kwargs) -> "ProcessingResult":
        return cls(status=ProcessingStatus.SUCCESS, data=data, executed=True, **kwargs)

    @classmethod
    def skipped(cls, passthrough_data: Any, reason: str, **kwargs) -> "ProcessingResult":
        data = [passthrough_data] if not isinstance(passthrough_data, list) else passthrough_data
        return cls(status=ProcessingStatus.SKIPPED, data=data, executed=False, skip_reason=reason, **kwargs)

    @classmethod
    def filtered(cls, **kwargs) -> "ProcessingResult":
        return cls(status=ProcessingStatus.FILTERED, data=[], executed=False, **kwargs)

    @classmethod
    def failed(cls, error: str, **kwargs) -> "ProcessingResult":
        return cls(status=ProcessingStatus.FAILED, data=[], executed=False, error=error, **kwargs)


@dataclass
class ProcessingContext:
    """All context needed for processing."""

    agent_config: Dict[str, Any]
    agent_name: str
    mode: ProcessingMode = ProcessingMode.ONLINE

    # Is this first-stage (raw input) or subsequent-stage (structured input)?
    is_first_stage: bool = False

    # Source data for lookups
    source_data: List[Dict[str, Any]] = field(default_factory=list)

    # File context
    file_path: Optional[str] = None
    output_directory: Optional[str] = None

    # Loop context for {loop.*} references
    loop_context: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None

    # Current record position (for loop correlation)
    record_index: int = 0

    @property
    def action_name(self) -> str:
        return self.agent_config.get("agent_type", self.agent_name)
```

### RecordProcessor

```python
# agent_actions/core/record_processor.py

from typing import Dict, List, Optional, Tuple
from .types import ProcessingContext, ProcessingResult, ProcessingStatus


class RecordProcessor:
    """
    Single processor for all record processing.

    Replaces both StagingProcessor and TargetContentProcessor._process_single_item().
    """

    def __init__(self, agent_config: Dict, agent_name: str):
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.enrichment_pipeline = EnrichmentPipeline()

    def process(self, item: Dict, context: ProcessingContext) -> ProcessingResult:
        """
        Process a single record.

        Works for both first-stage (raw input) and subsequent-stage (structured input).
        """
        # Step 1: Normalize input
        content, source_guid, source_snapshot = self._normalize_input(item, context)

        # Step 2: Early guard evaluation
        guard_result = self._evaluate_guard(content, source_guid, context)
        if guard_result is not None:
            return guard_result

        # Step 3: Get source content for prompt
        source_content = self._get_source_content(source_guid, context)

        # Step 4: Prepare prompt
        prep_result = self._prepare_prompt(content, source_content, context)

        # Step 5: Execute LLM
        response, executed, passthrough_fields = self._execute_llm(
            content, prep_result, context
        )

        # Step 6: Handle non-execution (guard evaluated to skip in LLM layer)
        if not executed:
            if response is None:
                return ProcessingResult.filtered(source_guid=source_guid)
            return ProcessingResult.skipped(
                passthrough_data=response,
                reason="guard_skip",
                source_guid=source_guid,
                passthrough_fields=passthrough_fields,
                source_snapshot=source_snapshot,
            )

        # Step 7: Transform response
        transformed = self._transform_response(
            response, content, source_guid, passthrough_fields, context
        )

        # Step 8: Create result
        result = ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
        )

        # Step 9: Enrich (lineage, metadata, loop IDs, etc.)
        return self.enrichment_pipeline.enrich(result, context)

    def process_batch(
        self,
        items: List[Dict],
        context: ProcessingContext
    ) -> List[ProcessingResult]:
        """Process multiple records."""
        results = []
        for idx, item in enumerate(items):
            ctx = ProcessingContext(
                agent_config=context.agent_config,
                agent_name=context.agent_name,
                mode=context.mode,
                is_first_stage=context.is_first_stage,
                source_data=context.source_data,
                file_path=context.file_path,
                output_directory=context.output_directory,
                loop_context=context.loop_context,
                workflow_metadata=context.workflow_metadata,
                record_index=idx,
            )
            results.append(self.process(item, ctx))
        return results

    def _normalize_input(
        self,
        item: Dict,
        context: ProcessingContext
    ) -> Tuple[Any, str, Optional[Dict]]:
        """
        Normalize input format.

        First-stage: raw input → generate source_guid, preserve snapshot
        Subsequent-stage: structured {content, source_guid} → extract fields
        """
        if context.is_first_stage:
            # Raw input - generate source_guid
            from agent_actions.utilities.id_generation import IDGenerator
            source_guid = IDGenerator.generate_deterministic_source_guid(item)
            return item, source_guid, item  # content, guid, snapshot
        else:
            # Structured input
            content = item.get("content", item)
            source_guid = item.get("source_guid")
            return content, source_guid, None

    def _evaluate_guard(
        self,
        content: Any,
        source_guid: str,
        context: ProcessingContext
    ) -> Optional[ProcessingResult]:
        """Evaluate guard conditions early."""
        from agent_actions.utilities.processor.processor_helpers import evaluate_guard_condition

        guard_config = context.agent_config.get("guard")
        conditional = context.agent_config.get("conditional_clause")

        if not guard_config and not conditional:
            return None

        eval_context = content if isinstance(content, dict) else {"_raw": content}
        should_execute, behavior = evaluate_guard_condition(
            context.agent_config, eval_context
        )

        if should_execute:
            return None

        if behavior == "filter":
            return ProcessingResult.filtered(source_guid=source_guid)

        return ProcessingResult.skipped(
            passthrough_data=content,
            reason=f"guard_{behavior}",
            source_guid=source_guid,
        )

    def _get_source_content(
        self,
        source_guid: str,
        context: ProcessingContext
    ) -> Optional[Any]:
        """Get source content for prompt preparation."""
        if not context.source_data:
            return None
        from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
        return DataTransformer.get_content_by_source_guid(context.source_data, source_guid)

    def _prepare_prompt(
        self,
        content: Any,
        source_content: Any,
        context: ProcessingContext
    ) -> "PromptPreparationResult":
        """Prepare prompt using shared service."""
        from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService

        return PromptPreparationService.prepare_prompt_with_context(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            contents=content if isinstance(content, dict) else {},
            mode="realtime" if context.mode.value == "online" else "batch",
            source_content=source_content,
            loop_context=context.loop_context,
            workflow_metadata=context.workflow_metadata,
        )

    def _execute_llm(
        self,
        content: Any,
        prep_result: "PromptPreparationResult",
        context: ProcessingContext
    ) -> Tuple[Any, bool, Dict]:
        """Execute LLM invocation."""
        from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent

        tools_path = context.agent_config.get("tools", {}).get("path")

        response, executed = run_dynamic_agent(
            context.agent_config,
            context.agent_name,
            content,
            prep_result.formatted_prompt,
            tools_path=tools_path,
        )

        return response, executed, prep_result.passthrough_fields

    def _transform_response(
        self,
        response: Any,
        content: Any,
        source_guid: str,
        passthrough_fields: Dict,
        context: ProcessingContext,
    ) -> List[Dict]:
        """Transform LLM response to output format."""
        from agent_actions.utilities.processor.processor_helpers import transform_with_passthrough

        return transform_with_passthrough(
            response, content, source_guid, context.agent_config
        )
```

### EnrichmentPipeline

```python
# agent_actions/core/enrichment.py

from abc import ABC, abstractmethod
from typing import List
from .types import ProcessingContext, ProcessingResult, ProcessingStatus


class Enricher(ABC):
    @abstractmethod
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        pass


class LineageEnricher(Enricher):
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utilities.lineage import LineageBuilder
        from agent_actions.utilities.id_generation import IDGenerator

        base_node_id = IDGenerator.generate_node_id(context.action_name)

        for i, item in enumerate(result.data):
            node_id = f"{base_node_id}_{i}" if len(result.data) > 1 else base_node_id
            # Use unified lineage method
            item["lineage"] = LineageBuilder.build_lineage(
                {"source_guid": result.source_guid},
                node_id
            )
            item["node_id"] = node_id

        result.node_id = base_node_id
        return result


class MetadataEnricher(Enricher):
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        if not result.executed:
            return result

        from agent_actions.utilities.metadata import MetadataExtractor
        from agent_actions.utilities.field_management import FieldManager

        response_metadata = MetadataExtractor.extract_from_response(
            response=result.raw_response,
            agent_config=context.agent_config,
        )

        for item in result.data:
            FieldManager.add_metadata(item, metadata=response_metadata.to_dict())

        return result


class LoopIdEnricher(Enricher):
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utilities.correlation import VersionIdGenerator

        for i, item in enumerate(result.data):
            result.data[i] = VersionIdGenerator.add_version_correlation_id(
                item, context.agent_config, record_index=context.record_index
            )

        return result


class PassthroughEnricher(Enricher):
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        if not result.passthrough_fields:
            return result

        for item in result.data:
            content = item.get("content", item)
            if isinstance(content, dict):
                content.update(result.passthrough_fields)

        return result


class RequiredFieldsEnricher(Enricher):
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utilities.field_management import FieldManager

        for item in result.data:
            FieldManager().ensure_required_fields(
                item,
                result.source_guid,
                0  # idx - consider if this needs to come from context
            )

        return result


class EnrichmentPipeline:
    def __init__(self, enrichers: List[Enricher] = None):
        self.enrichers = enrichers or [
            LineageEnricher(),
            MetadataEnricher(),
            LoopIdEnricher(),
            PassthroughEnricher(),
            RequiredFieldsEnricher(),
        ]

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        for enricher in self.enrichers:
            result = enricher.enrich(result, context)
        return result
```

### ConfigRegistry

```python
# agent_actions/core/config.py

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type
from enum import Enum


class Inheritance(Enum):
    STANDARD = "standard"      # action > defaults > hardcoded
    ACTION_ONLY = "action"     # Only from action
    REQUIRED = "required"      # Must be provided


@dataclass
class ConfigField:
    name: str
    default: Any = None
    inheritance: Inheritance = Inheritance.STANDARD
    type_hint: Optional[Type] = None
    description: str = ""
    validator: Optional[Callable[[Any], bool]] = None

    def resolve(self, action: Dict, defaults: Dict) -> Any:
        if self.inheritance == Inheritance.REQUIRED:
            if self.name in action:
                return action[self.name]
            if self.name in defaults:
                return defaults[self.name]
            raise ValueError(f"Required config field '{self.name}' not provided")

        if self.inheritance == Inheritance.ACTION_ONLY:
            return action.get(self.name, self.default)

        return action.get(self.name, defaults.get(self.name, self.default))


class ConfigRegistry:
    _fields: Dict[str, ConfigField] = {}

    @classmethod
    def register(cls, field: ConfigField) -> None:
        cls._fields[field.name] = field

    @classmethod
    def resolve_all(cls, action: Dict, defaults: Dict) -> Dict[str, Any]:
        return {name: field.resolve(action, defaults) for name, field in cls._fields.items()}


# Register all fields
def _init_fields():
    fields = [
        ConfigField("model_vendor", inheritance=Inheritance.REQUIRED, description="LLM vendor"),
        ConfigField("model_name", inheritance=Inheritance.REQUIRED, description="Model identifier"),
        ConfigField("api_key", description="API key"),
        ConfigField("base_url", description="Base URL for self-hosted models"),
        ConfigField("run_mode", default="online", description="online or batch"),
        ConfigField("is_operational", default=True, type_hint=bool),
        ConfigField("json_mode", default=True, type_hint=bool),
        ConfigField("prompt_debug", default=False, type_hint=bool),
        ConfigField("output_field", default="raw_response"),
        ConfigField("side_output", default=False, type_hint=bool),
        ConfigField("reprompt", default=False, type_hint=bool),
        ConfigField("constraints", default=[]),
        ConfigField("recovery", default={}, description="Recovery config for failures"),
        ConfigField("retry", default={"max_attempts": 3}, description="Retry config"),
    ]
    for f in fields:
        ConfigRegistry.register(f)

_init_fields()
```

## Usage Examples

### First-stage processing (replaces StagingProcessor)

```python
# In StagingContentLoader or ContentGenerator

processor = RecordProcessor(agent_config, agent_name)
context = ProcessingContext(
    agent_config=agent_config,
    agent_name=agent_name,
    is_first_stage=True,  # This is the key flag
    file_path=file_path,
)

results = processor.process_batch(raw_items, context)

# Extract data and source snapshots
data_chunk = []
src_text = []
for result in results:
    data_chunk.extend(result.data)
    if result.source_snapshot:
        src_text.append(result.source_snapshot)
```

### Subsequent-stage processing (replaces TargetContentProcessor._process_single_item)

```python
# In TargetContentProcessor

processor = RecordProcessor(agent_config, agent_name)
context = ProcessingContext(
    agent_config=agent_config,
    agent_name=agent_name,
    is_first_stage=False,
    source_data=source_data,
    file_path=file_path,
)

results = processor.process_batch(structured_items, context)
processed_data = [item for result in results for item in result.data]
```

### Batch mode

```python
# Same processor, different mode
context = ProcessingContext(
    agent_config=agent_config,
    agent_name=agent_name,
    mode=ProcessingMode.BATCH,
    is_first_stage=False,
)
```

## Files to Delete

After migration:

```
DELETE: agent_actions/preprocessing/staging/staging_processor.py
DELETE: agent_actions/prompt_generation/content_generator.py (merge into RecordProcessor usage)
SIMPLIFY: agent_actions/prompt_generation/target_content_processor.py (use RecordProcessor)
SIMPLIFY: agent_actions/preprocessing/staging/staging_content.py (use RecordProcessor)
DELETE: agent_actions/response_processing/config_field_definitions.py (replaced by ConfigRegistry)
```

## Files to Create

```
CREATE: agent_actions/core/__init__.py
CREATE: agent_actions/core/types.py
CREATE: agent_actions/core/record_processor.py
CREATE: agent_actions/core/enrichment.py
CREATE: agent_actions/core/config.py
```

## Migration Steps

1. Create `agent_actions/core/` with new types
2. Implement `RecordProcessor`
3. Implement `EnrichmentPipeline`
4. Update `StagingContentLoader` to use `RecordProcessor` with `is_first_stage=True`
5. Update `TargetContentProcessor` to use `RecordProcessor` with `is_first_stage=False`
6. Delete old code
7. Update tests

## Key Simplifications

| Before | After |
|--------|-------|
| 2 processing paths | 1 processing path |
| 3 lineage methods | 1 lineage method |
| Tuple returns | `ProcessingResult` dataclass |
| Implicit config inheritance | `ConfigRegistry` with explicit fields |
| `SIMPLE_CONFIG_FIELDS` dict | Typed `ConfigField` objects |
| Separate staging/target enrichment | Single `EnrichmentPipeline` |

## Open Questions

1. **Batch mode integration**: Should `BatchResultProcessor` also use `RecordProcessor`, or remain separate since it processes LLM responses (not invokes LLMs)?

2. **Async support**: Should `RecordProcessor.process()` have an async variant, or handle async at a higher level?

3. **Error handling strategy**: Should processing errors return `ProcessingResult.failed()` or raise exceptions? Current code mixes both approaches.





# TDD Test Plan: Unified Record Processing

**RFC Reference**: `docs/rfcs/unified-record-processing.md`

This document lists all tests that must be created BEFORE implementing the unified `RecordProcessor`. Tests are organized by component and behavior.

## Test File Structure

```
tests/
├── core/
│   ├── test_processing_result.py       # ProcessingResult dataclass
│   ├── test_processing_context.py      # ProcessingContext dataclass
│   ├── test_record_processor.py        # RecordProcessor core logic
│   ├── test_enrichment_pipeline.py     # EnrichmentPipeline and enrichers
│   └── test_config_registry.py         # ConfigRegistry and ConfigField
└── integration/
    ├── test_first_stage_processing.py  # End-to-end first-stage (staging)
    ├── test_subsequent_stage_processing.py  # End-to-end subsequent-stage
    └── test_processing_parity.py       # Verify old vs new produce same output
```

---

## 1. ProcessingResult Tests

**File**: `tests/core/test_processing_result.py`

### 1.1 Factory Methods

```python
class TestProcessingResultFactories:
    def test_success_creates_result_with_success_status(self):
        """ProcessingResult.success() sets status=SUCCESS and executed=True"""

    def test_success_accepts_data_list(self):
        """ProcessingResult.success() stores data list correctly"""

    def test_success_accepts_kwargs(self):
        """ProcessingResult.success() passes through source_guid, node_id, etc."""

    def test_skipped_creates_result_with_skipped_status(self):
        """ProcessingResult.skipped() sets status=SKIPPED and executed=False"""

    def test_skipped_wraps_non_list_data_in_list(self):
        """ProcessingResult.skipped() converts single dict to [dict]"""

    def test_skipped_preserves_list_data(self):
        """ProcessingResult.skipped() keeps list data as-is"""

    def test_skipped_stores_reason(self):
        """ProcessingResult.skipped() stores skip_reason correctly"""

    def test_filtered_creates_empty_result(self):
        """ProcessingResult.filtered() sets status=FILTERED, data=[], executed=False"""

    def test_failed_creates_result_with_error(self):
        """ProcessingResult.failed() sets status=FAILED and stores error message"""

    def test_failed_accepts_retry_state(self):
        """ProcessingResult.failed() can include RetryState"""
```

### 1.2 Default Values

```python
class TestProcessingResultDefaults:
    def test_default_data_is_empty_list(self):
        """Default data field is empty list, not None"""

    def test_default_passthrough_fields_is_empty_dict(self):
        """Default passthrough_fields is empty dict"""

    def test_default_retry_state_is_fresh(self):
        """Default RetryState has attempts=0, exhausted=False"""

    def test_default_executed_is_true(self):
        """Default executed is True (most results are executed)"""
```

### 1.3 RetryState

```python
class TestRetryState:
    def test_retry_state_default_values(self):
        """RetryState defaults: attempts=0, last_error=None, exhausted=False"""

    def test_retry_state_tracks_attempts(self):
        """RetryState.attempts increments correctly"""

    def test_retry_state_stores_last_error(self):
        """RetryState.last_error captures error message"""

    def test_retry_state_exhausted_flag(self):
        """RetryState.exhausted=True when max attempts reached"""
```

---

## 2. ProcessingContext Tests

**File**: `tests/core/test_processing_context.py`

### 2.1 Required Fields

```python
class TestProcessingContextRequired:
    def test_requires_agent_config(self):
        """ProcessingContext requires agent_config dict"""

    def test_requires_agent_name(self):
        """ProcessingContext requires agent_name string"""
```

### 2.2 Default Values

```python
class TestProcessingContextDefaults:
    def test_default_mode_is_online(self):
        """Default mode is ProcessingMode.ONLINE"""

    def test_default_is_first_stage_is_false(self):
        """Default is_first_stage is False (subsequent stage)"""

    def test_default_source_data_is_empty_list(self):
        """Default source_data is empty list"""

    def test_default_record_index_is_zero(self):
        """Default record_index is 0"""
```

### 2.3 Properties

```python
class TestProcessingContextProperties:
    def test_action_name_from_agent_type(self):
        """action_name returns agent_config['agent_type'] if present"""

    def test_action_name_fallback_to_agent_name(self):
        """action_name returns agent_name if agent_type not in config"""
```

---

## 3. RecordProcessor Tests

**File**: `tests/core/test_record_processor.py`

### 3.1 Input Normalization

```python
class TestRecordProcessorInputNormalization:
    def test_first_stage_generates_source_guid(self):
        """First-stage: generates deterministic source_guid from raw input"""

    def test_first_stage_preserves_source_snapshot(self):
        """First-stage: source_snapshot contains original input"""

    def test_first_stage_content_is_raw_input(self):
        """First-stage: content equals raw input dict"""

    def test_subsequent_stage_extracts_content_field(self):
        """Subsequent-stage: extracts item['content'] as content"""

    def test_subsequent_stage_extracts_source_guid(self):
        """Subsequent-stage: extracts item['source_guid']"""

    def test_subsequent_stage_no_source_snapshot(self):
        """Subsequent-stage: source_snapshot is None"""

    def test_subsequent_stage_content_fallback_to_item(self):
        """Subsequent-stage: if no 'content' key, use entire item as content"""
```

### 3.2 Guard Evaluation

```python
class TestRecordProcessorGuardEvaluation:
    def test_no_guard_config_proceeds_to_processing(self):
        """No guard/conditional_clause in config → process normally"""

    def test_guard_condition_true_proceeds_to_processing(self):
        """Guard evaluates True → process normally"""

    def test_guard_condition_false_filter_behavior(self):
        """Guard False + behavior='filter' → ProcessingResult.filtered()"""

    def test_guard_condition_false_skip_behavior(self):
        """Guard False + behavior='skip' → ProcessingResult.skipped()"""

    def test_guard_skip_includes_passthrough_data(self):
        """Skipped result includes original content as passthrough"""

    def test_guard_evaluates_against_content_dict(self):
        """Guard expression can reference fields in content"""

    def test_guard_with_non_dict_content_wraps_in_raw(self):
        """Non-dict content wrapped as {'_raw': content} for guard eval"""
```

### 3.3 LLM Execution

```python
class TestRecordProcessorLLMExecution:
    def test_calls_run_dynamic_agent_with_correct_args(self):
        """run_dynamic_agent called with config, name, content, prompt"""

    def test_passes_tools_path_when_configured(self):
        """tools_path from agent_config['tools']['path'] passed to run_dynamic_agent"""

    def test_executed_true_returns_success_result(self):
        """run_dynamic_agent returns (response, True) → ProcessingResult.success()"""

    def test_executed_false_response_none_returns_filtered(self):
        """run_dynamic_agent returns (None, False) → ProcessingResult.filtered()"""

    def test_executed_false_response_present_returns_skipped(self):
        """run_dynamic_agent returns (data, False) → ProcessingResult.skipped()"""

    def test_passthrough_fields_from_prompt_preparation(self):
        """passthrough_fields from PromptPreparationResult stored in result"""
```

### 3.4 Response Transformation

```python
class TestRecordProcessorResponseTransformation:
    def test_calls_transform_with_passthrough(self):
        """transform_with_passthrough called for successful execution"""

    def test_transformed_data_in_result(self):
        """Transformed data stored in ProcessingResult.data"""

    def test_raw_response_preserved_in_result(self):
        """Raw LLM response stored in ProcessingResult.raw_response"""
```

### 3.5 Batch Processing

```python
class TestRecordProcessorBatch:
    def test_process_batch_returns_list_of_results(self):
        """process_batch returns List[ProcessingResult]"""

    def test_process_batch_increments_record_index(self):
        """Each item processed with incrementing record_index"""

    def test_process_batch_preserves_context_fields(self):
        """Context fields (source_data, file_path, etc.) preserved per item"""

    def test_process_batch_empty_list_returns_empty(self):
        """Empty items list returns empty results list"""
```

### 3.6 Error Handling

```python
class TestRecordProcessorErrorHandling:
    def test_llm_exception_returns_failed_result(self):
        """Exception during LLM call → ProcessingResult.failed()"""

    def test_failed_result_includes_error_message(self):
        """Failed result contains exception message"""

    def test_transform_exception_returns_failed_result(self):
        """Exception during transform → ProcessingResult.failed()"""
```

---

## 4. EnrichmentPipeline Tests

**File**: `tests/core/test_enrichment_pipeline.py`

### 4.1 LineageEnricher

```python
class TestLineageEnricher:
    def test_skips_filtered_results(self):
        """FILTERED status → no lineage added"""

    def test_generates_node_id_from_action_name(self):
        """node_id generated using IDGenerator.generate_node_id(action_name)"""

    def test_single_item_gets_base_node_id(self):
        """Single item: node_id = base_node_id (no suffix)"""

    def test_multiple_items_get_indexed_node_ids(self):
        """Multiple items: node_id = base_node_id_0, base_node_id_1, etc."""

    def test_lineage_built_with_source_guid(self):
        """LineageBuilder.build_lineage called with source_guid"""

    def test_result_node_id_set_to_base(self):
        """result.node_id set to base_node_id"""
```

### 4.2 MetadataEnricher

```python
class TestMetadataEnricher:
    def test_skips_non_executed_results(self):
        """executed=False → no metadata added"""

    def test_extracts_metadata_from_raw_response(self):
        """MetadataExtractor.extract_from_response called with raw_response"""

    def test_adds_metadata_to_each_item(self):
        """FieldManager.add_metadata called for each item in data"""
```

### 4.3 LoopIdEnricher

```python
class TestLoopIdEnricher:
    def test_skips_filtered_results(self):
        """FILTERED status → no loop ID added"""

    def test_adds_version_correlation_id_to_each_item(self):
        """VersionIdGenerator.add_version_correlation_id called per item"""

    def test_uses_record_index_from_context(self):
        """record_index from context passed to VersionIdGenerator"""
```

### 4.4 PassthroughEnricher

```python
class TestPassthroughEnricher:
    def test_skips_empty_passthrough_fields(self):
        """Empty passthrough_fields → no changes"""

    def test_merges_passthrough_into_content_dict(self):
        """passthrough_fields merged into item['content']"""

    def test_handles_nested_content_field(self):
        """Works when item has nested 'content' dict"""

    def test_handles_flat_item_structure(self):
        """Works when item has no 'content' key"""
```

### 4.5 RequiredFieldsEnricher

```python
class TestRequiredFieldsEnricher:
    def test_skips_filtered_results(self):
        """FILTERED status → no required fields check"""

    def test_calls_ensure_required_fields(self):
        """FieldManager().ensure_required_fields called per item"""

    def test_passes_source_guid_to_ensure_required_fields(self):
        """source_guid from result passed to ensure_required_fields"""
```

### 4.6 Pipeline Ordering

```python
class TestEnrichmentPipeline:
    def test_default_enricher_order(self):
        """Default order: Lineage → Metadata → LoopId → Passthrough → RequiredFields"""

    def test_enrichers_run_in_sequence(self):
        """Each enricher receives output of previous enricher"""

    def test_custom_enricher_list(self):
        """Can construct pipeline with custom enricher list"""

    def test_empty_enricher_list_returns_unchanged(self):
        """Empty enricher list returns result unchanged"""
```

---

## 5. ConfigRegistry Tests

**File**: `tests/core/test_config_registry.py`

### 5.1 ConfigField Resolution

```python
class TestConfigFieldResolution:
    def test_standard_inheritance_action_first(self):
        """STANDARD: action value takes priority"""

    def test_standard_inheritance_defaults_second(self):
        """STANDARD: defaults used when not in action"""

    def test_standard_inheritance_hardcoded_last(self):
        """STANDARD: hardcoded default when not in action or defaults"""

    def test_action_only_ignores_defaults(self):
        """ACTION_ONLY: only action value used, ignores defaults"""

    def test_required_raises_when_missing(self):
        """REQUIRED: raises ValueError when not in action or defaults"""

    def test_required_from_action(self):
        """REQUIRED: works when value in action"""

    def test_required_from_defaults(self):
        """REQUIRED: works when value in defaults"""
```

### 5.2 ConfigRegistry

```python
class TestConfigRegistry:
    def test_register_adds_field(self):
        """register() adds field to registry"""

    def test_resolve_all_returns_dict(self):
        """resolve_all() returns dict of field_name → resolved_value"""

    def test_resolve_all_includes_all_registered_fields(self):
        """resolve_all() includes every registered field"""

    def test_required_field_missing_raises_in_resolve_all(self):
        """resolve_all() raises if required field missing"""
```

### 5.3 Default Fields

```python
class TestDefaultConfigFields:
    def test_model_vendor_is_required(self):
        """model_vendor has REQUIRED inheritance"""

    def test_model_name_is_required(self):
        """model_name has REQUIRED inheritance"""

    def test_run_mode_default_is_online(self):
        """run_mode defaults to 'online'"""

    def test_json_mode_default_is_true(self):
        """json_mode defaults to True"""

    def test_is_operational_default_is_true(self):
        """is_operational defaults to True"""

    def test_retry_default_has_max_attempts(self):
        """retry defaults to {'max_attempts': 3}"""
```

---

## 6. Integration Tests

### 6.1 First-Stage Processing (Staging Replacement)

**File**: `tests/integration/test_first_stage_processing.py`

```python
class TestFirstStageProcessing:
    def test_raw_text_input_produces_structured_output(self):
        """Raw text → LLM → structured dict with source_guid, lineage, etc."""

    def test_raw_json_input_produces_structured_output(self):
        """Raw JSON dict → LLM → structured output"""

    def test_source_snapshot_preserved_for_saving(self):
        """Original input available in result.source_snapshot"""

    def test_deterministic_source_guid_generation(self):
        """Same input → same source_guid (deterministic)"""

    def test_lineage_tracking_added(self):
        """Output includes lineage field with node_id"""

    def test_metadata_added(self):
        """Output includes metadata from LLM response"""
```

### 6.2 Subsequent-Stage Processing (Target Replacement)

**File**: `tests/integration/test_subsequent_stage_processing.py`

```python
class TestSubsequentStageProcessing:
    def test_structured_input_with_source_guid(self):
        """Input {content, source_guid} → LLM → structured output"""

    def test_source_data_lookup_by_guid(self):
        """source_content looked up from source_data by source_guid"""

    def test_passthrough_fields_merged(self):
        """passthrough_fields from context_scope merged into output"""

    def test_version_correlation_id_added(self):
        """version_correlation_id added based on record_index"""

    def test_guard_skip_preserves_input(self):
        """Guard skip → input passed through unchanged"""

    def test_guard_filter_excludes_from_output(self):
        """Guard filter → empty result, not included in output"""
```

### 6.3 Parity Tests (Old vs New)

**File**: `tests/integration/test_processing_parity.py`

These tests ensure the new `RecordProcessor` produces identical output to the old code.

```python
class TestProcessingParity:
    def test_staging_processor_parity_simple_input(self):
        """
        Given same input:
        - StagingProcessor.staging_dynamic_creator() output
        - RecordProcessor(is_first_stage=True) output
        Must be equivalent (same data, same source_guid, same lineage structure)
        """

    def test_staging_processor_parity_with_guard_skip(self):
        """Parity when guard evaluates to skip"""

    def test_staging_processor_parity_with_guard_filter(self):
        """Parity when guard evaluates to filter"""

    def test_target_processor_parity_simple_input(self):
        """
        Given same input:
        - TargetContentProcessor._process_single_item() output
        - RecordProcessor(is_first_stage=False) output
        Must be equivalent
        """

    def test_target_processor_parity_with_passthrough(self):
        """Parity with passthrough fields configured"""

    def test_target_processor_parity_with_guard_skip(self):
        """Parity when guard evaluates to skip"""

    def test_target_processor_parity_with_guard_filter(self):
        """Parity when guard evaluates to filter"""

    def test_target_processor_parity_with_loop_context(self):
        """Parity with loop_context provided"""

    def test_lineage_structure_identical(self):
        """Lineage dict structure identical between old and new"""

    def test_metadata_structure_identical(self):
        """Metadata dict structure identical between old and new"""

    def test_source_guid_generation_identical(self):
        """Same input produces same source_guid in old and new"""
```

---

## 7. Behavior Preservation Tests

These tests capture specific behaviors from the current implementation that MUST be preserved.

**File**: `tests/core/test_behavior_preservation.py`

```python
class TestBehaviorPreservation:
    # From StagingProcessor
    def test_staging_returns_none_on_error(self):
        """Current: staging_dynamic_creator returns None on error
        New: Should return ProcessingResult.failed() instead
        BREAKING CHANGE - document in migration guide"""

    def test_staging_returns_tuple_with_src_text(self):
        """Current: returns (transformed_response, src_text)
        New: returns ProcessingResult with source_snapshot
        BREAKING CHANGE - callers must adapt"""

    # From TargetContentProcessor
    def test_target_raises_processing_error(self):
        """Current: _process_single_item raises ProcessingError
        New: Should return ProcessingResult.failed()
        BREAKING CHANGE - callers catching exceptions must adapt"""

    def test_target_returns_empty_list_on_filter(self):
        """Current: returns [] when guard filters
        New: returns ProcessingResult.filtered() with data=[]
        COMPATIBLE - same semantic"""

    def test_target_returns_list_on_skip(self):
        """Current: returns [passthrough_item] when guard skips
        New: returns ProcessingResult.skipped() with data=[item]
        COMPATIBLE - same semantic"""

    # Lineage
    def test_lineage_add_context_lineage_tracking_format(self):
        """Verify LineageBuilder.add_context_lineage_tracking output format"""

    def test_lineage_add_lineage_tracking_format(self):
        """Verify LineageBuilder.add_lineage_tracking output format"""

    def test_unified_lineage_matches_both_formats(self):
        """New unified lineage must match structure of both old methods"""

    # Passthrough
    def test_passthrough_merged_into_content_dict(self):
        """passthrough_fields merged into item['content'] dict"""

    def test_passthrough_merged_into_flat_item(self):
        """passthrough_fields merged into item when no 'content' key"""

    # Guard
    def test_guard_evaluation_context_includes_content_fields(self):
        """Guard can reference fields from content dict"""

    def test_guard_filter_returns_empty_immediately(self):
        """Filter behavior returns immediately, no LLM call"""

    def test_guard_skip_returns_passthrough_immediately(self):
        """Skip behavior returns immediately, no LLM call"""
```

---

## 8. Edge Cases

**File**: `tests/core/test_edge_cases.py`

```python
class TestEdgeCases:
    def test_empty_content_dict(self):
        """Handle item with content={}"""

    def test_none_content(self):
        """Handle item with content=None"""

    def test_missing_source_guid(self):
        """Handle item without source_guid (subsequent stage)"""

    def test_empty_source_data(self):
        """Handle empty source_data list"""

    def test_source_guid_not_found_in_source_data(self):
        """Handle source_guid not matching any source_data item"""

    def test_llm_returns_empty_list(self):
        """Handle LLM returning []"""

    def test_llm_returns_single_dict(self):
        """Handle LLM returning single dict (not list)"""

    def test_llm_returns_none(self):
        """Handle LLM returning None"""

    def test_transform_returns_empty(self):
        """Handle transform_with_passthrough returning []"""

    def test_deeply_nested_content(self):
        """Handle deeply nested content structure"""

    def test_special_characters_in_content(self):
        """Handle special characters in content fields"""

    def test_very_large_content(self):
        """Handle very large content dict"""

    def test_circular_reference_in_content(self):
        """Handle (or reject) circular references in content"""
```

---

## Test Execution Order

1. **Unit tests first** (tests/core/):
   - `test_processing_result.py`
   - `test_processing_context.py`
   - `test_config_registry.py`
   - `test_enrichment_pipeline.py`
   - `test_record_processor.py`

2. **Behavior preservation tests**:
   - `test_behavior_preservation.py`

3. **Edge case tests**:
   - `test_edge_cases.py`

4. **Integration tests last**:
   - `test_first_stage_processing.py`
   - `test_subsequent_stage_processing.py`
   - `test_processing_parity.py`

---

## Test Fixtures Needed

```python
# tests/conftest.py additions

@pytest.fixture
def minimal_agent_config():
    """Minimal valid agent config for testing"""
    return {
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "agent_type": "test_action",
    }

@pytest.fixture
def agent_config_with_guard():
    """Agent config with guard configured"""
    return {
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "agent_type": "test_action",
        "guard": {
            "condition": "status == 'active'",
            "behavior": "skip"
        }
    }

@pytest.fixture
def agent_config_with_passthrough():
    """Agent config with context_scope.passthrough"""
    return {
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "agent_type": "test_action",
        "context_scope": {
            "passthrough": ["field_a", "field_b"]
        }
    }

@pytest.fixture
def sample_structured_item():
    """Sample structured item for subsequent-stage testing"""
    return {
        "content": {"name": "test", "value": 123},
        "source_guid": "guid-12345",
        "target_id": "target-67890",
    }

@pytest.fixture
def sample_raw_item():
    """Sample raw item for first-stage testing"""
    return {"name": "test", "value": 123}

@pytest.fixture
def sample_source_data():
    """Sample source_data list for lookups"""
    return [
        {"source_guid": "guid-12345", "content": {"original": "data"}},
        {"source_guid": "guid-67890", "content": {"other": "data"}},
    ]

@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing"""
    return [{"generated": "content", "score": 0.95}]
```

---

## Mocking Strategy

```python
# Key mocks needed:

# 1. Mock run_dynamic_agent to avoid actual LLM calls
@pytest.fixture
def mock_run_dynamic_agent(mocker):
    return mocker.patch(
        "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
        return_value=({"generated": "data"}, True)
    )

# 2. Mock PromptPreparationService
@pytest.fixture
def mock_prompt_preparation(mocker):
    mock_result = MagicMock()
    mock_result.formatted_prompt = "Test prompt"
    mock_result.passthrough_fields = {}
    return mocker.patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context",
        return_value=mock_result
    )

# 3. Mock transform_with_passthrough
@pytest.fixture
def mock_transform(mocker):
    return mocker.patch(
        "agent_actions.utilities.processor.processor_helpers.transform_with_passthrough",
        return_value=[{"transformed": "data"}]
    )

# 4. Mock IDGenerator for deterministic tests
@pytest.fixture
def mock_id_generator(mocker):
    mocker.patch(
        "agent_actions.utilities.id_generation.IDGenerator.generate_node_id",
        return_value="node-test-123"
    )
    mocker.patch(
        "agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid",
        return_value="guid-deterministic-456"
    )
```

---

## Summary

| Category | Test Count |
|----------|------------|
| ProcessingResult | 14 |
| ProcessingContext | 6 |
| RecordProcessor | 22 |
| EnrichmentPipeline | 18 |
| ConfigRegistry | 14 |
| Integration - First Stage | 6 |
| Integration - Subsequent Stage | 6 |
| Integration - Parity | 10 |
| Behavior Preservation | 14 |
| Edge Cases | 13 |
| **Total** | **123** |

All 123 tests should be written and passing BEFORE implementing the `RecordProcessor`.
