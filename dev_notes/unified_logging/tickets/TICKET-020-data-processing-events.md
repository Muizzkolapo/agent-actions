# TICKET-020: Add Data Processing Events

**Status:** 🔲 TODO
**Priority:** High
**Estimate:** 5-6 hours
**Labels:** logging, data, pipeline

## Description

Add comprehensive event instrumentation for data processing operations to provide visibility into data transformation pipelines, file I/O, validation, and record processing loops.

## Deliverables

- [ ] Record processing pipeline events
- [ ] Batch processing events
- [ ] File I/O events
- [ ] Data validation events
- [ ] Schema operation events
- [ ] Data transformation events
- [ ] Result collection events

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

- [ ] Record processing stages fire events
- [ ] Batch progress visible every N records
- [ ] File I/O tracked with sizes
- [ ] Validation results fire events
- [ ] Enrichment pipeline stages tracked
- [ ] Result collection summary available
- [ ] Events appear in debug logs with `-v`
