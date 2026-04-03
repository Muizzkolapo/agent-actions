# Lessons Learned

## 2026-04-03: Output-list emptiness is not a reliable proxy for "no successes"

**Failure mode:** Both pipelines used `not output` to detect total failure, but EXHAUSTED records produce tombstone data that inflates the output list. This masked the failure when all records exhausted retries or when FAILED + EXHAUSTED records mixed.

**Detection signal:** Circuit breaker never fired for downstream actions despite all upstream records failing. Downstream actions ran on tombstone-only data and produced garbage.

**Prevention rule:** When checking whether an action meaningfully succeeded, always use `stats.success == 0` (the direct signal) instead of `not output` (a proxy that can be polluted by non-success data like tombstones, unprocessed passthrough, or deferred placeholders). The stats object is the authoritative source for what happened during processing.

**Applied in:** `pipeline.py` and `initial_pipeline.py` zero-success failure checks.
