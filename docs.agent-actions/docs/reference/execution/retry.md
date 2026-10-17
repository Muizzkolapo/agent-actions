---
title: Retry & Error Handling
sidebar_position: 6
---

# Retry & Error Handling

Retry handles transient errors (rate limits, network issues, server errors) with exponential backoff.

Retry is **off until a `retry:` block turns it on**, on the action or under `defaults:`, where
it applies to every action that writes no block of its own. Inside a block, `enabled` is `true`,
`max_attempts` is `3` and `on_exhausted` is `return_last` unless you set them, so
`retry: {max_attempts: 3}` is enough. `enabled: false`, or `retry: false`, turns it off for one
action under a `defaults:` block that turns it on.

Without retry, a transport error fails its record at the first attempt, and a record a batch
provider leaves out of its results is failed with the reason `batch_not_returned`. Either way
the record is `failed`, and [`agac retry`](../cli/retry) sends it again.

## Configuration

```yaml
defaults:
  retry:
    enabled: true        # the default inside a retry: block, shown for clarity
    max_attempts: 3
    on_exhausted: return_last

actions:
  - name: extract_metadata
    retry:
      max_attempts: 5
      on_exhausted: raise

  - name: noisy_endpoint
    retry:
      enabled: false     # opts this action out of the defaults: block
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | A `retry:` block turns retry on unless it sets `enabled: false`. Other fields below take effect only when `enabled` is `true`. |
| `max_attempts` | int | `3` | Attempts per record in all, the first call or batch included (1-10). `1` never retries. |
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
| Network Issues | Connection refused, reset or dropped mid-response, timeout, DNS failure | Yes |
| Server Errors | HTTP 502, 503, 504 | Yes |
| Invalid Request | Bad API key, malformed input | No |
| Schema Violation | Invalid JSON output | No (uses `expect:` repair) |

:::info
For invalid LLM outputs, Agent Actions uses the [expectations](../validation/expectations.md) repair loop instead of retry.
:::

## Provider Support

All provider-specific errors are normalized into unified `RateLimitError` and `NetworkError` types, ensuring consistent retry behavior across OpenAI, Anthropic, Gemini, Cohere, Groq, and Ollama.

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

- [Expectations](../validation/expectations.md) - Handling invalid LLM outputs
- [Run Modes](./run-modes.md) - Batch vs online execution
