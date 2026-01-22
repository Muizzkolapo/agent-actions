# TICKET-009: Add LLM Provider Events

**Status:** 🔲 TODO
**Priority:** High
**Estimate:** 2-3 hours
**Labels:** logging, llm, instrumentation

## Description

Instrument LLM provider classes to fire events for API requests, responses, and errors. This provides visibility into LLM interactions and enables token tracking.

## Deliverables

- [ ] Fire `LLMRequestEvent` before API calls
- [ ] Fire `LLMResponseEvent` after successful calls
- [ ] Fire `LLMErrorEvent` on API errors
- [ ] Fire `RateLimitEvent` when rate limited

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

- [ ] All LLM calls fire request/response events
- [ ] Token counts are accurate
- [ ] Errors are properly captured
- [ ] Events appear in JSON logs
