---
title: Internal Defaults
sidebar_position: 2
---

# Internal Defaults

Magic numbers and hardcoded constants are centralized in a single module — `agent_actions/config/defaults.py` — so every consumer references a named constant instead of a bare literal. This makes defaults discoverable, documented, and changeable in one place.

## Design

The module contains plain classes with class attributes grouped by domain. It has **zero imports**, which means it can be safely imported from anywhere in the codebase without circular-dependency risk.

```python
from agent_actions.config.defaults import OllamaDefaults

base_url = os.getenv("OLLAMA_HOST", OllamaDefaults.BASE_URL)
```

## Domains

### StorageDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `SQLITE_LOCK_TIMEOUT_SECONDS` | float | `30.0` | Wait time for SQLite database locks |
| `PROMPT_TRACE_RETENTION_RUNS` | int | `10` | Number of most recent calendar days of prompt traces to keep; despite the name, the unit is days, not runs. `0` never prunes |
| `SOURCE_DATA_TTL_DAYS` | int\|None | `None` | Days to retain source data; `None` means keep forever |

### LockDefaults

File locks use one timeout: the atomic (exclusive read-modify-write) timeout, read by the run tracker.

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `ATOMIC_LOCK_TIMEOUT_SECONDS` | float | `10.0` | Timeout for exclusive read-modify-write locks |

### OllamaDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BASE_URL` | str | `http://localhost:11434` | Default Ollama server URL |
| `BATCH_MAX_WORKERS` | int | `1` | Maximum concurrent workers for Ollama batch processing |

The `OLLAMA_HOST` environment variable overrides the base URL. An action's `base_url` overrides both.

### OllamaCloudDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BASE_URL` | str | `https://ollama.com` | Default Ollama Cloud API URL |
| `BATCH_MAX_WORKERS` | int | `1` | Maximum concurrent workers for Ollama Cloud batch processing |

The Ollama Cloud batch client reads the `OLLAMA_CLOUD_HOST` environment variable before it uses `BASE_URL`. Both Ollama batch clients take the worker count from an action's `batch_max_workers`, then the `OLLAMA_BATCH_MAX_WORKERS` environment variable, then `BATCH_MAX_WORKERS`.

### ApiDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_RESPONSE_BYTES` | int | `10 * 1024 * 1024` | Safety cap on API response size (10 MB) |
| `REQUEST_TIMEOUT_SECONDS` | int | `30` | HTTP request timeout for data-source fetching |

### SeedDataDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_FILE_SIZE_BYTES` | int | `10 * 1024 * 1024` | Maximum seed/static data file size (10 MB) |

### PromptDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `MAX_PROMPT_SIZE_BYTES` | int | `100 * 1024` | Maximum prompt file size for validation (100 KB) |

### DocsDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `README_MAX_BYTES` | int | `100 * 1024` | Maximum README content included in catalog.json (100 KB) |
| `EVENT_TAIL_LIMIT` | int | `2000` | Most recent events each log keeps for catalog.json; every log shares one window of this size |
| `EVENT_PROBLEM_LIMIT` | int | `500` | Kept per level, per log, on top of the recency window — so a log retains up to 500 warnings *and* 500 errors, and rare old problems still reach the window |

## Naming Conventions

- `_SECONDS` / `_BYTES` suffixes make units explicit
- Constants use `UPPER_SNAKE_CASE`
- Classes group related defaults by subsystem

## Adding New Defaults

1. Add a constant to the appropriate class (or create a new class if the domain is new)
2. Keep the module free of imports
3. Update the consumer to reference the constant
4. Update this page

## See Also

- [Configuration](../configuration/) — User-facing workflow configuration
- [Architecture](./) — System architecture overview
