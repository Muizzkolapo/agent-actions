---
title: Reprompting & Custom Validators
description: Validate LLM outputs and automatically improve prompts when validation fails
sidebar_position: 2
---

# Reprompting & Custom Validators

Automatically validate LLM responses and retry with improved prompts when validation fails. This feature helps ensure LLM outputs meet your specific requirements without manual intervention.

## Overview

### What is Reprompting?

Reprompting is an automatic retry mechanism that:
1. **Validates** LLM outputs against your criteria (word count, format, content, etc.)
2. **Detects** when validation fails
3. **Generates** an improved prompt based on the failure
4. **Retries** the request with the better prompt

### When to Use It

Use reprompting when you need LLMs to:
- Generate specific formats (exact word counts, JSON structure, etc.)
- Include required content (keywords, data fields, etc.)
- Meet quality criteria (minimum length, proper formatting, etc.)
- Follow complex instructions consistently

### How It Works

```
Original Request → LLM Response → Validation Check
                                        ↓
                                    ✅ Pass → Return Response
                                    ❌ Fail → Generate Better Prompt → Retry
```

Each retry is independent - the LLM has no memory of previous failures. The reprompt interceptor analyzes the failure and crafts a better prompt to fix the issue.

### Prerequisites

- Agent Actions installed
- Basic understanding of [YAML configuration](../core-concepts/index.md)
- Tools directory configured (for custom validators)

## Quick Start

Here's a simple example using a built-in validator to ensure exactly 5 words:

```yaml
# workflows/summarize.yml
tools:
  path: "./tools"

agents:
  - agent_type: Summarizer
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Summarize this article in exactly 5 words"

    interceptors:
      # Validation interceptor checks the response
      - type: validation
        validator_function: "agent_actions.agents.validators.functions.validate_word_count"
        validator_args:
          expected: 5
        on_failure: retry

      # Reprompt interceptor improves the prompt on failure
      - type: reprompt
        strategy: "simple"
        max_attempts: 3
```

**What happens:**
1. LLM generates response
2. `validate_word_count` checks if it's exactly 5 words
3. If validation fails, reprompt interceptor generates better prompt
4. Process repeats up to 3 times

## Built-in Validators

Agent Actions provides ready-to-use validators for common cases.

### Word Count Validator

Ensures response has exactly N words.

```yaml
interceptors:
  - type: validation
    validator_function: "agent_actions.agents.validators.functions.validate_word_count"
    validator_args:
      expected: 10  # Exactly 10 words
    on_failure: retry
```

**Validator signature:**
```python
validate_word_count(content: str, expected: int = 5) -> Tuple[bool, str | None]
```

### Character Count Validator

Ensures response length is within range.

```yaml
interceptors:
  - type: validation
    validator_function: "agent_actions.agents.validators.functions.validate_char_count"
    validator_args:
      min_chars: 100
      max_chars: 500
    on_failure: retry
```

**Validator signature:**
```python
validate_char_count(content: str, *, min_chars: int = 0, max_chars: int | None = None) -> Tuple[bool, str | None]
```

### Keywords Validator

Ensures response contains all required keywords.

```yaml
interceptors:
  - type: validation
    validator_function: "agent_actions.agents.validators.functions.validate_keywords"
    validator_args:
      required_keywords: ["API", "authentication", "security"]
    on_failure: retry
```

**Validator signature:**
```python
validate_keywords(content: str, required_keywords: List[str]) -> Tuple[bool, str | None]
```

## Reprompt Strategies

Choose how improved prompts are generated when validation fails.

### LLM Strategy

Uses an LLM to analyze the failure and generate improved prompts. Best for complex validations and nuanced failures.

```yaml
interceptors:
  - type: reprompt
    strategy: "llm"
    max_attempts: 3
    llm_config:
      model_vendor: "openai"
      model_name: "gpt-4"
```

**When to use:**
- Complex validation failures
- Nuanced requirements
- You want intelligent prompt improvements

**Pros:** Most sophisticated, understands context
**Cons:** Requires additional LLM call (slower, costs more)

### Simple Strategy

Appends the validation error message to the original prompt. Best for clear, actionable error messages.

```yaml
interceptors:
  - type: reprompt
    strategy: "simple"
    max_attempts: 2
```

**When to use:**
- Basic validations with clear errors
- You want fast retries
- Error messages are self-explanatory

**Pros:** Fast, no extra LLM calls
**Cons:** Less sophisticated improvements

**Example output:**
```
Original prompt: "Summarize this in 5 words"

After validation fails (got 8 words):
"Summarize this in 5 words

Previous attempt failed: Expected 5 words, got 8"
```

### Template Strategy

Uses predefined templates matched to error patterns. Best for known failure types.

```yaml
interceptors:
  - type: reprompt
    strategy: "template"
    max_attempts: 2
    templates:
      "too short": |
        {original_prompt}

        IMPORTANT: Your response must be at least {min_chars} characters long.
        Previous attempt was too short.

      "missing keywords": |
        {original_prompt}

        CRITICAL: You MUST include these keywords: {required_keywords}
```

**When to use:**
- Known, predictable failure patterns
- You want full control over retry prompts
- Structured requirements

**Pros:** Precise control, consistent improvements
**Cons:** Requires upfront template definition

## Custom Validators

Create your own validators for domain-specific validation logic.

### Validator Function Requirements

Custom validators must follow this signature:

```python
from typing import Tuple

def my_validator(response: Any, **kwargs) -> Tuple[bool, str | None]:
    """
    Args:
        response: The LLM response to validate
        **kwargs: validator_args from config + workflow context

    Returns:
        (is_valid, error_message)
        - is_valid: True if validation passes
        - error_message: None if valid, error description if invalid
    """
    # Your validation logic here
    pass
```

### Where to Place Validators

Place custom validators in your `tools` directory:

```
project/
├── workflows/
│   └── my_workflow.yml
├── tools/
│   └── my_validators.py    # ← Place validators here
└── agent_actions.yml
```

### How to Reference Validators

Reference validators using `module_name.function_name`:

```yaml
tools:
  path: "./tools"

interceptors:
  - type: validation
    validator_function: "my_validators.validate_json_structure"  # module.function
    validator_args:
      required_fields: ["name", "email"]
```

### Complete Example: JSON Validator

**1. Create validator function** (`tools/my_validators.py`):

```python
from typing import Tuple
import json

def validate_json_structure(response: str, required_fields: list = None, **kwargs) -> Tuple[bool, str | None]:
    """Validate that response is valid JSON with required fields."""

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"

    if required_fields:
        missing = [f for f in required_fields if f not in data]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

    return True, None
```

**2. Configure in workflow** (`workflows/extract.yml`):

```yaml
tools:
  path: "./tools"

agents:
  - agent_type: DataExtractor
    model_vendor: "openai"
    prompt: "Extract user data as JSON with fields: name, email, phone"

    interceptors:
      - type: validation
        validator_function: "my_validators.validate_json_structure"
        validator_args:
          required_fields: ["name", "email", "phone"]
        on_failure: retry

      - type: reprompt
        strategy: "llm"
        max_attempts: 3
        llm_config:
          model_vendor: "openai"
          model_name: "gpt-4"
```

### Accessing Context Data

Validators can access workflow context data through `**kwargs`:

```python
def validate_word_count_from_context(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Validate word count using value from workflow context."""

    # Access validator_args
    expected = kwargs.get("expected", 5)

    # Access workflow context (from record data)
    target_count = kwargs.get("target_word_count")  # From workflow data
    if target_count:
        expected = target_count

    word_count = len(response.split())
    if word_count == expected:
        return True, None
    return False, f"Expected {expected} words, got {word_count}"
```

## Error Handling

Control what happens when validation fails using `on_failure`:

### retry (default)

Trigger reprompt interceptor to improve and retry:

```yaml
interceptors:
  - type: validation
    validator_function: "my_validators.check_format"
    on_failure: retry  # Default behavior
```

### fail

Stop immediately and raise error:

```yaml
interceptors:
  - type: validation
    validator_function: "my_validators.critical_check"
    on_failure: fail  # Fail fast
```

**When to use:** Critical validations that must pass, no retry makes sense

### continue

Log error but continue processing:

```yaml
interceptors:
  - type: validation
    validator_function: "my_validators.optional_check"
    on_failure: continue  # Non-blocking
```

**When to use:** Optional validations, soft checks, monitoring

## Advanced Patterns

### Chaining Multiple Validators

Run multiple validators in sequence:

```yaml
interceptors:
  # Check 1: Validate format
  - type: validation
    validator_function: "my_validators.validate_json"
    on_failure: retry

  # Check 2: Validate content (only runs if format valid)
  - type: validation
    validator_function: "my_validators.validate_required_fields"
    validator_args:
      required_fields: ["id", "name", "status"]
    on_failure: retry

  # Reprompt on any failure
  - type: reprompt
    strategy: "llm"
    max_attempts: 3
```

### Different Strategies Per Attempt

Validators receive attempt number via context:

```python
def adaptive_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Different validation based on attempt."""
    attempt = kwargs.get("attempt", 0)

    if attempt == 0:
        # First attempt: strict validation
        return strict_check(response)
    else:
        # Later attempts: relaxed validation
        return relaxed_check(response)
```

### Using Workflow Context in Validators

Access record data in validators:

```yaml
# workflow with record data
data:
  - {"article": "...", "target_words": 5}
  - {"article": "...", "target_words": 10}

agents:
  - agent_type: Summarizer
    prompt: "Summarize: {article}"
    interceptors:
      - type: validation
        validator_function: "my_validators.validate_dynamic_count"
        # target_words available in kwargs automatically
```

```python
def validate_dynamic_count(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Use target_words from workflow data."""
    expected = kwargs.get("target_words", 5)  # From record
    word_count = len(response.split())

    if word_count == expected:
        return True, None
    return False, f"Expected {expected} words, got {word_count}"
```

## Troubleshooting

### Validator Not Found

**Error:** `"Validator function error: Module 'my_validators' not found"`

**Solutions:**
1. Check `tools.path` is correctly configured:
   ```yaml
   tools:
     path: "./tools"  # Must point to directory containing validators
   ```

2. Ensure validator file exists: `tools/my_validators.py`

3. Verify function reference format: `"module_name.function_name"`

### Infinite Retry Loops

**Symptom:** Retries continue without success

**Solutions:**
1. Set reasonable `max_attempts`:
   ```yaml
   interceptors:
     - type: reprompt
       max_attempts: 3  # Don't set too high
   ```

2. Check validator logic is achievable:
   ```python
   # BAD: Impossible to satisfy
   def bad_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
       return False, "Always fails"

   # GOOD: Has success condition
   def good_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
       if len(response) > 10:
           return True, None
       return False, "Too short"
   ```

3. Use `on_failure: fail` for debugging:
   ```yaml
   - type: validation
     validator_function: "my_validators.debug_check"
     on_failure: fail  # See error immediately
   ```

### Validation Errors Not Clear

**Problem:** Reprompt doesn't improve because error message is vague

**Solution:** Return specific, actionable error messages:

```python
# BAD: Vague error
def bad_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    if not is_valid(response):
        return False, "Invalid"  # Not helpful

# GOOD: Specific error
def good_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    required = kwargs.get("required_fields", [])
    data = json.loads(response)
    missing = [f for f in required if f not in data]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}. Please include these in your JSON response."
    return True, None
```

### Debugging Reprompt Generation

Enable debug mode to see what's happening:

```yaml
agents:
  - agent_type: Debugger
    prompt_debug: true  # Enable debug output

    interceptors:
      - type: validation
        validator_function: "my_validators.test"
        on_failure: retry

      - type: reprompt
        strategy: "simple"
        max_attempts: 2
```

**Debug output shows:**
- Validation results (pass/fail)
- Error messages
- Generated improved prompts
- Attempt numbers
- Context data

### Validator Returns Wrong Type

**Error:** `"Validator must return Tuple[bool, str | None]"`

**Solution:** Always return tuple:

```python
# BAD: Returns wrong type
def bad_validator(response: str, **kwargs):
    return True  # Missing error message part

# GOOD: Returns tuple
def good_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    return True, None  # Always return both parts
```

## Next Steps

- [Configuration Reference](../reference/configuration-fields.md) - All interceptor options
- [Examples](../examples/configurations/08-reprompting-validators.md) - More configuration examples
- [Custom Validator Examples](../examples/custom-validators.md) - Code examples
- [Error Handling](../core-concepts/error-handling.md) - Advanced error handling
