---
title: Internal Defaults
sidebar_position: 2
---

# Internal Defaults

One module, `agent_actions/config/defaults.py`, holds the magic numbers and the hardcoded constants. Each consumer refers to a named constant, not to a bare literal. Thus you can find, document and change the defaults in one place.

## Design

The module contains plain classes. Each class has class attributes for one domain. The module has **zero imports**. Thus you can safely import it from any location in the codebase, with no risk of circular dependencies.

```python
from agent_actions.config.defaults import OllamaDefaults

base_url = os.getenv("OLLAMA_HOST", OllamaDefaults.BASE_URL)
```

## Domains

### StorageDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `SQLITE_LOCK_TIMEOUT_SECONDS` | float | `30.0` | The wait time for SQLite database locks |
| `PROMPT_TRACE_RETENTION_RUNS` | int | `10` | The number of most recent calendar days of prompt traces to keep. The name says runs, but the unit is days, not runs. `0` never prunes |
| `SOURCE_DATA_TTL_DAYS` | int\|None | `None` | The number of days to keep source data. `None` means keep forever |

### LockDefaults

File locks use one timeout. This timeout is the atomic (exclusive read-modify-write) timeout. The run tracker reads it.

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `ATOMIC_LOCK_TIMEOUT_SECONDS` | float | `10.0` | The timeout for exclusive read-modify-write locks |

### OllamaDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BASE_URL` | str | `http://localhost:11434` | The default URL of the Ollama server |
| `BATCH_MAX_WORKERS` | int | `1` | The maximum number of concurrent workers for Ollama batch processing |

The `OLLAMA_HOST` environment variable overrides the base URL. The `base_url` of an action overrides the two values.

### OllamaCloudDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BASE_URL` | str | `https://ollama.com` | The default URL of the Ollama Cloud API |
| `BATCH_MAX_WORKERS` | int | `1` | The maximum number of concurrent workers for Ollama Cloud batch processing |

The Ollama Cloud batch client reads the `OLLAMA_CLOUD_HOST` environment variable before it uses `BASE_URL`. The two Ollama batch clients get the worker count from these sources, in this order:

1. The `batch_max_workers` of the action.
2. The `OLLAMA_BATCH_MAX_WORKERS` environment variable.
3. `BATCH_MAX_WORKERS`.

### ApiDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_RESPONSE_BYTES` | int | `10 * 1024 * 1024` | The safety limit on the size of an API response (10 MB) |
| `REQUEST_TIMEOUT_SECONDS` | int | `30` | The HTTP request timeout when Agent Actions gets data from a data source |

### SeedDataDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_FILE_SIZE_BYTES` | int | `10 * 1024 * 1024` | The maximum size of a seed or static data file (10 MB) |

### PromptDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_PROMPT_SIZE_BYTES` | int | `100 * 1024` | The maximum size of a prompt file for validation (100 KB) |

### DocsDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `README_MAX_BYTES` | int | `100 * 1024` | The maximum README content that catalog.json includes (100 KB) |
| `EVENT_TAIL_LIMIT` | int | `2000` | The number of most recent events that each log keeps for catalog.json. Every log shares one window of this size |
| `EVENT_PROBLEM_LIMIT` | int | `500` | The number of problem events kept per level, per log. This number adds to the recency window. Thus a log keeps up to 500 warnings *and* 500 errors. Rare old problems still reach the window |

## Naming Conventions

- The `_SECONDS` / `_BYTES` suffixes make the units explicit.
- Constants use `UPPER_SNAKE_CASE`.
- Each class holds the related defaults of one subsystem.

## Adding New Defaults

1. Add a constant to the class of its domain. If the domain is new, create a new class.
2. Keep the module free of imports.
3. Update the consumer to refer to the constant.
4. Update this page.

## See Also

- [Configuration](../configuration/) — User-facing workflow configuration
- [Architecture](./) — System architecture overview
