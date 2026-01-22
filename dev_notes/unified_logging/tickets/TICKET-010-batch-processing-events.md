# TICKET-010: Add Batch Processing Events

**Status:** ✅ DONE
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, batch, instrumentation

## Description

Instrument batch processing to fire events for job submission, progress updates, and completion.

## Deliverables

- [x] Fire `BatchSubmittedEvent` when batch job created
- [x] Fire `BatchProgressEvent` on progress updates
- [x] Fire `BatchCompleteEvent` when batch finishes

## Files Modified

```
agent_actions/llm/batch/services/submission.py
agent_actions/llm/batch/services/processing.py
```

## Event Data

### BatchSubmittedEvent (B001)

```python
fire_event(BatchSubmittedEvent(
    batch_id="batch_abc123",
    agent_name="test_agent",
    request_count=100,
    provider="openai",
))
```

### BatchProgressEvent (B002)

```python
fire_event(BatchProgressEvent(
    batch_id="batch_abc123",
    completed=45,
    total=100,
    failed=2,
))
```

### BatchCompleteEvent (B003)

```python
fire_event(BatchCompleteEvent(
    batch_id="batch_abc123",
    agent_name="test_agent",
    completed=98,
    failed=2,
    elapsed_time=3600.5,
))
```

## Progress Update Frequency

Fire progress events at these intervals:
- Every 10% completion
- Every 60 seconds (whichever comes first)
- On completion

## Acceptance Criteria

- [x] Batch submission fires event with job details
- [x] Progress updates visible in console
- [x] Completion includes success/failure counts
- [x] Events correlate with workflow via invocation_id

## Implementation Notes

### BatchSubmittedEvent (B001)
- Fired in `BatchSubmissionService._submit_to_provider()` after successful batch submission
- Includes batch_id, agent_name (batch_name), request_count, and provider

### BatchProgressEvent (B002)
- Fired in `BatchProcessingService._wait_for_batch_completion()` during polling
- Triggers on 10% progress increments OR every 60 seconds (whichever comes first)
- Requires provider to implement `get_batch_progress()` method for progress data

### BatchCompleteEvent (B003)
- Fired in `BatchProcessingService._process_single_batch_file()` after processing completes
- Includes batch_id, agent_name, completed count, failed count, and elapsed_time

### Correlation
- Events automatically receive `invocation_id` from EventManager context
- This enables correlation with workflow events through the logging infrastructure
