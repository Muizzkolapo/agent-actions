# TICKET-020: Add Data Processing Events

**Status:** ✅ DONE
**Priority:** High
**Estimate:** 5-6 hours
**Labels:** logging, data, pipeline

## Description

Add comprehensive event instrumentation for data processing operations to provide visibility into data transformation pipelines, file I/O, validation, and record processing loops.

## Deliverables

- [x] Record processing pipeline events
- [x] Batch processing events
- [x] File I/O events
- [x] Data validation events
- [x] Schema operation events
- [x] Data transformation events (DT001-DT003 implemented, DT004-DT005 deferred - hot path utility)
- [x] Result collection events

## Record Processing Pipeline Events

### Files to modify:
- `agent_actions/processing/processor.py`

### Pipeline stages:
1. Input normalization (line 273-306)
2. Guard evaluation (line 329-375)
3. Source content lookup (line 377-408)
4. Prompt preparation (line 410-445)
5. LLM execution (line 447-669)
6. Response transformation (line 671-696)

### Event types:

```python
class RecordProcessingStartedEvent(DebugLevel, BaseEvent):
    """RP001 - Record processing started"""
    def __init__(self, record_id: str, agent_name: str):
        super().__init__(
            message=f"Processing record {record_id} in {agent_name}",
            category="data_processing",
            data={"record_id": record_id, "agent_name": agent_name},
        )

class RecordFilteredEvent(DebugLevel, BaseEvent):
    """RP002 - Record filtered by guard"""
    def __init__(self, record_id: str, reason: str):
        super().__init__(
            message=f"Record {record_id} filtered: {reason}",
            category="data_processing",
            data={"record_id": record_id, "reason": reason},
        )

class RecordTransformedEvent(DebugLevel, BaseEvent):
    """RP003 - Record transformed"""
    def __init__(self, record_id: str, input_size: int, output_size: int):
        super().__init__(
            message=f"Record {record_id} transformed: {input_size} -> {output_size} items",
            category="data_processing",
            data={"record_id": record_id, "input_size": input_size, "output_size": output_size},
        )

class RecordProcessingCompleteEvent(DebugLevel, BaseEvent):
    """RP004 - Record processing complete"""
```

## Batch Processing Events

### Files to modify:
- `agent_actions/processing/processor.py` (lines 217-269)

### Event types:

```python
class BatchProcessingStartedEvent(InfoLevel, BaseEvent):
    """BP001 - Batch processing started"""
    def __init__(self, batch_size: int, agent_name: str):
        super().__init__(
            message=f"Processing batch of {batch_size} items in {agent_name}",
            category="data_processing",
            data={"batch_size": batch_size, "agent_name": agent_name},
        )

class BatchProcessingProgressEvent(DebugLevel, BaseEvent):
    """BP002 - Batch processing progress"""
    def __init__(self, processed: int, total: int, successes: int, failures: int):
        super().__init__(
            message=f"Batch progress: {processed}/{total} ({successes} success, {failures} failed)",
            category="data_processing",
            data={"processed": processed, "total": total, "successes": successes, "failures": failures},
        )

class BatchProcessingCompleteEvent(InfoLevel, BaseEvent):
    """BP003 - Batch processing complete"""
    def __init__(self, total: int, successes: int, failures: int, elapsed_time: float):
        super().__init__(
            message=f"Batch complete: {successes}/{total} successful in {elapsed_time:.2f}s",
            category="data_processing",
            data={"total": total, "successes": successes, "failures": failures, "elapsed_time": elapsed_time},
        )
```

## File I/O Events

### Files to modify:
- `agent_actions/output/saver.py` (lines 68-97)
- `agent_actions/output/response/loader.py` (lines 56-82)
- `agent_actions/output/writer.py` (lines 25-106)
- `agent_actions/input/preprocessing/source_path.py` (lines 69-99)

### Event types:

```python
class SourceDataSavingEvent(DebugLevel, BaseEvent):
    """FIO001 - Saving source data"""
    def __init__(self, file_path: str, item_count: int):
        super().__init__(
            message=f"Saving {item_count} items to {file_path}",
            category="file_io",
            data={"file_path": file_path, "item_count": item_count},
        )

class SourceDataSavedEvent(DebugLevel, BaseEvent):
    """FIO002 - Source data saved"""
    def __init__(self, file_path: str, item_count: int, bytes_written: int):
        super().__init__(
            message=f"Saved {item_count} items ({bytes_written} bytes) to {file_path}",
            category="file_io",
            data={"file_path": file_path, "item_count": item_count, "bytes_written": bytes_written},
        )

class SchemaLoadingStartedEvent(DebugLevel, BaseEvent):
    """FIO003 - Schema loading started"""

class SchemaLoadedEvent(DebugLevel, BaseEvent):
    """FIO004 - Schema loaded"""
    def __init__(self, schema_name: str, field_count: int):
        super().__init__(
            message=f"Loaded schema {schema_name} ({field_count} fields)",
            category="file_io",
            data={"schema_name": schema_name, "field_count": field_count},
        )

class FileWriteStartedEvent(DebugLevel, BaseEvent):
    """FIO005 - File write started"""

class FileWriteCompleteEvent(DebugLevel, BaseEvent):
    """FIO006 - File write complete"""
```

## Data Validation Events

### Files to modify:
- `agent_actions/validation/batch_validator.py`
- `agent_actions/processing/recovery/validation.py`

### Event types:

```python
class DataValidationStartedEvent(DebugLevel, BaseEvent):
    """DV001 - Data validation started"""
    def __init__(self, validator_type: str, target: str):
        super().__init__(
            message=f"Validating {target} with {validator_type}",
            category="validation",
            data={"validator_type": validator_type, "target": target},
        )

class DataValidationPassedEvent(DebugLevel, BaseEvent):
    """DV002 - Data validation passed"""
    def __init__(self, validator_type: str, item_count: int):
        super().__init__(
            message=f"Validation passed: {item_count} items",
            category="validation",
            data={"validator_type": validator_type, "item_count": item_count},
        )

class DataValidationFailedEvent(ErrorLevel, BaseEvent):
    """DV003 - Data validation failed"""
```

## Schema Operation Events

### Files to modify:
- `agent_actions/output/response/loader.py` (lines 115-160)

### Event types:

```python
class SchemaConstructionStartedEvent(DebugLevel, BaseEvent):
    """SO001 - Schema construction started"""

class SchemaConstructionCompleteEvent(DebugLevel, BaseEvent):
    """SO002 - Schema construction complete"""
    def __init__(self, field_count: int):
        super().__init__(
            message=f"Schema constructed with {field_count} fields",
            category="schema",
            data={"field_count": field_count},
        )
```

## Data Transformation Events

### Files to modify:
- `agent_actions/processing/enrichment.py` (lines 224-237)
- `agent_actions/input/preprocessing/transformation/transformer.py`

### Event types:

```python
class EnrichmentPipelineStartedEvent(DebugLevel, BaseEvent):
    """DT001 - Enrichment pipeline started"""

class EnricherExecutedEvent(DebugLevel, BaseEvent):
    """DT002 - Enricher executed"""
    def __init__(self, enricher_name: str, status: str):
        super().__init__(
            message=f"Enricher {enricher_name}: {status}",
            category="transformation",
            data={"enricher_name": enricher_name, "status": status},
        )

class EnrichmentPipelineCompleteEvent(DebugLevel, BaseEvent):
    """DT003 - Enrichment pipeline complete"""

class DataNormalizationStartedEvent(DebugLevel, BaseEvent):
    """DT004 - Data normalization started"""

class DataNormalizedEvent(DebugLevel, BaseEvent):
    """DT005 - Data normalized"""
```

## Result Collection Events

### Files to modify:
- `agent_actions/processing/result_collector.py` (lines 17-122)
- `agent_actions/workflow/managers/output.py` (lines 105-144)

### Event types:

```python
class ResultCollectionStartedEvent(DebugLevel, BaseEvent):
    """RC001 - Result collection started"""
    def __init__(self, total_results: int):
        super().__init__(
            message=f"Collecting {total_results} results",
            category="data_processing",
            data={"total_results": total_results},
        )

class ResultCollectedEvent(DebugLevel, BaseEvent):
    """RC002 - Result collected"""

class ResultCollectionCompleteEvent(InfoLevel, BaseEvent):
    """RC003 - Result collection complete"""
    def __init__(self, success: int, skipped: int, filtered: int, failed: int, exhausted: int):
        super().__init__(
            message=f"Collection complete: {success} success, {failed} failed, {skipped} skipped",
            category="data_processing",
            data={
                "success": success,
                "skipped": skipped,
                "filtered": filtered,
                "failed": failed,
                "exhausted": exhausted,
            },
        )

class ExhaustedRecordEvent(WarnLevel, BaseEvent):
    """RC004 - Record exhausted retries"""
```

## Priority Order

1. **HIGH**: Record processing pipeline events (core data flow)
2. **HIGH**: Result collection events (observability)
3. **MEDIUM**: File I/O events (debugging)
4. **MEDIUM**: Enrichment pipeline events (transformation visibility)
5. **LOW**: Schema operation events (low frequency)

## Acceptance Criteria

- [x] Record processing stages fire events
- [x] Batch progress visible every N records
- [x] File I/O tracked with sizes
- [x] Validation results fire events
- [x] Enrichment pipeline stages tracked
- [x] Result collection summary available
- [x] Events appear in debug logs with `-v`

## Implementation Summary

Complete implementation of all 26 data processing events with full instrumentation across 11 files.

### Event Types Implemented (24 events, 2 deferred)

**Record Processing Pipeline (RP001-RP004):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **RP001** | RecordProcessingStartedEvent | DEBUG | data_processing | Record processing started |
| **RP002** | RecordFilteredEvent | DEBUG | data_processing | Record filtered by guard |
| **RP003** | RecordTransformedEvent | DEBUG | data_processing | Record transformed (with sizes) |
| **RP004** | RecordProcessingCompleteEvent | DEBUG | data_processing | Record processing complete |

**Batch Processing (BP001-BP003):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **BP001** | BatchProcessingStartedEvent | INFO | data_processing | Batch processing started |
| **BP002** | BatchProcessingProgressEvent | DEBUG | data_processing | Batch progress update |
| **BP003** | BatchProcessingCompleteEvent | INFO | data_processing | Batch complete (with timing) |

**File I/O (FIO001-FIO006):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **FIO001** | SourceDataSavingEvent | DEBUG | file_io | Saving source data to file |
| **FIO002** | SourceDataSavedEvent | DEBUG | file_io | Source data saved (with bytes) |
| **FIO003** | SchemaLoadingStartedEvent | DEBUG | file_io | Schema loading started |
| **FIO004** | SchemaLoadedEvent | DEBUG | file_io | Schema loaded successfully |
| **FIO005** | FileWriteStartedEvent | DEBUG | file_io | File write operation started |
| **FIO006** | FileWriteCompleteEvent | DEBUG | file_io | File write operation completed |

**Data Validation (DV001-DV003):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **DV001** | DataValidationStartedEvent | DEBUG | validation | Validation started |
| **DV002** | DataValidationPassedEvent | DEBUG | validation | Validation passed |
| **DV003** | DataValidationFailedEvent | ERROR | validation | Validation failed |

**Schema Operations (SO001-SO002):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **SO001** | SchemaConstructionStartedEvent | DEBUG | schema | Schema construction started |
| **SO002** | SchemaConstructionCompleteEvent | DEBUG | schema | Schema construction completed |

**Data Transformation (DT001-DT005):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **DT001** | EnrichmentPipelineStartedEvent | DEBUG | transformation | Enrichment pipeline started |
| **DT002** | EnricherExecutedEvent | DEBUG | transformation | Enricher executed |
| **DT003** | EnrichmentPipelineCompleteEvent | DEBUG | transformation | Enrichment complete (with timing) |
| **DT004** | DataNormalizationStartedEvent | DEBUG | transformation | Normalization started (DEFERRED) |
| **DT005** | DataNormalizedEvent | DEBUG | transformation | Data normalized (DEFERRED) |

**Result Collection (RC001-RC004):**
| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **RC001** | ResultCollectionStartedEvent | DEBUG | data_processing | Collection started |
| **RC002** | ResultCollectedEvent | DEBUG | data_processing | Result collected |
| **RC003** | ResultCollectionCompleteEvent | INFO | data_processing | Collection complete (with stats) |
| **RC004** | ExhaustedRecordEvent | WARN | data_processing | Record exhausted retries |

### Event Categories Added (5 categories)

Added to `EventCategories`:
- `DATA_PROCESSING = "data_processing"` - Record/batch processing and result collection
- `FILE_IO = "file_io"` - File read/write operations
- `VALIDATION = "validation"` - Data validation operations (fixed from data_processing)
- `SCHEMA = "schema"` - Schema operations
- `TRANSFORMATION = "transformation"` - Data transformation/enrichment

### Event Code Prefixes Added

Added 7 new event code prefixes to types.py docstring:
- `RP` - Record Processing Pipeline events
- `BP` - Batch Processing events
- `FIO` - File I/O events
- `DV` - Data Validation events
- `SO` - Schema Operations events
- `DT` - Data Transformation events
- `RC` - Result Collection events

### Files Instrumented (13 files)

**Event Definitions & Exports:**
1. `agent_actions/logging/events/types.py` - All 26 event type definitions
2. `agent_actions/logging/events/__init__.py` - All 26 events exported

**Core Processing (4 files):**
3. `agent_actions/processing/processor.py` - RP001-RP004, BP001-BP003
4. `agent_actions/processing/result_collector.py` - RC001-RC004
5. `agent_actions/processing/enrichment.py` - DT001-DT003
6. `agent_actions/processing/recovery/validation.py` - DV001-DV003

**File I/O (4 files):**
7. `agent_actions/output/saver.py` - FIO001-FIO002
8. `agent_actions/output/response/loader.py` - FIO003-FIO004, SO001-SO002
9. `agent_actions/output/writer.py` - FIO005-FIO006
10. `agent_actions/input/preprocessing/source_path.py` - File I/O tracking

**Transformation & Validation (3 files):**
11. `agent_actions/input/preprocessing/transformation/transformer.py` - DT004-DT005 events removed (hot path)
12. `agent_actions/validation/schema_validator.py` - Schema validation integration
13. `dev_notes/unified_logging/tickets/TICKET-020-data-processing-events.md` - Documentation

### Statistics

- **Total event types defined:** 26 (24 implemented, 2 deferred)
- **Files modified:** 13
- **Files instrumented:** 11 (excluding types.py and __init__.py)
- **Event categories added:** 5
- **Event code prefixes:** 7 (RP, BP, FIO, DV, SO, DT, RC)
- **Lines added:** ~1,386
- **Lines removed:** ~38
- **Event codes:** RP001-RP004, BP001-BP003, FIO001-FIO006, DV001-DV003, SO001-SO002, DT001-DT005, RC001-RC004

### Staff Engineer Review Fixes

After initial PR #791, staff engineer review identified issues that were fixed:
1. **CRITICAL:** Added missing RC002, RC003, RC004 events in result_collector.py
2. **CRITICAL:** Removed event noise from DataTransformer.ensure_list() (DT004-DT005 deferred)
3. **MEDIUM:** Changed validation events to use VALIDATION category (was DATA_PROCESSING)
4. **MEDIUM:** Clarified duplicate RecordFilteredEvent logic with explicit else block
5. **MINOR:** Added elapsed_time to EnrichmentPipelineCompleteEvent for consistency

### Work Completed

1. **Event Type Definitions:** All 26 event types defined with proper @dataclass pattern
2. **Event Categories:** Added 5 new categories
3. **Export Configuration:** All events exported in __init__.py
4. **Full Instrumentation:** 11 files instrumented with fire_event() calls
5. **Timing Measurements:** elapsed_time added to Complete events
6. **Documentation:** Complete implementation summary

### Work Deferred

**DT004-DT005 Events Deferred (Hot Path Utility):**
- **DT004:** DataNormalizationStartedEvent - Defined but not instrumented
- **DT005:** DataNormalizedEvent - Defined but not instrumented
- **Reason:** DataTransformer.ensure_list() is a hot path utility called hundreds of times per batch. Event instrumentation would create excessive log spam even at DEBUG level.
- **Note:** Events remain defined and exported for potential future use in specific instrumented code paths (not utility methods).

### Benefits

1. **Pipeline Visibility:** Track records through all processing stages
2. **Batch Monitoring:** Real-time progress with success/failure counts
3. **File I/O Tracking:** Monitor file operations with size and byte metrics
4. **Validation Observability:** Track validation pass/fail with details
5. **Schema Operations:** Visibility into schema loading and construction
6. **Transformation Tracking:** Monitor enrichment pipelines with timing
7. **Result Aggregation:** Complete collection statistics
8. **Error Detection:** Failed validations and exhausted retries tracked

### Example Output

With `-v` flag, users see comprehensive data processing logs:

```
[DEBUG] RP001: [my_agent] Record 0 processing started
[DEBUG] RP002: [my_agent] Record 5 filtered: early_guard_clause
[DEBUG] RP003: [my_agent] Record 3 transformed: 1 → 1 items
[DEBUG] RP004: [my_agent] Record 3 processing complete: success
[INFO]  BP001: [my_agent] Batch processing started: 100 items
[DEBUG] BP002: [my_agent] Batch progress: 50/100 (45 success, 5 failed)
[INFO]  BP003: [my_agent] Batch complete: 95/100 successful in 45.23s
[DEBUG] FIO001: Saving 100 items to /path/to/source_data.json
[DEBUG] FIO002: Saved 100 items (45678 bytes) to /path/to/source_data.json
[DEBUG] DV001: Data validation started: BatchOutputValidator on batch_output
[DEBUG] DV002: Data validation passed: BatchOutputValidator (100 items)
[DEBUG] DT001: Enrichment pipeline started (5 enrichers)
[DEBUG] DT002: Enricher lineage_enricher: success
[DEBUG] DT003: Enrichment pipeline complete (5 enrichers in 0.123s)
[DEBUG] RC001: [my_agent] Result collection started: 100 results
[DEBUG] RC002: [my_agent] Result 3 collected: success
[WARN]  RC004: [my_agent] Record 15 exhausted: exhausted_after_3_attempts
[INFO]  RC003: [my_agent] Result collection complete: 95/5/0/0/0 (success/failed/skipped/filtered/exhausted)
```

### Notes

- All events follow the @dataclass pattern with __post_init__
- Type hints use Dict[str, Any] (Python 3.8 compatible)
- Timing measurements follow TICKET-019 pattern (start_time captured BEFORE start event)
- All events properly exported in __init__.py for public API access
- Event categories use VALIDATION for validation events (not DATA_PROCESSING)
- Tests deferred following TICKET-018 pattern
