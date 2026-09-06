---
title: Retry & Error Handling
sidebar_position: 6
---

# Retry & Error Handling

Retry handles transient errors (rate limits, network issues, server errors) automatically with exponential backoff.

Retry is **enabled by default** (`enabled: true`). The `retry:` block is optional — omitting it leaves retry on with the framework's default attempt count (`3`) and `return_last` exhaustion behavior. To opt out, set `enabled: false` explicitly.

## Configuration

```yaml
defaults:
  retry:
    enabled: true        # default — shown for clarity, can be omitted
    max_attempts: 3
    on_exhausted: return_last

actions:
  - name: extract_metadata
    retry:
      max_attempts: 5
      on_exhausted: raise

  - name: noisy_endpoint
    retry:
      enabled: false     # explicit opt-out; default is true
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Retry is on by default. Set `enabled: false` to opt out. Other fields below take effect only when `enabled` is `true`. |
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
