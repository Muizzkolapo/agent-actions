---
title: Retry & Error Handling
sidebar_position: 6
---

# Retry & Error Handling

Retry handles transient errors (rate limits, network issues, server errors) with exponential backoff. An online action waits up to `base_delay` (1 second unless you set it) after the first failed attempt, up to twice that after the second, and so on, doubling up to `max_delay` (60 seconds unless you set it); each wait is a random time between zero and that limit.

When a rate-limit error carries the provider's `Retry-After` (read from OpenAI, Anthropic and Groq errors, and from a [declared endpoint](../configuration/endpoints.md)'s), the action waits exactly that long instead, as `retry-after-ms`, seconds or an HTTP date. A request for longer than `max_delay` waits `max_delay` and logs a warning with both numbers. The OpenAI, Anthropic and Groq SDKs retry twice on their own before the error reaches this retry, so a rate-limited request can be sent more times than `max_attempts`.

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
| `base_delay` | float | `1.0` | Seconds the backoff may wait after the first failed attempt; the limit doubles after each one (more than 0, at most 300). Online actions only. |
| `max_delay` | float | `60.0` | The longest wait in seconds, a provider's `Retry-After` included (more than 0, at most 3600, and at least `base_delay`). Online actions only. |

### Exhaustion Behavior

| Value | Behavior |
|-------|----------|
| `return_last` | The record is marked `exhausted`, no response is kept, and the workflow continues |
| `raise` | Raise exception, workflow fails |

A record that exhausted its retries carries the error its last attempt raised, ahead of the
count, wherever it is reported: the run's line for the action, `agac status`, and
`agac dispositions` (its record-level detail too). An action whose every record exhausted
fails with that error rather than with the count alone:

```text
✗ summarize  Action 'summarize': items.json: openai network error: Connection error. — retry
  exhausted after 2 attempts — Action 'summarize' produced 0 successful records — …
```

The record's `_recovery.retry` holds it as `last_error`. An error with no message of its own
is named by its type.

## Retryable Errors

| Error Type | Examples | Retryable |
|------------|----------|-----------|
| Rate Limits | HTTP 429, quota exceeded | Yes |
| Network Issues | Connection refused, reset or dropped mid-response, timeout (including a request that outlasts [`request_timeout`](../configuration/index.md#request-timeout)), DNS failure | Yes |
| Server Errors | HTTP 500, 502, 503, 504 | Yes; which other statuses depends on the provider ([by provider](#provider-support)) |
| Transient request rejection | A request the provider refuses with a message containing `could not parse the JSON body` or `we are currently processing your json schema` | Yes |
| Invalid Request | Bad API key, malformed input | No |
| Schema Violation | Invalid JSON output | No (uses `expect:` repair) |

:::info
For invalid LLM outputs, Agent Actions uses the [expectations](../validation/expectations.md) repair loop instead of retry.
:::

## Provider Support

Provider-specific errors are normalized into unified `RateLimitError` and `NetworkError` types, and those two are retried. Connection failures are retried for every provider. Which HTTP statuses are retried depends on how the provider's SDK reports them:

| Provider | Rate limit (429) | Server errors |
|----------|------------------|---------------|
| OpenAI, Groq | Retried | Any HTTP 5xx retried |
| Anthropic | Retried | Any HTTP 5xx retried, 529 (overloaded) included |
| Gemini, Cohere, Ollama | Retried | HTTP 500, 502, 503, 504 retried |

A status the table does not mark as retried is not retried. One exception: a [declared endpoint](../configuration/endpoints.md) with `auth.command` answers a 401 by running the command once more and retrying that call once, so an expired token is renewed; a second 401 fails the record.

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
