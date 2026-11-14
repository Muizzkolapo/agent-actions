---
title: Retry & Error Handling
sidebar_position: 6
---

# Retry & Error Handling

Retry sends a request again after a transient error, with exponential backoff. A transient error is a rate limit, a network problem or a server error. After each failed attempt, an online action waits for a random time between zero and a limit. After the first failed attempt, the limit is `base_delay` (1 second if you do not set it). After each subsequent failed attempt, the limit doubles, to a maximum of `max_delay` (60 seconds if you do not set it).

A rate-limit error can carry a `Retry-After` value from the provider. Agent Actions reads this value from OpenAI, Anthropic and Groq errors, and from the errors of a [declared endpoint](../configuration/endpoints.md). If the error carries the value, the action waits for exactly that time, in place of the random wait. The value can be `retry-after-ms`, seconds or an HTTP date. If the value is longer than `max_delay`, the action waits for `max_delay`. The action also logs a warning that shows the two numbers.

The OpenAI, Anthropic and Groq SDKs retry two times before the error gets to the retry of Agent Actions. Thus the number of sends of a rate-limited request can be more than `max_attempts`.

Retry is **disabled until a `retry:` block enables it**. You can put the block on the action or
under `defaults:`. A block under `defaults:` applies to each action that does not have its own
block. Inside a block, these values apply if you do not set them: `enabled` is `true`,
`max_attempts` is `3` and `on_exhausted` is `return_last`. Thus `retry: {max_attempts: 3}` is
sufficient. If a `defaults:` block enables retry, set `enabled: false`, or `retry: false`, to
disable retry for one action.

If retry is disabled, a transport error fails its record at the first attempt. A record that a
batch provider does not include in its results fails with the reason `batch_not_returned`. In
the two cases, the status of the record is `failed`, and [`agac retry`](../cli/retry) sends the
record again.

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
| `enabled` | bool | `true` | A `retry:` block enables retry, unless the block sets `enabled: false`. The other fields in this table have an effect only when `enabled` is `true`. |
| `max_attempts` | int | `3` | The total number of attempts for each record, which includes the first call or the first batch (1-10). `1` does not retry. |
| `on_exhausted` | string | `return_last` | The behavior when a record exhausted its retries |
| `base_delay` | float | `1.0` | The number of seconds that the backoff may wait after the first failed attempt. The limit doubles after each failed attempt. The value is more than 0 and not more than 300. Online actions only. |
| `max_delay` | float | `60.0` | The longest wait in seconds, which includes a `Retry-After` value from a provider. The value is more than 0, not more than 3600, and not less than `base_delay`. Online actions only. |

### Exhaustion Behavior

| Value | Behavior |
|-------|----------|
| `return_last` | Agent Actions marks the record `exhausted` and keeps no response. The workflow continues. |
| `raise` | Agent Actions raises an exception, and the workflow fails. |

A record that exhausted its retries carries the error from its last attempt. Each report of
the record shows this error before the count. These reports are the line for the action in
the run output, `agac status`, and `agac dispositions` (which includes its record-level
detail). If each record of an action exhausted its retries, the action fails with that error,
not with the count only:

```text
✗ summarize  Action 'summarize': items.json: openai network error: Connection error. — retry
  exhausted after 2 attempts — Action 'summarize' produced 0 successful records — …
```

The `_recovery.retry` field of the record holds the error as `last_error`. If an error has no
message of its own, the report names the error by its type.

## Retryable Errors

| Error Type | Examples | Retryable |
|------------|----------|-----------|
| Rate Limits | HTTP 429, quota exceeded | Yes |
| Network Issues | A refused connection. A connection that resets or drops during the response. A timeout, which includes a request that takes longer than [`request_timeout`](../configuration/index.md#request-timeout). A DNS failure. | Yes |
| Server Errors | HTTP 500, 502, 503, 504 | Yes. The other statuses that Agent Actions retries depend on the provider ([by provider](#provider-support)). |
| Transient request rejection | A request that the provider refuses with a message that contains `could not parse the JSON body` or `we are currently processing your json schema` | Yes |
| Cut-off answer | A non-JSON response that holds no answer because the output budget ran out (`stop_reason=max_tokens`, or `length`). The error is a `ResponseTruncatedError` that names the stop reason. See [Vendor parameters](../configuration/index.md#vendor-parameters) | Yes |
| Invalid Request | A bad API key, malformed input | No |
| Schema Violation | Invalid JSON output | No (the `expect:` repair loop handles it) |

:::note
For invalid LLM outputs, Agent Actions uses the [expectations](../validation/expectations.md) repair loop, not retry.
:::

## Provider Support

Agent Actions normalizes the errors of each provider into the unified types `RateLimitError` and `NetworkError`, and retries these two types. Agent Actions retries connection failures for all providers. The HTTP statuses that Agent Actions retries depend on how the SDK of the provider reports them:

| Provider | Rate limit (429) | Server errors |
|----------|------------------|---------------|
| OpenAI, Groq | Retried | Any HTTP 5xx retried |
| Anthropic | Retried | Any HTTP 5xx retried, which includes 529 (overloaded) |
| Gemini, Cohere, Ollama | Retried | HTTP 500, 502, 503, 504 retried |

Agent Actions does not retry a status that the table does not mark as retried. There is one exception. If a [declared endpoint](../configuration/endpoints.md) with `auth.command` gets a 401, Agent Actions runs the command one more time. Then Agent Actions retries that call one time. Thus Agent Actions renews an expired token. A second 401 fails the record.

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

- [Expectations](../validation/expectations.md) - How to handle invalid LLM outputs
- [Run Modes](./run-modes.md) - Batch execution and online execution
