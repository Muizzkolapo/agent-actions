# Removed Features

This document describes features that were removed from Agent Actions but may be re-implemented in the future.

---

## Reprompting System (Removed: January 2026)

### What It Was

Reprompting was an automatic retry system for validation errors. When an LLM returned invalid output (malformed JSON, schema violations, constraint failures), the system would:

1. Attempt to repair the response without an API call
2. If repair failed, retry with error feedback in the prompt
3. Optionally use LLM critique to analyze failures

### Features

#### JSON Repair (No API Call)
Attempted to fix common JSON syntax issues before triggering a full reprompt:

| Issue | Example | Repair Method |
|-------|---------|---------------|
| Markdown wrapping | ` ```json {...}``` ` | `strip_markdown` |
| Trailing commas | `[1, 2, 3,]` | `fix_trailing_commas` |
| Single quotes | `{'key': 'value'}` | `fix_quotes` |
| Unclosed brackets | `{"items": [1, 2, 3` | `close_brackets` |
| Embedded JSON | `Here's the data: {...}` | `extract_json_block` |

#### LLM Critique
Used an LLM to analyze validation failures and provide guidance:
- Analyzed the original response and error
- Identified why validation failed
- Suggested corrections
- Added guidance to the retry prompt

#### Self-Reflection
Included the model's own assessment of what went wrong in retry prompts.

#### Constraint Validation
Validated responses against configurable constraints:
- `required_fields` - Check for required fields
- `not_contains` - Ensure response doesn't contain certain values
- `field_types` - Validate field types match schema
- `non_empty` - Check fields are not empty

### Configuration (Was)

```yaml
defaults:
  reprompt:
    max_attempts: 3           # Maximum retry attempts
    json_repair: true         # Attempt JSON repair before retry
    use_llm_critique: false   # Use LLM to analyze failures
    use_self_reflection: false # Include model self-assessment
    critique_after_attempt: 2  # Start critique after this attempt
    on_exhausted: continue    # Behavior when attempts exhausted
    constraints:              # Optional constraints
      - required_fields: [name, description]
      - not_contains: "I don't know"
```

### Exhaustion Behavior (Was)

| Value | Behavior |
|-------|----------|
| `continue` | Drop the failed record, continue workflow |
| `fail` | Raise error, entire workflow fails |
| `dead_letter` | Write failed records to `.failed.json`, continue |

### Why Removed

1. **Complexity** - The interceptor-based architecture was overly complex
2. **Integration Issues** - Reprompt wasn't properly integrated with the main execution path
3. **Schema Validation Gap** - JSON repair fixed syntax but didn't validate against schema
4. **LLM Critique Not Triggering** - The critique feature wasn't being invoked properly
5. **Duplicate Systems** - RecoveryEngine in `recovery/` and RepromptEngine in `reprompting/` had overlapping functionality

### Files That Were Removed

```
agent_actions/reprompting/
├── __init__.py
├── config.py          # RepromptConfig class
├── engine.py          # RepromptEngine - core reprompt logic
├── interceptor.py     # RepromptInterceptor - integration with interceptor system
├── json_repair.py     # JSONRepairStrategy - 6-stage repair pipeline
├── constraints.py     # ConstraintValidator - constraint checking
└── _MANIFEST.md       # Module documentation
```

### Future Re-implementation Notes

If re-implementing, consider:

1. **Use RecoveryEngine pattern** - Single entry point that wraps the LLM call and handles all recovery (retry + reprompt) in nested loops

2. **Schema validation first** - Validate against schema BEFORE considering response valid, not just JSON syntax

3. **Simpler architecture** - Avoid separate interceptor system; integrate directly into the LLM invocation path

4. **Test with real failures** - The test injection system returned data that was syntactically valid but semantically wrong, which exposed gaps in schema validation

### Related Documentation

- [Retry & Error Handling](reference/execution/retry.md) - Still supported for transient errors
- [Recovery Module](../agent_actions/recovery/) - Contains retry logic that remains

---

## dead_letter Exhaustion Behavior (Removed: January 2026)

### What It Was

`dead_letter` was an exhaustion behavior option for retry configuration. When retries were exhausted:
- `continue` - Drop the failed record, continue workflow
- `fail` - Raise error, entire workflow fails
- `dead_letter` - Write failed records to a separate `.dead_letter.json` file, continue workflow

### Why Removed

1. **Redundant with failure records** - Failed records now have `_failed: true` flag and full `_retry_metadata` embedded directly in output files
2. **Simplification** - Two behaviors (`continue` and `fail`) are sufficient for most use cases
3. **Inconsistency** - Online and batch modes handled dead_letter differently, causing confusion

### What to Use Instead

Use `on_exhausted: continue` - failed records will be created in the normal output with:
- `_failed: true` marker
- `_retry_metadata.exhausted: true`
- Full error information in `_retry_metadata.error_type` and `_retry_metadata.error_message`

---

## RetryTracker / .retry_log.json (Removed: January 2026)

### What It Was

`RetryTracker` was a centralized tracking system that persisted retry events to a `.retry_log.json` file in the output directory. It tracked:
- Every retry attempt with full record data
- Success/failure/exhausted outcomes
- Timestamp and error information

### Why Removed

1. **Redundancy** - Retry metadata is now embedded in each output record's `_retry_metadata` field
2. **Correlation complexity** - The separate log file made it hard to correlate retries with output records
3. **File management** - An extra file to track and manage per workflow run

### What to Use Instead

Check the `_retry_metadata` field on each output record:
```json
{
  "_retry_metadata": {
    "was_retried": true,
    "retry_attempts": 2,
    "error_type": "RateLimitError",
    "error_message": "Rate limit exceeded",
    "exhausted": false
  }
}
```
