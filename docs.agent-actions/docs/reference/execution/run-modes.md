---
title: Run Modes
sidebar_position: 4
---

# Run Modes

Agent Actions supports two execution modes: **online** (real-time) and **batch** (cost-optimized).

## Overview

| Mode | Processing | Latency | Cost | Use Case |
|------|------------|---------|------|----------|
| **online** | Synchronous | Real-time | Standard | Interactive, development |
| **batch** | Asynchronous | Hours | Up to 50% savings | Production, large datasets |

## Configuration

```yaml
defaults:
  run_mode: batch  # or "online"

actions:
  - name: my_action
    run_mode: online  # Override per-action
```

:::info
`run_mode` accepts the string values `batch` and `online` (case-insensitive). These map to the `RunMode` enum internally.
:::

## Online Mode

Requests process synchronously with immediate responses.

```yaml
defaults:
  run_mode: online
```

**When to use:**
- Development and testing
- Interactive applications
- Small datasets (< 100 records)
- Debugging workflows

## Batch Mode

Requests queue for asynchronous batch processing with significant cost savings.

```yaml
defaults:
  run_mode: batch
```

**When to use:**
- Production workloads
- Large datasets (100+ records)
- Cost-sensitive processing
- Scheduled/overnight jobs

### Provider Support

| Provider | Batch API | Cost Savings |
|----------|-----------|--------------|
| OpenAI | Yes | ~50% |
| Anthropic | Yes | ~50% |
| Google Gemini | Yes | Varies |
| Groq | Yes | Varies |
| Mistral | Yes | Varies |
| Ollama | No (local) | N/A |

### Batch Commands

```bash
# Check batch status
agac batch status --batch-id batch_abc123

# Retrieve completed results
agac batch retrieve --batch-id batch_abc123

# Retry failed records
agac batch retry --batch-id batch_abc123
```

See [batch Commands](../cli/batch) for complete CLI reference.

## Mixing Modes

Override at the action level for hybrid workflows:

```yaml
defaults:
  run_mode: batch

actions:
  - name: bulk_extraction
    # Uses default batch mode

  - name: interactive_validation
    run_mode: online  # Override for this action
```

## See Also

- [batch Commands](../cli/batch) - CLI reference for batch operations
- [Batch Recovery](./batch-recovery) - Two-phase retry and reprompt for batch processing
- [Context Handling](./context-handling) - Batch vs online context differences
- [Granularity](./granularity) - Record vs file processing
