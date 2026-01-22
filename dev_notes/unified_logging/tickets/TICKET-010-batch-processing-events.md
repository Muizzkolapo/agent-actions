# TICKET-010: Add Batch Processing Events

**Status:** 🔲 TODO
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, batch, instrumentation

## Description

Instrument batch processing to fire events for job submission, progress updates, and completion.

## Deliverables

- [ ] Fire `BatchSubmittedEvent` when batch job created
- [ ] Fire `BatchProgressEvent` on progress updates
- [ ] Fire `BatchCompleteEvent` when batch finishes

## Files to Modify

```
agent_actions/batch/processor.py
agent_actions/batch/manager.py
```

## Event Data

### BatchSubmittedEvent (B001)

```python
fire_event(BatchSubmittedEvent(
    batch_id="batch_abc123",
    total_items=100,
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
    total_items=100,
    successful=98,
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

- [ ] Batch submission fires event with job details
- [ ] Progress updates visible in console
- [ ] Completion includes success/failure counts
- [ ] Events correlate with workflow via invocation_id
