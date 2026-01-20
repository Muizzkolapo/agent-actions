# Failure Injection for Testing

Test retry and recovery logic by injecting failures into the processing pipeline.

## Prerequisites

Failure injection only works with:
1. **New code path** - Workflows using `RecordProcessor` (not legacy `StagingProcessor`)
2. **Retry enabled** - Agent config must have `retry` configured

```yaml
# agent_config.yml - retry must be configured
agents:
  classify_genre:
    retry:
      max_attempts: 3
      backoff: exponential
```

## Quick Start

```bash
# Normal run
agac run -a book_catalog_enrichment

# With 30% failure rate
FAILURE_INJECTION_RATE=0.3 agac run -a book_catalog_enrichment

# Fail specific record IDs (batch mode)
FAILURE_INJECTION_IDS=book-001,book-042 agac run -a book_catalog_enrichment

# Reproducible failures (same seed = same failures)
FAILURE_INJECTION_RATE=0.2 FAILURE_INJECTION_SEED=42 agac run -a book_catalog_enrichment
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FAILURE_INJECTION_RATE` | Percentage of operations to fail (0.0-1.0) | `0.3` = 30% |
| `FAILURE_INJECTION_IDS` | Comma-separated custom_ids to fail (batch only) | `id1,id2,id3` |
| `FAILURE_INJECTION_SEED` | Random seed for reproducible failures | `42` |

## Behavior by Processing Mode

### Online Mode (`RecordProcessor`)
- Raises `RateLimitError` inside the retry wrapper
- Retry service catches and retries the operation
- Only affected by `RATE` (IDs are for batch records)
- **Requires retry config** in agent

```bash
# 10% of LLM calls fail, retry kicks in
FAILURE_INJECTION_RATE=0.1 agac run -a book_catalog_enrichment
```

### Batch Mode (`OllamaBatchClient`)
- Skips records, omitting them from results
- Simulates "missing" responses to test batch retry
- Affected by both `RATE` and `IDS`

```bash
# Skip 20% of records randomly
FAILURE_INJECTION_RATE=0.2 agac run -a book_catalog_enrichment

# Skip specific books
FAILURE_INJECTION_IDS=book-007,book-013 agac run -a book_catalog_enrichment
```

## Code Path Requirements

| Code Path | Injection? | Retry? | Status |
|-----------|------------|--------|--------|
| `RecordProcessor` (new) | ✅ | ✅ | Supported |
| `StagingProcessor` (legacy) | ❌ | ❌ | Not supported |

If your workflow uses `InitialStrategy` with `StagingProcessor`, failure injection will **not** trigger. Ensure your workflow is routed through `RecordProcessor`.

## Examples

### Test batch retry with reproducible failures
```bash
# First run - some records will fail
FAILURE_INJECTION_RATE=0.25 FAILURE_INJECTION_SEED=123 agac run -a book_catalog_enrichment

# Second run with same seed - exact same records fail
FAILURE_INJECTION_RATE=0.25 FAILURE_INJECTION_SEED=123 agac run -a book_catalog_enrichment
```

### Test specific edge cases
```bash
# Fail the first and last book in a catalog
FAILURE_INJECTION_IDS=book-001,book-100 agac run -a book_catalog_enrichment
```

### Combine rate and specific IDs
```bash
# Always fail book-042, plus 10% random failures
FAILURE_INJECTION_RATE=0.1 FAILURE_INJECTION_IDS=book-042 agac run -a book_catalog_enrichment
```

## Logs

When enabled, you'll see log output:
```
INFO - Failure injection ENABLED: rate=0.30, ids=(random), seed=42
...
[INJECTED] Skipping book-007
[INJECTED] Skipping book-023
```

## Disabling

Failure injection is **disabled by default**. Simply don't set the environment variables:

```bash
# No injection - normal operation
agac run -a book_catalog_enrichment
```

Or explicitly set rate to 0:
```bash
FAILURE_INJECTION_RATE=0 agac run -a book_catalog_enrichment
```

## Troubleshooting

### Injection not triggering?

Check these requirements:
1. **Using new code path** - Look for `RecordProcessor` in logs, not `StagingProcessor`
2. **Retry configured** - Agent must have `retry:` in config
3. **Env var set** - `FAILURE_INJECTION_RATE` must be > 0

### Workflow crashing instead of retrying?

Your workflow is likely using the legacy `StagingProcessor` path which doesn't have retry. Ensure your workflow routes through `RecordProcessor`.
