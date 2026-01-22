# Reprompt Feature Specification

## Overview

Reprompt re-invokes the LLM when a response fails a validation condition. The condition is a UDF decorated with `@reprompt_condition` that returns `True`/`False`.

---

## Configuration

```yaml
actions:
  - name: classify_book
    reprompt:
      enabled: true
      max_attempts: 2
      condition: check_classification_quality   # UDF name
      on_exhausted: continue                    # continue | fail
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable reprompt |
| `max_attempts` | int | `2` | Max reprompt iterations |
| `condition` | str | required | UDF that validates response |
| `on_exhausted` | str | `continue` | `continue` = return last response, `fail` = raise error |

---

## Condition UDF

```python
"""Reprompt condition for validating book classification quality."""

from agent_actions import reprompt_condition


@reprompt_condition(
    description="Classification must include valid BISAC code format (3 letters + 6 digits) and reasoning must be at least 20 words"
)
def check_classification_quality(record: dict) -> bool:
    """Check if the LLM classification response meets quality standards.

    Args:
        record: LLM output containing classification data

    Returns:
        True if valid, False to trigger reprompt
    """
    # Check primary BISAC code format (e.g., COM051000)
    primary_code = record.get("primary_bisac_code", "")
    if not primary_code or len(primary_code) < 9:
        return False

    # Check code starts with valid prefix
    prefix = primary_code[:3].upper()
    valid_prefixes = ["COM", "BUS", "TEC", "SCI", "MAT", "EDU"]
    if prefix not in valid_prefixes:
        return False

    # Check reasoning has minimum word count
    reasoning = record.get("classification_reasoning", "")
    word_count = len(reasoning.split())
    if word_count < 20:
        return False

    # Check primary_bisac_name is not empty
    if not record.get("primary_bisac_name", "").strip():
        return False

    return True
```

### Decorator

```python
@reprompt_condition(
    description="..."  # Used in reprompt message to LLM
)
def my_condition(record: dict) -> bool:
    ...
```

The `description` tells the LLM what went wrong so it can fix the response.

---

## Flow

```
┌─────────────────────────────────────────┐
│           LLM Invocation                │
└─────────────────────────────────────────┘
                    │
                    ▼
           ┌────────────────┐
           │ Parse Response │
           └────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  condition(record)    │
        └───────────────────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
        True                False
          │                   │
          ▼                   ▼
    ┌───────────┐    ┌─────────────────┐
    │  Return   │    │ Attempts Left?  │
    │  Success  │    └─────────────────┘
    └───────────┘          │        │
                         YES       NO
                           │        │
                           ▼        ▼
                    ┌──────────┐  ┌──────────────┐
                    │ REPROMPT │  │ on_exhausted │
                    │   LLM    │  └──────────────┘
                    └──────────┘
                           │
                    (back to top)
```

---

## Reprompt Message

When condition returns `False`, the description is sent to the LLM:

```
[Original Prompt]

---
Your previous response did not pass validation:

Classification must include valid BISAC code format (3 letters + 6 digits) and reasoning must be at least 20 words

Your response:
{"primary_bisac_code": "COM05", "classification_reasoning": "This is a tech book.", ...}

Please correct this issue and try again.
```

---

## Implementation

### Decorator

```python
# reprompt/decorator.py

_CONDITIONS: Dict[str, Tuple[Callable, str]] = {}

def reprompt_condition(description: str):
    """Register a function as a reprompt condition.

    Args:
        description: Error message shown to LLM when condition fails
    """
    def decorator(func: Callable[[dict], bool]) -> Callable:
        _CONDITIONS[func.__name__] = (func, description)
        return func
    return decorator

def get_condition(name: str) -> Tuple[Callable, str]:
    """Get condition function and description by name."""
    if name not in _CONDITIONS:
        raise ValueError(f"Unknown reprompt condition: {name}")
    return _CONDITIONS[name]
```

### Engine

```python
# reprompt/engine.py

class RepromptEngine:
    def __init__(self, config: RepromptConfig):
        self.config = config
        self.condition_fn, self.description = get_condition(config.condition)

    def process(
        self,
        record: dict,
        raw_response: str,
        original_prompt: str,
        invoke_fn: Callable[[str], dict],
    ) -> RepromptResult:
        attempt = 0
        current = record
        current_raw = raw_response

        while True:
            # Run condition
            passed = self.condition_fn(current)

            if passed:
                return RepromptResult(
                    data=current,
                    success=True,
                    attempts=attempt
                )

            # Check attempts
            if attempt >= self.config.max_attempts:
                if self.config.on_exhausted == "fail":
                    raise RepromptExhaustedError(self.description)
                return RepromptResult(
                    data=current,
                    success=False,
                    attempts=attempt
                )

            # Reprompt
            attempt += 1
            prompt = self._build_reprompt(original_prompt, current_raw)
            current = invoke_fn(prompt)
            current_raw = json.dumps(current)

    def _build_reprompt(self, original: str, response: str) -> str:
        return f"""{original}

---
Your previous response did not pass validation:

{self.description}

Your response:
{response}

Please correct this issue and try again."""
```

---

## Module Structure

```
agent_actions/reprompt/
├── __init__.py
├── decorator.py    # @reprompt_condition
├── config.py       # RepromptConfig
└── engine.py       # RepromptEngine
```

---

## Output Metadata

```json
{
  "content": { "primary_bisac_code": "COM051000", ... },
  "_reprompt_metadata": {
    "was_reprompted": true,
    "attempts": 1
  }
}
```

---

## Examples

### Basic

```yaml
actions:
  - name: classify_book
    reprompt:
      condition: check_classification_quality
```

### With Retry Limit

```yaml
actions:
  - name: generate_description
    reprompt:
      max_attempts: 3
      condition: check_description_quality
      on_exhausted: continue
```

### Fail on Exhausted

```yaml
actions:
  - name: critical_extraction
    reprompt:
      max_attempts: 2
      condition: validate_extraction
      on_exhausted: fail
```
