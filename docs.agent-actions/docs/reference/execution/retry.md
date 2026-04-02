---
title: Retry & Error Handling
sidebar_position: 6
---

# Retry & Error Handling

Retry handles transient errors (rate limits, network issues, server errors) automatically with exponential backoff.

## Configuration

```yaml
defaults:
  retry:
    enabled: true
    max_attempts: 3
    on_exhausted: return_last

actions:
  - name: extract_metadata
    retry:
      max_attempts: 5
      on_exhausted: raise
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable retry |
| `max_attempts` | int | `3` | Maximum attempts (1-10) |
| `on_exhausted` | string | `return_last` | Behavior when retries exhausted |

### Exhaustion Behavior

| Value | Behavior |
|-------|----------|
| `return_last` | Return last response, workflow continues |
| `raise` | Raise exception, workflow fails |

## Retryable Errors

| Error Type | Examples | Retryable |
|------------|----------|-----------|
| Rate Limits | HTTP 429, quota exceeded | Yes |
| Network Issues | Connection timeout, DNS failure | Yes |
| Server Errors | HTTP 502, 503, 504 | Yes |
| Invalid Request | Bad API key, malformed input | No |
| Schema Violation | Invalid JSON output | No (uses reprompt) |

:::info
For invalid LLM outputs, Agent Actions uses [reprompting](../validation/reprompting.md) instead of retry.
:::

## Provider Support

All provider-specific errors are normalized into unified `RateLimitError` and `NetworkError` types, ensuring consistent retry behavior across OpenAI, Anthropic, Gemini, Cohere, Mistral, Groq, and Ollama.

## Best Practices

**Use `raise` for CI/CD:**
```yaml
retry:
  max_attempts: 3
  on_exhausted: raise
```

**Use `return_last` for partial results:**
```yaml
retry:
  max_attempts: 3
  on_exhausted: return_last
```

## See Also

- [Failure Handling](./failure-handling.md) - Partial failures, `on_partial_failure`, and the execution tally
- [Reprompting](../validation/reprompting.md) - Handling invalid LLM outputs
- [Run Modes](./run-modes.md) - Batch vs online execution
