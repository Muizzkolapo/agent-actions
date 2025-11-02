# Batch and Realtime Architecture

**Last Updated:** 2025-11-01
**Issue:** [#492](https://github.com/Muizzkolapo/agent-actions/issues/492)

## Overview

This document describes the architecture of batch and realtime processing modes in agent-actions, focusing on shared components and mode-specific implementations after the refactoring completed in issue #492.

## Table of Contents

1. [Architecture Goals](#architecture-goals)
2. [Mode Comparison](#mode-comparison)
3. [Shared Components](#shared-components)
4. [Mode-Specific Components](#mode-specific-components)
5. [Data Flow Diagrams](#data-flow-diagrams)
6. [When to Use Each Mode](#when-to-use-each-mode)
7. [Developer Guide](#developer-guide)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Goals

The refactoring in issue #492 achieved the following goals:

1. **Eliminate Code Duplication** - Extracted ~160 lines of duplicated code into shared services
2. **Single Source of Truth** - Changes to shared logic now require updates in ONE place
3. **Preserve Mode-Specific Behavior** - Respects fundamental differences between batch and realtime modes
4. **Zero Breaking Changes** - 100% backwards compatible with existing functionality
5. **Improved Maintainability** - Clear separation between shared and mode-specific code

---

## Mode Comparison

### Batch Mode

**Purpose:** Process large datasets asynchronously using vendor batch APIs

**Characteristics:**
- Uses vendor batch APIs (OpenAI Batch API, etc.)
- Deferred processing and response retrieval
- Cost-optimized (typically 50% discount)
- High throughput for large datasets
- Results available after processing completes

**Key Files:**
- `agent_actions/llm_invocation/batch/batch_service.py`
- `agent_actions/llm_invocation/batch/loaders_batch_data_loader.py`

### Realtime Mode

**Purpose:** Process data synchronously with immediate responses

**Characteristics:**
- Uses standard vendor APIs (immediate response)
- Synchronous or async streaming
- Lower latency for individual requests
- Interactive use cases
- Results available immediately

**Key Files:**
- `agent_actions/prompt_generation/data_generator.py`
- `agent_actions/prompt_generation/target_data_generator.py`
- `agent_actions/llm_invocation/realtime/agent_builder.py`

---

## Shared Components

These components are used identically by both batch and realtime modes:

### 1. FilterService

**Location:** `agent_actions/preprocessing/filter_service.py`

**Purpose:** Centralized WHERE clause and conditional filtering logic

**Key Methods:**
- `filter_single_item(item_content, where_clause_config, conditional_clause)` → FilterStatus
- `apply_where_clause_filtering(data, where_clause_config, conditional_clause, content_key)` → (filtered_data, status_map)

**Features:**
- WHERE clause filtering with 'filter' behavior (exclude non-matching items)
- WHERE clause filtering with 'skip' behavior (mark for passthrough)
- Conditional clause evaluation (legacy UDF-based)
- `passthrough_on_error` configuration support
- Status tracking for batch mode context map

**Usage Example:**
```python
from agent_actions.preprocessing.filter_service import get_filter_service

filter_service = get_filter_service()
filter_status = filter_service.filter_single_item(
    item_content=row_content,
    where_clause_config=where_clause_config,
    conditional_clause=conditional_clause
)

if filter_status.should_include:
    # Process the item
    pass
else:
    # Skip or filter the item
    context_map[item_id]['_batch_filter_status'] = filter_status.status
```

**Benefits:**
- Single place to modify filtering logic
- Consistent behavior across modes
- Comprehensive test coverage (21 tests)

### 2. LLMContextBuilder

**Location:** `agent_actions/utilities/llm_context_builder.py`

**Purpose:** Unified LLM context building with mode-specific approaches

**Key Methods:**
- `build_llm_context_for_batch(row_content, llm_context, context_scope)` → Dict
- `build_llm_context_for_realtime(processed_context, llm_additional_context, context_scope)` → Dict

**Features:**
- Batch mode: Uses `dict.pop()` for drops, `dict.update()` for observe
- Realtime mode: Uses `DataTransformer.remove_schema_objects()` for drops, dict spread for observe
- Handles `context_scope.drop` and `context_scope.observe` directives
- Supports None inputs and non-dict edge cases
- Skips invalid field references silently

**Usage Example (Batch):**
```python
from agent_actions.utilities.llm_context_builder import LLMContextBuilder

llm_full_context = LLMContextBuilder.build_llm_context_for_batch(
    row_content=row_content,
    llm_context=llm_context,  # From context_scope.observe
    context_scope=context_scope
)
```

**Usage Example (Realtime):**
```python
from agent_actions.utilities.llm_context_builder import LLMContextBuilder

processed_context = LLMContextBuilder.build_llm_context_for_realtime(
    processed_context=processed_context,
    llm_additional_context=llm_additional_context,
    context_scope=context_scope
)
```

**Benefits:**
- Single place to modify context building logic
- Preserves mode-specific approaches for backward compatibility
- Clear separation of batch vs realtime implementations

### 3. PromptFormatter

**Location:** `agent_actions/preprocessing/prompt_formatter.py`

**Purpose:** Unified prompt loading and validation

**Key Methods:**
- `get_raw_prompt(agent_config)` → str
- `format_prompt(raw_prompt, field_context)` → str

**Features:**
- Loads prompt from `agent_config[PROMPT_KEY]`
- Supports `$` prefix for external file loading
- Provides default fallback: `'Process the following content: {content}'`
- Error handling with `PromptValidationError`
- Type checking for string prompts

**Usage Example:**
```python
from agent_actions.preprocessing.prompt_formatter import PromptFormatter

raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
formatted_prompt = PromptFormatter.format_prompt(raw_prompt, field_context)
```

**Benefits:**
- Single place to modify prompt loading logic
- Consistent behavior across all modes
- Centralized error handling

### 4. ContextScopeProcessor

**Location:** `agent_actions/utilities/context_scope_processor.py`

**Purpose:** Field context building with context_scope directives

**Key Methods:**
- `build_field_context_with_history()` - Builds field context with historical data
- `apply_context_scope()` - Splits field_context into prompt/llm/passthrough streams
- `merge_passthrough_fields()` - Merges passthrough fields into LLM output

**Status:** Already shared before issue #492

### 5. PromptPreparationService

**Location:** `agent_actions/prompt_generation/prompt_preparation_service.py`

**Purpose:** Unified prompt preparation orchestration for batch and realtime modes

**Key Methods:**
- `prepare_prompt_with_context(agent_config, agent_name, contents, mode, ...)` → PromptPreparationResult
- Returns: `PromptPreparationResult(formatted_prompt, llm_context, passthrough_fields, metadata)`

**Features:**
- **7-Step Orchestration Pipeline:**
  1. Load raw prompt template (via PromptFormatter)
  2. Build field context with historical node loading (via ContextScopeProcessor)
  3. Apply context_scope transformations (observe/drop/passthrough)
  4. Build LLM context (mode-specific: batch vs realtime)
  5. Replace field references ({action.field})
  6. Inject function outputs (batch mode only, via dispatch_task)
  7. Append few-shot samples (via SampleEnricher)
- **Mode-Specific Handling:** Accepts `mode='batch'` or `mode='realtime'` parameter
- **Comprehensive Metadata:** Returns debug info for troubleshooting
- **Guaranteed Parity:** Both modes use identical orchestration logic

**Usage Example (Realtime Mode):**
```python
from agent_actions.prompt_generation.prompt_preparation_service import (
    PromptPreparationService
)

# Prepare prompt with all transformations
prep_result = PromptPreparationService.prepare_prompt_with_context(
    agent_config=agent_config,
    agent_name='validator',
    contents=contents,
    mode='realtime',
    agent_indices=agent_indices,
    dependency_configs=dependency_configs,
    source_content=source_content,
    loop_context=loop_context,
    workflow_metadata=workflow_metadata,
    current_item=current_item,
    file_path=file_path
)

# Use prepared results
formatted_prompt = prep_result.formatted_prompt  # Has few-shot samples
llm_context = prep_result.llm_context  # Ready for LLM
passthrough_fields = prep_result.passthrough_fields  # For output merging
```

**Usage Example (Batch Mode):**
```python
# Batch mode includes function injection for dispatch_task()
prep_result = PromptPreparationService.prepare_prompt_with_context(
    agent_config=agent_config,
    agent_name='processor',
    contents=row_content,
    mode='batch',
    agent_indices=self.agent_indices,
    dependency_configs=self.dependency_configs,
    source_content=row_content,
    current_item=context_map[custom_id],
    file_path=file_path_for_history,
    tools_path=tools_path  # For function injection
)

# Create batch task with prepared data
task = {
    'target_id': custom_id,
    'content': prep_result.llm_context,
    'prompt': prep_result.formatted_prompt
}
```

**Benefits:**
- **Single Point of Truth:** All prompt preparation logic in ONE place
- **Guaranteed Parity:** Batch and realtime modes cannot diverge (use same code)
- **Easier Testing:** Test service in isolation with comprehensive unit tests
- **Better Debugging:** Metadata provides visibility into transformations
- **Reduced Complexity:** Eliminates ~220 lines of duplicate/wrapper code
- **Bug Prevention:** Fixed few-shot sample bug (was missing in batch mode before)
- **Future-Proof:** New features only need to modify one service

**Status:** Added in issue #487 (Phases 1-3)

**Related Components:**
- Uses: PromptFormatter, ContextScopeProcessor, LLMContextBuilder, PromptUtils, SampleEnricher
- Used by: DataGenerator, TargetDataGenerator, BatchService

**Tests:**
- Unit tests: `tests/prompt_generation/test_prompt_preparation_service.py` (22 tests)
- Integration tests: `tests/integration/test_prompt_preparation_parity.py` (6 parity tests)

### 6. Other Shared Components

All these were already shared before issue #492:

- **PromptUtils** - Field reference replacement (`{reference.field}`)
- **DataTransformer** - Data transformation and schema manipulation
- **ProcessorUtils** - Lineage tracking, node ID generation, loop correlation
- **HistoricalNodeDataLoader** - Loading previous action data

---

## Mode-Specific Components

These components remain separate because they handle fundamentally different processing patterns:

### Batch Mode Specific

1. **LLM Invocation**
   - Uses vendor batch APIs
   - Submits jobs asynchronously
   - Returns batch_id for later retrieval

2. **Response Retrieval**
   - Polls for batch completion
   - Downloads results when ready
   - Maps responses using custom_id

3. **Context Map Storage**
   - Stores item context for deferred processing
   - Tracks `_batch_filter_status` for filtering

4. **File I/O Patterns**
   - Writes JSONL batch files
   - Manages batch registry
   - Handles output directory structure

### Realtime Mode Specific

1. **LLM Invocation**
   - Direct API calls with immediate response
   - Streaming support for some vendors
   - No batch_id concept

2. **Response Handling**
   - Processes responses immediately
   - No polling required
   - Direct result return

3. **Data Flow**
   - Streaming through generators
   - Item-by-item processing
   - Immediate output writing

---

## Data Flow Diagrams

### Batch Mode Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA INPUT                                                   │
│    BatchDataLoader.load_data() → List[Dict]                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. PROMPT LOADING (Shared: PromptFormatter)                    │
│    PromptFormatter.get_raw_prompt(agent_config) → str          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. FILTERING (Shared: FilterService)                           │
│    FilterService.filter_single_item() → FilterStatus           │
│    - WHERE clause evaluation                                    │
│    - Conditional clause evaluation                              │
│    - Status tracking in context_map                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. FIELD CONTEXT BUILDING (Shared: ContextScopeProcessor)     │
│    ContextScopeProcessor.build_field_context_with_history()    │
│    → (field_context, llm_context, passthrough_fields)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. LLM CONTEXT BUILDING (Shared: LLMContextBuilder)           │
│    LLMContextBuilder.build_llm_context_for_batch()             │
│    - Start with row_content.copy()                              │
│    - Remove dropped fields (dict.pop)                           │
│    - Add observed fields (dict.update)                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. PROMPT FORMATTING (Shared: PromptUtils)                     │
│    PromptUtils.replace_field_references() → formatted_prompt   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. BATCH SUBMISSION (Mode-Specific: BatchProvider)            │
│    provider.submit_batch() → batch_id                           │
│    - Creates JSONL batch file                                   │
│    - Submits to vendor API                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. RESPONSE RETRIEVAL (Mode-Specific: BatchProvider)          │
│    provider.get_batch_results(batch_id) → List[BatchResult]   │
│    - Polls for completion                                       │
│    - Downloads results                                          │
│    - Maps via custom_id                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 9. PASSTHROUGH MERGE (Shared: ContextScopeProcessor)          │
│    ContextScopeProcessor.merge_passthrough_fields()            │
│    - Merges passthrough fields into LLM output                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 10. OUTPUT WRITING (Mode-Specific: FileWriter)                │
│     FileWriter.write_results() → output files                   │
└─────────────────────────────────────────────────────────────────┘
```

### Realtime Mode Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA INPUT                                                   │
│    Iterator/Generator → item-by-item processing                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. PROMPT LOADING (Shared: PromptFormatter)                    │
│    PromptFormatter.get_raw_prompt(agent_config) → str          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. FILTERING (Shared: FilterService or run_dynamic_agent)     │
│    - WHERE clause evaluation with 'skip' behavior              │
│    - Conditional clause evaluation                              │
│    - Returns (context, executed) tuple                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. FIELD CONTEXT BUILDING (Shared: ContextScopeProcessor)     │
│    ContextScopeProcessor.build_field_context_with_history()    │
│    → (field_context, llm_context, passthrough_fields)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. LLM CONTEXT BUILDING (Shared: LLMContextBuilder)           │
│    LLMContextBuilder.build_llm_context_for_realtime()          │
│    - Start with processed_context                               │
│    - Remove dropped fields (DataTransformer)                    │
│    - Merge observed fields (dict spread)                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. PROMPT FORMATTING (Shared: PromptUtils)                     │
│    PromptUtils.replace_field_references() → formatted_prompt   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. LLM INVOCATION (Mode-Specific: agent_builder)              │
│    agent_builder.create_dynamic_agent() → response             │
│    - Direct vendor API call                                     │
│    - Immediate response                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. PASSTHROUGH MERGE (Shared: ContextScopeProcessor)          │
│    ContextScopeProcessor.merge_passthrough_fields()            │
│    - Merges passthrough fields into LLM output                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 9. OUTPUT WRITING (Mode-Specific: FileWriter)                 │
│    FileWriter.write_results() → output files (immediate)       │
└─────────────────────────────────────────────────────────────────┘
```

---

## When to Use Each Mode

### Use Batch Mode When:

✅ Processing **large datasets** (thousands+ items)
✅ Cost optimization is important (50% discount)
✅ Latency is not critical (can wait minutes to hours)
✅ Need to process data asynchronously
✅ Want to leverage vendor batch APIs

**Example Use Cases:**
- Bulk data enrichment
- Large-scale classification tasks
- Batch sentiment analysis
- Historical data processing
- Cost-sensitive workloads

### Use Realtime Mode When:

✅ Need **immediate responses**
✅ Processing small to medium datasets
✅ Interactive applications
✅ Streaming data processing
✅ Low latency requirements

**Example Use Cases:**
- Interactive chat applications
- Real-time data enrichment
- Streaming ETL pipelines
- User-facing features
- Time-sensitive processing

---

## Developer Guide

### Adding New Features to Shared Components

When adding features that should be shared between batch and realtime modes:

1. **Identify the appropriate shared component:**
   - Filtering logic → `FilterService`
   - Context building → `LLMContextBuilder`
   - Prompt handling → `PromptFormatter`
   - Field context → `ContextScopeProcessor`

2. **Update the shared component:**
   - Add the new method/functionality
   - Update docstrings with usage examples
   - Add unit tests

3. **Update both modes to use the new functionality:**
   - Batch mode files: `batch_service.py`
   - Realtime mode files: `data_generator.py`, `target_data_generator.py`, `agent_builder.py`

4. **Run tests:**
   ```bash
   # Run all relevant tests
   pytest tests/preprocessing/test_filter_service.py
   pytest tests/utilities/test_llm_context_builder.py
   pytest tests/tasks/test_batch_service_filtering.py
   pytest tests/agents/generators/test_data_generator_field_context.py
   ```

### Extending FilterService

Example: Adding a new filtering behavior

```python
# In filter_service.py
@dataclass
class FilterStatus:
    should_include: bool
    status: str  # 'included', 'filtered', 'skipped', 'your_new_status'
    error: Optional[str] = None

def filter_single_item(
    self,
    item_content: Dict[str, Any],
    where_clause_config: Optional[Dict[str, Any]],
    conditional_clause: Optional[str],
    your_new_config: Optional[Dict[str, Any]] = None  # Add new param
) -> FilterStatus:
    # Add your new filtering logic here
    pass
```

### Extending LLMContextBuilder

Example: Adding context validation

```python
# In llm_context_builder.py
@staticmethod
def build_llm_context_for_batch(
    row_content: Dict[str, Any],
    llm_context: Dict[str, Any],
    context_scope: Optional[Dict[str, Any]] = None,
    validate: bool = False  # Add new param
) -> Dict[str, Any]:
    # Build context as usual
    llm_full_context = row_content.copy() if isinstance(row_content, dict) else {}

    # Add validation if requested
    if validate:
        _validate_context(llm_full_context)

    return llm_full_context
```

### Mode-Specific Customizations

If you need mode-specific behavior:

1. **Keep it in mode-specific files:**
   - Batch: `batch_service.py`, batch providers
   - Realtime: `data_generator.py`, `agent_builder.py`

2. **Document why it's mode-specific:**
   - Different APIs (batch vs realtime)
   - Different data structures
   - Different performance characteristics

3. **Consider parameterizing shared components:**
   - Instead of duplicating, add parameters to shared components
   - Use strategy pattern for complex variations

---

## Troubleshooting

### Common Issues

#### Issue: Items being filtered unexpectedly

**Symptoms:** Items disappear from batch results or realtime output

**Diagnosis:**
1. Check WHERE clause configuration:
   ```python
   where_clause = agent_config.get('where_clause', {})
   print(f"Behavior: {where_clause.get('behavior')}")  # 'filter' or 'skip'?
   print(f"Clause: {where_clause.get('clause')}")
   ```

2. Check conditional clause:
   ```python
   conditional = agent_config.get('conditional_clause')
   print(f"Conditional: {conditional}")
   ```

3. Enable debug logging:
   ```python
   import logging
   logging.getLogger('agent_actions.preprocessing.filter_service').setLevel(logging.DEBUG)
   ```

**Solution:**
- For 'filter' behavior: Items not matching are excluded (as expected)
- For 'skip' behavior: Items not matching are marked for passthrough
- Adjust WHERE clause or conditional clause as needed

#### Issue: Context scope fields not being observed

**Symptoms:** Fields from `context_scope.observe` not appearing in LLM context

**Diagnosis:**
1. Check that `context_scope.observe` is properly configured
2. Verify `ContextScopeProcessor.apply_context_scope()` is being called
3. Check that `llm_context` is being passed to `LLMContextBuilder`

**Solution:**
```python
# Ensure field_context includes observed fields
field_context, llm_context, passthrough_fields = \
    ContextScopeProcessor.apply_context_scope(field_context, context_scope)

# Verify llm_context is not empty
assert llm_context, "llm_context should contain observed fields"

# Pass llm_context to LLMContextBuilder
llm_full_context = LLMContextBuilder.build_llm_context_for_batch(
    row_content=row_content,
    llm_context=llm_context,  # ← Must pass this
    context_scope=context_scope
)
```

#### Issue: Prompt not loading from file

**Symptoms:** Using `$prompt_file.prompt_name` but getting default prompt

**Diagnosis:**
1. Check that prompt file exists in `./prompt_store/`
2. Verify file format (markdown with `{prompt_name}...{end_prompt}` blocks)
3. Check file permissions

**Solution:**
```python
# Verify prompt loading
from agent_actions.preprocessing.prompt_formatter import PromptFormatter

try:
    raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
    print(f"Loaded prompt: {raw_prompt[:100]}...")
except Exception as e:
    print(f"Error loading prompt: {e}")
```

#### Issue: Batch mode and realtime mode producing different results

**Symptoms:** Same input produces different outputs in batch vs realtime

**Diagnosis:**
1. Compare WHERE clause behavior ('filter' vs 'skip')
2. Check context_scope configuration differences
3. Verify prompt formatting is identical

**Solution:**
- Use same agent_config for both modes
- Verify shared components are being used:
  ```python
  # Both modes should use:
  PromptFormatter.get_raw_prompt()
  LLMContextBuilder.build_llm_context_for_*()
  FilterService.filter_single_item()
  ```

### Debug Checklist

When debugging issues:

- [ ] Check agent_config is properly configured
- [ ] Verify WHERE clause and conditional clause settings
- [ ] Confirm context_scope directives are correct
- [ ] Enable debug logging for relevant components
- [ ] Run unit tests to isolate the issue
- [ ] Compare batch and realtime configurations
- [ ] Check that shared components are being used

### Getting Help

If you encounter issues not covered here:

1. Check the test files for examples:
   - `tests/preprocessing/test_filter_service.py`
   - `tests/utilities/test_llm_context_builder.py`
   - `tests/tasks/test_batch_service_filtering.py`

2. Review the implementation:
   - `agent_actions/preprocessing/filter_service.py`
   - `agent_actions/utilities/llm_context_builder.py`
   - `agent_actions/preprocessing/prompt_formatter.py`

3. File an issue on GitHub with:
   - Minimal reproducible example
   - Expected vs actual behavior
   - Relevant configuration
   - Debug logs

---

## References

- **Issue #492:** [Refactor batch and realtime modes to minimize code duplication](https://github.com/Muizzkolapo/agent-actions/issues/492)
- **Implementation Details:** `dev_artefacts/implementations/issue_492_batch_realtime_refactor.jsonc`
- **FilterService:** `agent_actions/preprocessing/filter_service.py`
- **LLMContextBuilder:** `agent_actions/utilities/llm_context_builder.py`
- **PromptFormatter:** `agent_actions/preprocessing/prompt_formatter.py`
- **ContextScopeProcessor:** `agent_actions/utilities/context_scope_processor.py`

---

**Document Version:** 1.0
**Last Updated:** 2025-11-01
**Status:** Complete (Phases 1-3 of issue #492)
