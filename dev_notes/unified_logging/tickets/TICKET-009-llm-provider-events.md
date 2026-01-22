# TICKET-009: Add LLM Provider Events

**Status:** ✅ DONE
**Priority:** High
**Estimate:** 2-3 hours
**Labels:** logging, llm, instrumentation
**PR:** https://github.com/Muizzkolapo/agent-actions/pull/778

## Description

Instrument LLM provider classes to fire events for API requests, responses, and errors. This provides visibility into LLM interactions and enables token tracking.

## Deliverables

- [x] Fire `LLMRequestEvent` before API calls
- [x] Fire `LLMResponseEvent` after successful calls
- [x] Fire `LLMErrorEvent` on API errors
- [x] Fire `RateLimitEvent` when rate limited

## Files to Modify

```
agent_actions/llm/providers/openai_provider.py
agent_actions/llm/providers/anthropic_provider.py
agent_actions/llm/providers/base.py
```

## Event Data

### LLMRequestEvent (L001)

```python
fire_event(LLMRequestEvent(
    provider="openai",
    model="gpt-4",
    prompt_tokens=500,
    request_id="req-123",
))
```

### LLMResponseEvent (L002)

```python
fire_event(LLMResponseEvent(
    provider="openai",
    model="gpt-4",
    prompt_tokens=500,
    completion_tokens=1200,
    total_tokens=1700,
    latency_ms=2500,
    request_id="req-123",
))
```

### LLMErrorEvent (L003)

```python
fire_event(LLMErrorEvent(
    provider="openai",
    model="gpt-4",
    error_type="APIError",
    error_message="Rate limit exceeded",
    request_id="req-123",
))
```

### RateLimitEvent (L004)

```python
fire_event(RateLimitEvent(
    provider="openai",
    retry_after=60,
    request_id="req-123",
))
```

## Implementation Notes

- Events should fire at provider level, not client level
- Include request_id for correlation
- Track token counts for cost analysis
- Log latency for performance monitoring

## Acceptance Criteria

- [x] All LLM calls fire request/response events
- [x] Token counts are accurate
- [x] Errors are properly captured
- [x] Events appear in JSON logs
