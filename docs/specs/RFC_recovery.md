# RFC: Recovery

## Terminology

| Term | Meaning |
|------|---------|
| **Retry** | Re-submit failed records (network/API errors, missing results) |
| **Reprompt** | Re-send to LLM with feedback (content failed UDF validation) |

Both mechanisms work in **Online** and **Batch** modes.

---

## Record Tracking

Recovery requires tracking records through the workflow. Each record has identifiers that allow matching submitted requests to received results.

### Key Identifiers

| Field | Purpose |
|-------|---------|
| `source_guid` | Stable ID from original input (never changes) |
| `target_id` | Output ID for this action's result |
| `node_id` | Unique execution node ID |
| `batch_id` | Groups records in same batch submission |
| `batch_uuid` | Unique ID within batch (`{batch_id}_{index}`) |
| `lineage` | Chain of node_ids through workflow |

### Context Map

The `.context_map_{source}.json` maps `target_id` → original record with all tracking fields:

```json
{
  "ea312272-e902-4860-ad6d-fa3e7647eda0": {
    "isbn": "9780596007126",
    "title": "Head First Design Patterns",
    "source_guid": "a822c738-b8bd-5327-8457-a241f8ae90ea",
    "target_id": "ea312272-e902-4860-ad6d-fa3e7647eda0",
    "batch_id": "batch_6b759323b9404aa989f4754b182a8ef7",
    "batch_uuid": "batch_6b759323b9404aa989f4754b182a8ef7_0"
  }
}
```

### Matching Results

**Retry:** Match missing records by comparing submitted `target_id` set vs received `target_id` set.

**Reprompt:** Use `target_id` to look up original context for re-prompting.

---

## Output Structure

Each record follows this structure. Recovery metadata goes in `_recovery`:

```json
{
  "source_guid": "a822c738-b8bd-5327-8457-a241f8ae90ea",
  "content": {
    "primary_bisac_code": "COM051010",
    "classification_reasoning": "..."
  },
  "metadata": {
    "model": "gpt-4",
    "finish_reason": "stop",
    "status_code": 200
  },
  "node_id": "classify_genre_1b453f68-6ed3-4b06-b24c-70d00a0ec234",
  "lineage": ["classify_genre_1b453f68-6ed3-4b06-b24c-70d00a0ec234"],
  "target_id": "ea312272-e902-4860-ad6d-fa3e7647eda0",
  "_recovery": {
    "retry": {
      "attempts": 2,
      "failures": 1,
      "succeeded": true,
      "reason": "timeout",
      "timestamp": "2024-01-13T12:30:45+00:00"
    },
    "reprompt": {
      "attempts": 2,
      "passed": true,
      "validation": "check_no_forbidden_words"
    }
  }
}
```

### Record Fields

| Field | Description |
|-------|-------------|
| `source_guid` | Stable ID from original input |
| `content` | LLM response payload |
| `metadata` | LLM call metadata (model, status) |
| `node_id` | Unique execution node ID |
| `lineage` | Chain of node_ids through workflow |
| `target_id` | Output ID for this result |
| `_recovery` | Recovery metadata (only present if retry/reprompt occurred) |

### Recovery Metadata

`_recovery.retry` (present if retried):

| Field | Type | Description |
|-------|------|-------------|
| `attempts` | int | Total number of attempts made (failures + 1 if succeeded) |
| `failures` | int | Number of failed attempts before success (or total if exhausted) |
| `succeeded` | bool | Whether the operation ultimately succeeded |
| `reason` | str | Why retry was needed (`timeout`, `api_error`, `missing`, `rate_limit`, `network_error`) |
| `timestamp` | str | ISO format timestamp when retry completed (e.g., `2024-01-13T12:30:45+00:00`) |

`_recovery.reprompt` (present if reprompted):

| Field | Description |
|-------|-------------|
| `attempts` | Number of reprompt attempts |
| `passed` | Whether validation ultimately passed |
| `validation` | UDF name that triggered reprompt |

---

## Retry

### Problem

Records can fail due to network errors, API failures, or missing results.

- **Online**: Request times out or returns error
- **Batch**: Submit 10 records, get 9 back

### Solution

Automatically resubmit failed/missing records.

### Configuration

```yaml
actions:
  - name: classify_book
    retry:
      enabled: true
      max_attempts: 3
```

### Behavior

**Online:**
1. LLM call fails (timeout, API error)
2. Retry same request (up to `max_attempts`)

**Batch:**
1. Submit N records, receive M results (M ≤ N)
2. Identify missing records by comparing `target_id` sets
3. Resubmit missing records as new batch
4. Consolidate results
5. Repeat until complete or `max_attempts` exhausted

---

## Reprompt

### Problem

LLM responses sometimes fail business validation (wrong format, forbidden words, missing fields). Need to re-send to LLM with feedback explaining what to fix.

### Solution

Add a `reprompt` block with a UDF that validates the response.

### Configuration

```yaml
actions:
  - name: classify_book
    reprompt:
      validation: check_no_forbidden_words   # UDF name
      max_attempts: 2                        # Default: 2
      on_exhausted: return_last              # return_last | raise
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `validation` | str | required | UDF function name |
| `max_attempts` | int | `2` | Reprompt attempts |
| `on_exhausted` | str | `return_last` | Behavior when attempts exhausted |

### Validation UDF

```python
from agent_actions import reprompt_validation

@reprompt_validation("Response must not contain the word 'boy'")
def check_no_forbidden_words(response: dict) -> bool:
    text = response.get("description", "").lower()
    return "boy" not in text
```

The decorator message tells the LLM what to fix on reprompt.

**Contract:**
- Input: parsed LLM response (dict)
- Output: `True` (pass) or `False` (reprompt)

### Reprompt Message

When validation fails, appended to original prompt:

```
---
Your response failed validation: Response must not contain the word 'boy'

Your response: {"description": "A boy and his dog..."}

Please correct and respond again.
```

### Behavior

**Online:**
1. LLM responds
2. UDF validates response
3. If fails, reprompt with feedback (up to `max_attempts`)

**Batch:**
1. Receive batch results
2. UDF validates each response
3. Failed records resubmitted as new batch (with feedback appended)
4. Consolidate results
5. Repeat until all pass or `max_attempts` exhausted

### Cost

Each reprompt is a full LLM call. `max_attempts: 2` means up to 3 total calls per record.

---

## Summary

| Aspect | Retry | Reprompt |
|--------|-------|----------|
| Trigger | Network error, missing results | UDF returns False |
| Action | Resubmit same request | Re-send with feedback |
| Modes | Online + Batch | Online + Batch |
| Layer | Transport | Application |

Both mechanisms can be enabled on the same action. They operate independently.

---

## Workflow Integration

Recovery integrates with the existing workflow structure:

```
agent_workflow/
├── agent_config/
│   └── book_catalog_enrichment.yml    # Action configs with retry/reprompt
├── agent_io/
│   ├── source/                        # Input records
│   ├── staging/                       # Preprocessed records
│   ├── target/
│   │   ├── .manifest.json             # Workflow state
│   │   └── {action_name}/
│   │       ├── books_sample.json      # Output records (with _recovery)
│   │       └── batch/
│   │           ├── .batch_registry.json
│   │           └── .context_map_{source}.json
│   └── .agent_status.json             # Action-level status
```

### Manifest Updates

The `.manifest.json` tracks recovery at action level:

```json
{
  "actions": {
    "classify_genre": {
      "status": "completed",
      "record_count": 10,
      "recovery_stats": {
        "retry_count": 1,
        "reprompt_count": 2
      }
    }
  }
}
```

### Agent Status

The `.agent_status.json` includes recovery summary:

```json
{
  "classify_genre": {
    "status": "completed",
    "recovery": {
      "retried": 1,
      "reprompted": 2,
      "failed": 0
    }
  }
}
```

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Retry + Reprompt both fail | `_recovery` contains both, `on_exhausted` determines final outcome |
| Retry succeeds, Reprompt fails | Record marked with reprompt failure |
| Network error during reprompt | Retry kicks in for that reprompt attempt |
| Batch partially fails validation | Only failed records reprompted, results merged |

---

## Non-Goals

- **Cross-action recovery**: Recovery is per-action only. If `action_b` fails, we don't re-run `action_a`.
- **Persistent retry queue**: No external queue. Retry state is in-memory during execution.
- **Custom backoff**: Fixed immediate retry. Backoff complexity not needed for LLM validation.

---

## Design for Extensibility: Exhausted Handlers

> **Note**: Not implementing now, but design should make this easy to add later.

When retry/reprompt attempts are exhausted, records need a destination. Inspired by Apache Beam's dead letter pattern.

### Current Scope (v1)

For v1, we implement two simple behaviors via `on_exhausted`:

| Value | Behavior |
|-------|----------|
| `return_last` | Return last response (default) |
| `raise` | Raise exception, fail the action |

### Future Handlers

Design the `on_exhausted` field as a **string that maps to a handler**. This allows adding new handlers without config changes:

```yaml
# v1 - simple string
on_exhausted: return_last

# Future - same pattern, new handlers
on_exhausted: dead_letter
on_exhausted: skip
on_exhausted: send_to_review   # Custom UDF
```

### Implementation Guidance

To enable future extensibility:

1. **Store exhausted records with full context** - Even if we just `return_last` now, capture failure info in `_recovery` metadata so it can be used later

2. **Use handler registry pattern** - Similar to how we register `@reprompt_validation` UDFs, design for `@exhausted_handler` UDFs

3. **Keep `on_exhausted` as string** - Don't hardcode enum, allow string lookup to handler registry

### Future Handler Ideas

| Handler | Behavior |
|---------|----------|
| `dead_letter` | Write to `_dead_letter/` folder |
| `skip` | Skip record, continue with others |
| Custom UDF | User-defined (human review queue, alerts, etc.) |

---

## Test Cases (TDD)

Write these tests before implementation.

### Retry Tests

**Online:**
```python
def test_retry_online_success_on_first_attempt():
    """No retry needed when LLM call succeeds."""

def test_retry_online_success_after_timeout():
    """Retry succeeds after first attempt times out."""

def test_retry_online_exhausted_raises():
    """on_exhausted=raise raises after max_attempts."""

def test_retry_online_exhausted_returns_last():
    """on_exhausted=return_last returns last error response."""

def test_retry_online_metadata_recorded():
    """_recovery.retry contains attempts and reason."""
```

**Batch:**
```python
def test_retry_batch_all_records_returned():
    """No retry when all N records return."""

def test_retry_batch_missing_records_resubmitted():
    """Submit 10, get 8 back, resubmit 2 as new batch."""

def test_retry_batch_consolidates_results():
    """Results from original + retry batches merged correctly."""

def test_retry_batch_multiple_rounds():
    """Handles multiple retry rounds until complete."""

def test_retry_batch_exhausted_partial_results():
    """Returns successful records even if some exhaust retries."""

def test_retry_batch_identifies_missing_by_target_id():
    """Uses target_id to match submitted vs received."""
```

### Reprompt Tests

**Online:**
```python
def test_reprompt_online_passes_validation():
    """No reprompt when UDF returns True."""

def test_reprompt_online_fails_then_passes():
    """Reprompt succeeds after validation failure."""

def test_reprompt_online_feedback_appended():
    """Validation error message appended to prompt."""

def test_reprompt_online_exhausted_returns_last():
    """Returns last response when max_attempts reached."""

def test_reprompt_online_exhausted_raises():
    """on_exhausted=raise raises after max_attempts."""

def test_reprompt_online_metadata_recorded():
    """_recovery.reprompt contains attempts, passed, validation."""
```

**Batch:**
```python
def test_reprompt_batch_all_pass_validation():
    """No reprompt when all records pass UDF."""

def test_reprompt_batch_failed_records_resubmitted():
    """Only failed records sent in reprompt batch."""

def test_reprompt_batch_feedback_per_record():
    """Each failed record gets its own feedback message."""

def test_reprompt_batch_consolidates_results():
    """Original passes + reprompt results merged."""

def test_reprompt_batch_multiple_rounds():
    """Handles multiple reprompt rounds."""
```

### Combined Tests

```python
def test_retry_then_reprompt():
    """Record retried (network error), then reprompted (validation)."""

def test_reprompt_triggers_retry():
    """Network error during reprompt triggers retry."""

def test_both_exhausted():
    """_recovery contains both retry and reprompt info."""

def test_recovery_metadata_in_output():
    """Output JSON includes _recovery when recovery occurred."""

def test_no_recovery_metadata_when_clean():
    """Output JSON excludes _recovery when no recovery needed."""
```

### UDF Registration Tests

```python
def test_reprompt_validation_decorator_registers():
    """@reprompt_validation registers function in registry."""

def test_reprompt_validation_stores_message():
    """Decorator message stored for feedback."""

def test_unknown_validation_raises():
    """Config referencing unknown UDF raises error."""
```

### Integration Tests

```python
def test_workflow_retry_batch_end_to_end():
    """Full workflow with batch retry."""

def test_workflow_reprompt_online_end_to_end():
    """Full workflow with online reprompt."""

def test_manifest_records_recovery_stats():
    """manifest.json includes retry_count, reprompt_count."""

def test_agent_status_records_recovery():
    """agent_status.json includes recovery summary."""
```

---

## Open Questions

1. **Max total attempts across retry + reprompt?**
   - Current: Independent limits (e.g., 3 retries + 2 reprompts = 5 possible attempts)
   - Consider a global cap to prevent runaway costs?

2. **Logging verbosity for recovery events?**
   - Recommendation: INFO for attempts, DEBUG for full request/response
