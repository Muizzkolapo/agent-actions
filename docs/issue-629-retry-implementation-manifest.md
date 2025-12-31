# Issue #629: Automatic Retry for Failed Batch Records
## Implementation Manifest

> **Purpose**: This document captures all complexity, integration points, edge cases, and implementation requirements for automatic batch retry functionality.

---

## 1. Executive Summary

### What We're Building
An automatic retry system that re-submits failed/missing batch records to the provider API, with configurable retry policies and proper batch chain tracking.

### Current State
- **Data model**: Ready (retry fields exist in `BatchJobEntry` but unused)
- **Missing detection**: Ready (`BatchResultReconciler.get_missing_ids()` works)
- **Orchestration**: NOT implemented (no code creates retry batches)

---

## 2. Existing Infrastructure Analysis

### 2.1 BatchJobEntry Data Model
**File**: `agent_actions/llm_invocation/batch/batch_models.py:11-57`

```python
@dataclass
class BatchJobEntry:
    batch_id: str                                    # Provider-specific ID
    status: str                                      # 'submitted'|'validating'|'in_progress'|'finalizing'|'completed'|'failed'|'cancelled'
    timestamp: str                                   # ISO format creation time
    provider: str                                    # 'openai'|'gemini'|'anthropic'|'groq'|'mistral'
    record_count: Optional[int] = None              # Records in batch

    # RETRY FIELDS (exist but unused)
    parent_batch_id: Optional[str] = None           # Links to original batch
    retry_attempt: int = 0                          # 0 = original, 1+ = retry count
    retry_for_records: Optional[List[str]] = None   # custom_ids being retried
    has_retry_batch: bool = False                   # Whether this batch spawned retries
```

**Properties**:
- `is_terminal` -> status in ['completed', 'failed', 'cancelled']
- `is_in_flight` -> status in ['validating', 'in_progress', 'finalizing']

### 2.2 BatchResultReconciler
**File**: `agent_actions/llm_invocation/batch/batch_result_reconciler.py`

**Key Methods**:
| Method | Line | Purpose |
|--------|------|---------|
| `get_expected_ids()` | 80-95 | Returns custom_ids with `_batch_filter_status='included'` |
| `get_missing_ids()` | 97-106 | Returns `expected_ids - processed_ids` |
| `get_passthrough_records()` | 108-140 | Returns records needing passthrough (skipped + missing) |
| `reconcile()` | 142-168 | Full reconciliation returning `BatchReconciliationResult` |
| `get_record_by_id(custom_id)` | 170-180 | Retrieve original row data |

**BatchReconciliationResult**:
```python
@dataclass
class BatchReconciliationResult:
    processed_ids: Set[str]      # Successfully/unsuccessfully processed
    missing_ids: Set[str]        # Expected but not received
    passthrough_records: List[Tuple[str, Dict[str, Any]]]  # (custom_id, original_row)
```

### 2.3 BatchResultProcessor Pipeline
**File**: `agent_actions/llm_invocation/batch/batch_result_processor.py`

**9-Stage Pipeline**:
1. `_stage_1_initialize_context()` - Extract config, create context
2. `_stage_2_reconcile()` - Create BatchResultReconciler
3. `_stage_3_4_process_results()` - Process success + errors, mark_processed()
4. (stages 5 skipped in current impl)
5. `_stage_6_merge_passthroughs()` - **INTEGRATION POINT** - reconcile() called here

**Current Behavior at Stage 6** (lines 425-454):
- Missing records become passthrough items with reason="conditional_clause_failed"
- No retry action taken

### 2.4 BatchService Orchestration
**File**: `agent_actions/llm_invocation/batch/batch_service.py`

**Key Methods**:
| Method | Line | Purpose |
|--------|------|---------|
| `submit_batch_job()` | 106-185 | Submit new batch, save to registry |
| `process_batch_results()` | 256-322 | Process single batch results |
| `process_all_batch_results()` | 335-456 | Process all completed batches |
| `_convert_batch_results_to_workflow_format()` | 324-333 | Delegates to BatchResultProcessor |
| `_retrieve_results()` | 476-503 | Get results from provider, log reconciliation |

**Critical**: `submit_batch_job()` creates `BatchJobEntry` with default retry values:
```python
entry = BatchJobEntry(
    batch_id=batch_id,
    status=initial_status,
    timestamp=datetime.now().isoformat(),
    provider=provider_type,
    record_count=len(tasks),
    # MISSING: parent_batch_id, retry_attempt, retry_for_records not set
)
```

### 2.5 BatchRegistryManager
**File**: `agent_actions/llm_invocation/batch/batch_registry_manager.py`

**Thread-Safe Operations**:
| Method | Purpose |
|--------|---------|
| `save_batch_job(file_name, entry)` | Persist entry |
| `get_batch_job(file_name)` | Get by file key |
| `get_batch_job_by_id(batch_id)` | Get by batch ID |
| `update_status(batch_id, new_status)` | Update status, preserve retry fields |
| `get_all_jobs()` | Get all entries |
| `are_all_jobs_completed(check_provider)` | Aggregate completion check |

**IMPORTANT**: `update_status()` (lines 113-148) explicitly preserves retry fields during updates.

### 2.6 BatchJobManager
**File**: `agent_actions/llm_invocation/batch/batch_job_manager.py`

**Current Capabilities**:
- `are_all_jobs_completed()` - Check all batches terminal
- `get_registry_status()` - Aggregate status ('completed'|'in_progress'|'partial_failed')

**MISSING**:
- No retry orchestration logic
- No batch chain queries (get children, get lineage)

### 2.7 Batch CLI
**File**: `agent_actions/llm_invocation/batch/batch_cli.py`

**Existing Commands**:
- `batch status [--batch-id]` - Check status
- `batch retrieve [--batch-id] [--output-dir]` - Retrieve results

**Pattern**: Click decorators + `@handles_user_errors` + `@requires_project`

---

## 3. Implementation Requirements

### 3.1 New File: BatchRetryOrchestrator
**Path**: `agent_actions/llm_invocation/batch/batch_retry_orchestrator.py`

**Responsibilities**:
1. Determine if retry should be triggered
2. Extract failed record data from context_map
3. Prepare retry batch tasks
4. Submit retry batch to provider
5. Update parent batch entry (has_retry_batch=True)
6. Create child batch entry with retry metadata

**Required Methods**:
```python
class BatchRetryOrchestrator:
    def __init__(
        self,
        registry_manager: BatchRegistryManager,
        client_resolver: BatchClientResolver,
        task_preparator: BatchTaskPreparator,
        context_manager: BatchContextManager,
        retry_config: Optional[RetryConfig] = None
    ): ...

    def should_retry(
        self,
        reconciliation: BatchReconciliationResult,
        current_attempt: int,
        max_attempts: int = 3
    ) -> bool:
        """Determine if retry should be triggered."""
        # Conditions:
        # - missing_ids not empty
        # - current_attempt < max_attempts
        # - Optional: minimum failure rate threshold

    def get_retry_records(
        self,
        missing_ids: Set[str],
        context_map: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract original row data for failed records."""
        # Return filtered context_map with only missing_ids

    def prepare_retry_batch(
        self,
        retry_records: Dict[str, Any],
        agent_config: Dict[str, Any],
        output_directory: str,
        parent_batch_id: str,
        retry_attempt: int
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """Prepare tasks for retry batch."""
        # Use BatchTaskPreparator with filtered data
        # Return (tasks, retry_context_map)

    def submit_retry_batch(
        self,
        tasks: List[Dict],
        retry_context_map: Dict[str, Any],
        parent_batch_id: str,
        retry_attempt: int,
        provider: BaseBatchClient,
        output_directory: str,
        agent_config: Dict[str, Any]
    ) -> str:
        """Submit retry batch and update registry."""
        # 1. Submit to provider
        # 2. Save retry context_map
        # 3. Create BatchJobEntry with retry metadata
        # 4. Update parent entry (has_retry_batch=True)
        # Return new_batch_id

    def orchestrate_retry(
        self,
        batch_id: str,
        reconciliation: BatchReconciliationResult,
        context_map: Dict[str, Any],
        agent_config: Dict[str, Any],
        output_directory: str
    ) -> Optional[str]:
        """Main orchestration method."""
        # Full workflow: should_retry -> get_records -> prepare -> submit
        # Return retry_batch_id or None if no retry needed
```

### 3.2 Modify: BatchResultProcessor
**File**: `agent_actions/llm_invocation/batch/batch_result_processor.py`

**Changes**:
1. Add optional `retry_orchestrator` parameter to `__init__`
2. Add `_stage_7_trigger_retries()` after stage 6
3. Return retry info in result or via callback

**Integration Point** (after line 119):
```python
# Stage 6: Merge passthroughs for missing/skipped records
ctx = self._stage_6_merge_passthroughs(ctx)

# NEW: Stage 7: Trigger retries for missing records
if self._retry_orchestrator and ctx.reconciler:
    reconciliation = ctx.reconciler.reconcile()
    if reconciliation.missing_ids:
        # Trigger retry via orchestrator (async or return retry_info)
        ctx.retry_batch_id = self._trigger_retry(ctx, reconciliation)
```

### 3.3 Modify: BatchService
**File**: `agent_actions/llm_invocation/batch/batch_service.py`

**Changes**:
1. Add `_retry_orchestrator` dependency
2. Modify `process_batch_results()` to handle retry triggering
3. Add `retry_batch_job()` method for CLI

**New Method**:
```python
def retry_batch_job(
    self,
    batch_id: str,
    record_ids: Optional[List[str]] = None,
    output_directory: str = None
) -> str:
    """Manually retry a batch job or specific records."""
    # For CLI: agac batch retry --batch-id X [--record-ids Y Z]
```

### 3.4 Modify: BatchJobManager
**File**: `agent_actions/llm_invocation/batch/batch_job_manager.py`

**New Methods**:
```python
def get_batch_children(self, batch_id: str) -> List[BatchJobEntry]:
    """Get all retry batches for a parent batch."""
    # Find entries where parent_batch_id == batch_id

def get_batch_lineage(self, batch_id: str) -> List[BatchJobEntry]:
    """Get full chain from original to all retries."""
    # Walk up to find root, then collect all descendants

def get_retry_chain_status(self, batch_id: str) -> Dict[str, Any]:
    """Get aggregated status for batch chain."""
    # Return {original_id, retry_attempts, final_status, missing_records}
```

### 3.5 Modify: BatchCLI
**File**: `agent_actions/llm_invocation/batch/batch_cli.py`

**New Command**:
```python
@batch.command()
@click.option("--batch-id", required=True, help="Batch ID to retry")
@click.option("--record-ids", multiple=True, help="Specific record IDs (optional)")
@click.option("--output-dir", "-o", default=".", type=click.Path())
@handles_user_errors("batch retry")
@requires_project
def retry(batch_id: str, record_ids: tuple = None, output_dir: str = "."):
    """Retry failed records from a batch job."""
```

**Enhanced Status Output**:
```python
# Show retry chain info in batch status
# Example: "Batch batch_001 (completed) -> retry_1 (completed) -> retry_2 (in_progress)"
```

### 3.6 New: RetryConfig
**Path**: `agent_actions/llm_invocation/batch/batch_retry_config.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class RetryConfig(BaseModel):
    """Configuration for batch retry behavior."""

    enabled: bool = Field(default=True, description="Enable automatic retries")
    max_attempts: int = Field(default=3, ge=1, le=10, description="Max retry attempts")
    min_failure_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Minimum failure rate to trigger retry (0 = any failure)"
    )
    backoff_strategy: str = Field(
        default="none",  # Batch processing doesn't benefit from backoff
        description="Backoff strategy (none, exponential, linear)"
    )
    retry_on_errors: Optional[List[str]] = Field(
        default=None,
        description="Error types to retry on (None = all errors)"
    )

    @classmethod
    def from_yaml(cls, value):
        """Parse from various YAML formats (bool, str preset, dict)."""
        if value is None or value is False:
            return cls(enabled=False)
        if value is True:
            return cls(enabled=True)
        if isinstance(value, str):
            return cls.from_preset(value)
        if isinstance(value, dict):
            return cls(**value)
        return cls(enabled=False)
```

### 3.7 Modify: Configuration Schema
**File**: `agent_actions/configuration/new_format_schema.py`

**Add to DefaultsConfig and ActionConfig**:
```python
retry: Optional[Union[bool, str, Dict[str, Any]]] = Field(
    default=None,
    description="Retry configuration for batch processing"
)

@field_validator("retry")
@classmethod
def validate_retry(cls, v):
    if v:
        try:
            if isinstance(v, dict):
                RetryConfig(**v)
        except (ValueError, TypeError) as e:
            raise ConfigValidationError(
                "retry_config",
                f"Invalid retry configuration: {e}",
                context={"retry": v},
                cause=e,
            )
    return v
```

---

## 4. Data Flow Diagrams

### 4.1 Current Flow (No Retry)
```
BatchService.process_batch_results()
    ↓
_retrieve_results() → BatchResult[]
    ↓
_convert_batch_results_to_workflow_format()
    ↓
BatchResultProcessor.process()
    ├── Stage 1: Initialize context
    ├── Stage 2: Create reconciler
    ├── Stage 3-4: Process results, mark_processed()
    └── Stage 6: Merge passthroughs (missing → passthrough items)
        ↓
Return processed_data (missing records as passthroughs)
    ↓
Write to output files
```

### 4.2 Proposed Flow (With Retry)
```
BatchService.process_batch_results()
    ↓
_retrieve_results() → BatchResult[]
    ↓
_convert_batch_results_to_workflow_format()
    ↓
BatchResultProcessor.process()
    ├── Stage 1: Initialize context
    ├── Stage 2: Create reconciler
    ├── Stage 3-4: Process results, mark_processed()
    ├── Stage 6: Merge passthroughs
    └── Stage 7: Trigger retry (NEW)
        ├── Check should_retry()
        ├── If yes: BatchRetryOrchestrator.orchestrate_retry()
        │       ├── Get retry records from context_map
        │       ├── Prepare retry tasks
        │       ├── Submit retry batch to provider
        │       ├── Save retry context_map
        │       ├── Create child BatchJobEntry
        │       └── Update parent has_retry_batch=True
        └── Return retry_batch_id (or None)
    ↓
Return processed_data + retry_info
    ↓
Write to output files
    ↓
(Retry batch processed in subsequent run)
```

### 4.3 Batch Chain Structure
```
Original Batch (batch_001)
├── batch_id: "batch_001"
├── parent_batch_id: null
├── retry_attempt: 0
├── has_retry_batch: true
├── record_count: 100
└── status: "completed"

    └── Retry Batch 1 (batch_001_r1)
        ├── batch_id: "batch_001_r1"
        ├── parent_batch_id: "batch_001"
        ├── retry_attempt: 1
        ├── retry_for_records: ["id_5", "id_12", "id_47"]
        ├── has_retry_batch: true
        ├── record_count: 3
        └── status: "completed"

            └── Retry Batch 2 (batch_001_r2)
                ├── batch_id: "batch_001_r2"
                ├── parent_batch_id: "batch_001_r1"
                ├── retry_attempt: 2
                ├── retry_for_records: ["id_12"]
                ├── has_retry_batch: false
                ├── record_count: 1
                └── status: "completed"
```

---

## 5. Edge Cases & Complexity

### 5.1 Filter Status Handling
Records have `_batch_filter_status`:
- `'included'` → Submitted to batch API → Can fail → Retry candidate
- `'skipped'` → Not submitted → Passthrough → NOT retry candidate
- `'filtered'` → Not submitted → Excluded → NOT retry candidate

**Only retry records with `_batch_filter_status='included'` that are missing from results.**

### 5.2 Error Types
Missing records can be due to:
1. **Provider-side timeout** → Retry makes sense
2. **Rate limiting** → Retry with backoff
3. **Invalid input** → Retry won't help (skip)
4. **Content policy violation** → Retry won't help (skip)

**Consider**: Add error categorization to skip non-retriable errors.

### 5.3 Partial Success Scenarios
A retry batch can also have failures:
- Original: 100 records → 3 failed
- Retry 1: 3 records → 1 failed
- Retry 2: 1 record → 0 failed (success)
- Retry 2: 1 record → 1 failed (max attempts reached)

**Handle**: Chain continues until all succeed OR max_attempts reached.

### 5.4 Context Map Preservation
Each batch needs its own context_map:
- Original: `batch_context_map_default.json` (100 records)
- Retry 1: `batch_context_map_default_r1.json` (3 records)
- Retry 2: `batch_context_map_default_r2.json` (1 record)

**Naming convention**: `{original_name}_r{attempt}.json`

### 5.5 Registry Entry Naming
Current: Uses `file_name` as key (e.g., "input.json")
For retries: Need unique keys

**Proposal**: `{file_name}_retry_{attempt}` or use `batch_id` as key

### 5.6 Concurrent Processing
Multiple files can have concurrent batches:
- file1.json → batch_001 (retry 1)
- file2.json → batch_002 (no retry needed)
- file3.json → batch_003 (retry 1, retry 2)

**Handle**: Each file's batch chain is independent.

### 5.7 Status Aggregation
`are_all_jobs_completed()` must consider retry chains:
- Original completed + retry in_progress = NOT complete
- Original completed + all retries completed = COMPLETE

### 5.8 Provider Differences
Different providers have different batch behaviors:
- OpenAI: May return partial results
- Anthropic: May return all-or-nothing
- Gemini: May have different error formats

**Handle**: Provider-agnostic retry logic using `BatchResult` abstraction.

---

## 6. Testing Requirements

### 6.1 Unit Tests
```
tests/unit/llm_invocation/batch/
├── test_batch_retry_orchestrator.py
│   ├── test_should_retry_with_missing_ids
│   ├── test_should_retry_max_attempts_exceeded
│   ├── test_get_retry_records
│   ├── test_prepare_retry_batch
│   └── test_submit_retry_batch
├── test_batch_result_processor_retry.py
│   ├── test_stage_7_triggers_retry
│   └── test_stage_7_skips_when_no_missing
└── test_batch_retry_config.py
    ├── test_from_yaml_bool
    ├── test_from_yaml_preset
    └── test_from_yaml_dict
```

### 6.2 Integration Tests
```
tests/integration/batch/
├── test_retry_flow.py
│   ├── test_end_to_end_retry_chain
│   ├── test_retry_with_partial_success
│   └── test_max_attempts_reached
└── test_cli_retry_command.py
```

### 6.3 Mock Scenarios
1. Provider returns 97/100 results → 3 retry
2. Retry returns 2/3 results → 1 retry
3. Retry returns 0/1 results → max attempts → passthrough
4. Provider returns 0/100 results (full failure)
5. Provider raises exception during retry submit

---

## 7. File Summary

### New Files
| File | Purpose |
|------|---------|
| `batch_retry_orchestrator.py` | Core retry orchestration logic |
| `batch_retry_config.py` | RetryConfig pydantic model |

### Modified Files
| File | Changes |
|------|---------|
| `batch_result_processor.py` | Add stage 7 retry trigger |
| `batch_service.py` | Add retry_batch_job(), wire orchestrator |
| `batch_job_manager.py` | Add chain queries |
| `batch_cli.py` | Add retry command |
| `new_format_schema.py` | Add retry config validation |

### Files to NOT Modify
| File | Reason |
|------|--------|
| `batch_models.py` | Already has retry fields |
| `batch_result_reconciler.py` | Already detects missing |
| `batch_registry_manager.py` | Already preserves retry fields |

---

## 8. Acceptance Criteria (from Issue)

- [ ] Failed records are automatically retried up to N times
- [ ] Retry batches are linked to parent batches
- [ ] `agac batch status` shows retry chain status
- [ ] Retry policy is configurable in workflow YAML
- [ ] Documentation updated

---

## 9. Open Questions

1. **Retry naming**: `batch_001_r1` vs `batch_001_retry_1` vs UUID?
2. **Context map strategy**: Filtered copy vs reference to original?
3. **Async vs sync retry**: Trigger immediately or wait for next `--batch_continue`?
4. **Error categorization**: Which errors are retriable?
5. **Backoff for batches**: Is exponential backoff useful for batch processing?

---

## 10. Implementation Order

1. **Phase 1**: Core retry logic
   - `BatchRetryOrchestrator` class
   - Unit tests for orchestrator

2. **Phase 2**: Integration
   - Wire into `BatchResultProcessor`
   - Wire into `BatchService`
   - Integration tests

3. **Phase 3**: CLI
   - Add `batch retry` command
   - Enhance `batch status` output

4. **Phase 4**: Configuration
   - `RetryConfig` model
   - Schema validation
   - YAML examples

5. **Phase 5**: Documentation
   - Update batch processing docs
   - Add retry examples
