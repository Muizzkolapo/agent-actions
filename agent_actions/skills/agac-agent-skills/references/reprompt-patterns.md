# Reprompt Patterns

How to configure automatic retry with feedback when LLM output fails validation.

## When to Use Reprompt vs Guard

| Scenario | Use | Why |
|----------|-----|-----|
| Malformed JSON | Reprompt | LLM can fix structural errors |
| Missing required field | Reprompt | LLM can add the field |
| Schema type mismatch | Reprompt | LLM can correct the type |
| Wrong business value | Guard | LLM made a semantic choice, retrying won't help |
| Score below threshold | Guard | This is filtering, not error correction |
| Custom format validation | Reprompt | LLM can learn from the feedback |

**Rule of thumb:** If the LLM can fix the problem given feedback, use reprompt. If the problem is a valid-but-unwanted value, use a guard.

## Configuration

```yaml
- name: extract_codes
  schema: bisac_codes
  reprompt:
    validation: "check_valid_bisac"    # Custom validation UDF
    max_attempts: 3                     # 1-10, default: 2
    on_exhausted: "return_last"         # "return_last" (default) or "raise"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `validation` | string | None | Name of `@reprompt_validation` function |
| `max_attempts` | int | 2 | Total attempts including first try (1-10) |
| `on_exhausted` | string | `"return_last"` | What to do when all attempts fail |

**`on_exhausted` options:**
- `"return_last"` — Accept the last response even though it failed validation. Downstream actions receive potentially invalid data.
- `"raise"` — Raise a `RuntimeError`, failing the action. Use this when invalid data is worse than no data.

## Schema-Based Reprompt (No Custom UDF)

For simple schema validation without writing Python, use `on_schema_mismatch`:

```yaml
- name: classify_issue
  schema: issue_classification
  json_mode: true
  on_schema_mismatch: reprompt         # "warn" | "reprompt" | "reject"
  reprompt:
    max_attempts: 3
```

When the LLM response fails JSON Schema validation, the framework sends the schema error as feedback and retries. No custom UDF needed.

## Writing Custom Validation UDFs

Place validation functions in `tools/shared/reprompt_validations.py`:

```python
from agent_actions import reprompt_validation

@reprompt_validation("BISAC codes must be exactly 9 characters and start with FIC or NON")
def check_valid_bisac(response: dict) -> bool:
    """Return True if valid, False to trigger reprompt."""
    codes = response.get("bisac_codes", [])
    if not codes:
        return False
    return all(
        len(code) == 9 and code[:3] in ("FIC", "NON")
        for code in codes
    )
```

**Decorator contract:**
- The string argument is the **feedback message** sent to the LLM on failure — make it specific
- Function receives the parsed dict response from the LLM
- Return `True` = pass, `False` = trigger reprompt with feedback
- `ValueError`, `TypeError`, `LookupError` are caught and treated as validation failure
- Other exceptions propagate (crash the action)

**Good feedback messages:**

```python
# BAD — vague, LLM can't learn from this
@reprompt_validation("Invalid response")

# GOOD — specific, tells the LLM exactly what to fix
@reprompt_validation("Each BISAC code must be exactly 9 characters starting with FIC or NON. Example: FIC000000")

# GOOD — includes the constraint and an example
@reprompt_validation("Description must be at least 50 words. Expand with more detail about the book's themes and content.")
```

**UDF discovery:** Place the file in `tools/shared/` with an `__init__.py`. The function name in the decorator becomes the `validation:` value in YAML:

```
tools/
  shared/
    __init__.py
    reprompt_validations.py    # Contains @reprompt_validation functions
```

## Composed Validators

When both `validation` (custom UDF) and `on_schema_mismatch: reprompt` are configured, validators are composed — the schema check runs first, then the custom UDF. Fails on the first failure.

```yaml
- name: generate_catalog_entry
  schema: catalog_entry
  on_schema_mismatch: reprompt         # Layer 1: schema check
  reprompt:
    validation: "check_valid_bisac"    # Layer 2: custom business logic
    max_attempts: 3
```

Execution order per attempt:
1. LLM produces response
2. Schema validator checks types/required fields
3. If schema passes → custom UDF checks business logic
4. If either fails → feedback appended to prompt, retry

## How the Retry Loop Works

```
Attempt 1: Original prompt → LLM → Validate
  ↓ (fails)
Attempt 2: Original prompt + "Previous response failed: {feedback}" → LLM → Validate
  ↓ (fails)
Attempt 3: Original prompt + feedback history → LLM → Validate
  ↓ (fails, max_attempts reached)
on_exhausted: "return_last" → accept last response
on_exhausted: "raise" → RuntimeError
```

Each retry appends the validation feedback to the prompt, giving the LLM context about what went wrong. The feedback accumulates — attempt 3 sees feedback from attempts 1 and 2.

## Reprompt + Guard Interaction

When both reprompt and guard are configured on the same action:

1. Guard evaluates first (on **input** data)
2. If guard skips/filters → reprompt is bypassed entirely (nothing to validate)
3. If guard passes → LLM executes → reprompt validation runs on output

Guards and reprompt operate on different data: guards check input, reprompt checks output.

## Reprompt in Batch Mode

Batch mode uses two-phase recovery:

1. **Retry phase** — Detects missing records from the batch response, resubmits as a new batch
2. **Reprompt phase** — Validates all results with the configured UDF, resubmits failed records with feedback as a new batch

The key difference from online: batch reprompt processes all failed records together as a single batch submission, while online mode handles each record individually.

## Examples

### Word count validation

```python
@reprompt_validation(
    "Description must be at least 50 words. Expand with more specific details "
    "about themes, plot points, and target audience."
)
def check_description_word_count(response: dict) -> bool:
    description = response.get("description", "")
    return len(description.split()) >= 50
```

### Combined format + content check

```python
@reprompt_validation(
    "Genre must be one of: Fiction, Non-Fiction, Science Fiction, Mystery, Romance. "
    "And the response must not contain parse errors."
)
def check_genre_classification(response: dict) -> bool:
    if "_parse_error" in response:
        return False
    genre = response.get("genre", "")
    valid_genres = {"Fiction", "Non-Fiction", "Science Fiction", "Mystery", "Romance"}
    return genre in valid_genres
```

### Schema-only reprompt (no UDF)

```yaml
- name: extract_entities
  schema:
    entities: array[string]!           # Required array of strings
    confidence: number!                # Required number
  json_mode: true
  on_schema_mismatch: reprompt
  reprompt:
    max_attempts: 2
    on_exhausted: raise                # Fail if schema still violated
```

## Cost Considerations

Each reprompt attempt is a full LLM call. With `max_attempts: 3`:
- Best case: 1 API call (passes first try)
- Worst case: 3 API calls per record

For workflows with many records, reprompt costs add up. Prefer:
- Tighter prompts over more retries
- Schema constraints over custom validation (schema errors give better LLM feedback)
- `max_attempts: 2` unless you have evidence that 3+ helps
