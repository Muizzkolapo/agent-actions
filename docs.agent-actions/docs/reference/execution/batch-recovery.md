---
title: Batch Recovery
sidebar_position: 5
---

# Batch Recovery

When batch jobs fail or produce unexpected results, Agent Actions provides tools to inspect, retry, and recover.

## Checking Batch Status

```bash
agac batch status --batch-id <batch_id>
```

The `--batch-id` flag is **required** — there is no "last job" fallback. Capture the batch ID from the `agac run --mode batch` output or from the `.batch_registry.json` file in the action's output directory.

## Retrieving Results

```bash
agac batch retrieve --batch-id <batch_id>
```

## Failure Type Counters

Both online and batch paths populate failure-type counters in the output record. The `parse_error_count`, `schema_error_count`, and other counter fields are present for both execution modes — the "online only" caveat in earlier documentation was incorrect.

Counter fields use a sparse contract: absent means zero. Use `record.get("parse_error_count", 0)` rather than assuming the key always exists.

## Provider Batch Support

| Provider | Batch API | Notes |
|----------|-----------|-------|
| OpenAI | Yes | File-based batch API |
| Anthropic | Yes | Message batches |
| Google Gemini | Yes | Batch prediction |
| Groq | Yes | Requires `uv pip install groq` (separate extra) |
| Cohere | Online only | No batch API available |
| Ollama | No | Local inference only |

## See Also

- [Run Modes](./run-modes.md) — Online vs. batch execution
- [Retry](./retry.md) — Transport-layer retry for online mode
