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

### LockDefaults

File-lock timeouts are split intentionally: simple (shared/read) locks use a shorter timeout than atomic (exclusive read-modify-write) locks.

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `SIMPLE_LOCK_TIMEOUT_SECONDS` | float | `5.0` | Timeout for shared/read file locks |
| `ATOMIC_LOCK_TIMEOUT_SECONDS` | float | `10.0` | Timeout for exclusive read-modify-write locks |

### OllamaDefaults

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BASE_URL` | str | `http://localhost:11434` | Default Ollama server URL |

This value was previously duplicated in three files. It can be overridden at runtime via the `OLLAMA_HOST` environment variable.

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
