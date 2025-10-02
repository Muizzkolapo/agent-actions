---
title: Reprompting & Validators
description: Configuration examples for validation and automatic reprompting
sidebar_position: 8
---

# Reprompting & Validators Examples

Complete configuration examples showing how to use validation interceptors and automatic reprompting.

## Example 1: Basic Word Count Validation

Ensure the LLM generates exactly N words using the built-in validator.

```yaml
# workflows/summarize.yml
tools:
  path: "./tools"

data:
  loader: csv_loader
  source: "./data/articles.csv"

agents:
  - agent_type: Summarizer
    name: create_summary
    intent: Summarize article in exactly 5 words
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Summarize this article in exactly 5 words: {article}"

    interceptors:
      # Validate word count
      - type: validation
        validator_function: "agent_actions.agents.validators.functions.validate_word_count"
        validator_args:
          expected: 5
        on_failure: retry

      # Generate improved prompt on failure
      - type: reprompt
        strategy: "simple"
        max_attempts: 3

output:
  - type: csv_output
    path: "./output/summaries.csv"
```

**How it works:**
1. LLM attempts to generate 5-word summary
2. `validate_word_count` checks exact word count
3. If wrong, `simple` strategy appends error to prompt
4. Retries up to 3 times

## Example 2: JSON Structure Validation

Validate that response is valid JSON with required fields using a custom validator.

### Custom Validator (`tools/json_validators.py`)

```python
from typing import Tuple
import json

def validate_json_structure(response: str, required_fields: list = None, **kwargs) -> Tuple[bool, str | None]:
    """Validate response is valid JSON with required fields."""

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON format: {str(e)}. Please return valid JSON."

    if required_fields:
        missing = [f for f in required_fields if f not in data]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}. Your JSON must include: {', '.join(required_fields)}"

    return True, None
```

### Configuration (`workflows/extract_data.yml`)

```yaml
tools:
  path: "./tools"

data:
  loader: csv_loader
  source: "./data/users.csv"

agents:
  - agent_type: DataExtractor
    name: extract_user_data
    intent: Extract user information as structured JSON
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: |
      Extract user data from this text and return as JSON with these fields:
      - name
      - email
      - phone

      Text: {user_text}

    interceptors:
      # Validate JSON structure
      - type: validation
        validator_function: "json_validators.validate_json_structure"
        validator_args:
          required_fields: ["name", "email", "phone"]
        on_failure: retry

      # Use LLM to improve prompt
      - type: reprompt
        strategy: "llm"
        max_attempts: 3
        llm_config:
          model_vendor: "openai"
          model_name: "gpt-4"

output:
  - type: json_output
    path: "./output/extracted_users.json"
```

**How it works:**
1. LLM extracts data and returns JSON
2. Custom validator checks JSON validity and required fields
3. If invalid, LLM strategy analyzes failure and generates better prompt
4. Retries with improved instructions

## Example 3: Content Quality Validation

Combine multiple validators to ensure content meets quality standards.

### Custom Validators (`tools/content_validators.py`)

```python
from typing import Tuple, List

def validate_char_count_range(content: str, min_chars: int = 100, max_chars: int = 500, **kwargs) -> Tuple[bool, str | None]:
    """Validate content length is within range."""
    char_count = len(content)

    if char_count < min_chars:
        return False, f"Content too short ({char_count} chars). Minimum: {min_chars} characters."

    if char_count > max_chars:
        return False, f"Content too long ({char_count} chars). Maximum: {max_chars} characters."

    return True, None

def validate_required_keywords(content: str, keywords: List[str], **kwargs) -> Tuple[bool, str | None]:
    """Validate content contains all required keywords."""
    content_lower = content.lower()
    missing = [kw for kw in keywords if kw.lower() not in content_lower]

    if missing:
        return False, f"Missing required keywords: {', '.join(missing)}. Please include these terms in your response."

    return True, None
```

### Configuration (`workflows/content_generation.yml`)

```yaml
tools:
  path: "./tools"

data:
  loader: csv_loader
  source: "./data/topics.csv"

agents:
  - agent_type: ContentGenerator
    name: generate_description
    intent: Generate product description with quality checks
    model_vendor: "anthropic"
    model_name: "claude-3-5-sonnet-20241022"
    prompt: |
      Write a product description for: {product_name}

      Requirements:
      - Between 100-300 characters
      - Must mention: {required_features}

    interceptors:
      # Check 1: Character count
      - type: validation
        validator_function: "content_validators.validate_char_count_range"
        validator_args:
          min_chars: 100
          max_chars: 300
        on_failure: retry

      # Check 2: Required keywords (from workflow data)
      - type: validation
        validator_function: "content_validators.validate_required_keywords"
        validator_args:
          keywords: ["{required_features}"]  # From data
        on_failure: retry

      # Reprompt with templates
      - type: reprompt
        strategy: "template"
        max_attempts: 3
        templates:
          "too short": |
            {original_prompt}

            IMPORTANT: Your previous response was only {char_count} characters.
            Please expand to at least {min_chars} characters.

          "too long": |
            {original_prompt}

            IMPORTANT: Your previous response was {char_count} characters.
            Please condense to maximum {max_chars} characters.

          "missing keywords": |
            {original_prompt}

            CRITICAL: You must include these keywords: {keywords}
            Previous attempt was missing: {missing}

output:
  - type: csv_output
    path: "./output/descriptions.csv"
```

**How it works:**
1. LLM generates product description
2. First validator checks character count
3. Second validator checks required keywords
4. If either fails, template strategy uses pattern-matched improvements
5. Specific templates for "too short", "too long", "missing keywords" errors

## Example 4: Advanced Multi-Stage Validation

Different validation strategies at different stages with progressive fallbacks.

### Custom Validators (`tools/advanced_validators.py`)

```python
from typing import Tuple
import json

def validate_strict_format(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Strict validation for first attempts."""
    attempt = kwargs.get("attempt", 0)

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"

    # First attempt: require all optional fields
    if attempt == 0:
        required = ["id", "name", "email", "phone", "address", "notes"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, f"Missing fields: {', '.join(missing)}"
    else:
        # Later attempts: only require core fields
        required = ["id", "name", "email"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, f"Missing critical fields: {', '.join(missing)}"

    return True, None

def validate_email_format(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Validate email format in JSON response."""
    import re

    try:
        data = json.loads(response)
    except:
        return True, None  # Let other validator handle JSON errors

    if "email" in data:
        email = data["email"]
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False, f"Invalid email format: {email}. Use format: user@domain.com"

    return True, None
```

### Configuration (`workflows/progressive_validation.yml`)

```yaml
tools:
  path: "./tools"

data:
  loader: json_loader
  source: "./data/contacts.json"

agents:
  - agent_type: ContactExtractor
    name: extract_contact
    intent: Extract contact information with progressive validation
    model_vendor: "openai"
    model_name: "gpt-4-turbo"
    prompt: |
      Extract contact information from this text as JSON:
      {contact_text}

      Include: id, name, email, phone, address, notes

    interceptors:
      # Validation 1: Format check (relaxes on retry)
      - type: validation
        validator_function: "advanced_validators.validate_strict_format"
        on_failure: retry

      # Validation 2: Email format
      - type: validation
        validator_function: "advanced_validators.validate_email_format"
        on_failure: retry

      # Reprompt: LLM-based for intelligent improvements
      - type: reprompt
        strategy: "llm"
        max_attempts: 3
        llm_config:
          model_vendor: "openai"
          model_name: "gpt-4"
          temperature: 0.7

output:
  - type: json_output
    path: "./output/contacts.json"
```

**How it works:**
1. First attempt: Strict validation (all fields required)
2. If fails, LLM strategy generates better prompt
3. Second attempt: Relaxed validation (only core fields)
4. Email validator runs on all attempts
5. Progressive relaxation prevents infinite loops while maintaining quality

## Example 5: Context-Aware Validation

Use workflow data in validators for dynamic validation criteria.

### Custom Validator (`tools/dynamic_validators.py`)

```python
from typing import Tuple

def validate_dynamic_word_count(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Validate word count using value from workflow context."""

    # Try to get target from validator_args first
    target = kwargs.get("target_words")

    # If not in args, try to get from workflow context
    if target is None:
        target = kwargs.get("expected_words", 5)  # From data column

    word_count = len(response.split())

    if word_count == target:
        return True, None

    return False, f"Expected {target} words (from data), got {word_count}"
```

### Configuration (`workflows/dynamic_validation.yml`)

```yaml
tools:
  path: "./tools"

# Data with varying requirements
data:
  loader: csv_loader
  source: "./data/summaries.csv"
  # CSV columns: article, expected_words

agents:
  - agent_type: DynamicSummarizer
    name: create_summary
    intent: Summarize with dynamic word count from data
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Summarize in exactly {expected_words} words: {article}"

    interceptors:
      # Validator accesses expected_words from data row
      - type: validation
        validator_function: "dynamic_validators.validate_dynamic_word_count"
        # No validator_args needed - uses context
        on_failure: retry

      - type: reprompt
        strategy: "simple"
        max_attempts: 3

output:
  - type: csv_output
    path: "./output/summaries.csv"
```

**Data example** (`data/summaries.csv`):
```csv
article,expected_words
"Long article about AI...",10
"Short news update...",5
"Detailed analysis...",15
```

**How it works:**
1. Each row has different `expected_words` value
2. Validator accesses `expected_words` from `**kwargs`
3. Dynamically validates based on row-specific requirement
4. Works with any workflow data structure

## Configuration Tips

### Choosing a Reprompt Strategy

**Use `llm` when:**
- Validation failures are complex
- You need intelligent analysis of errors
- Cost/speed trade-off favors quality

**Use `simple` when:**
- Error messages are clear and actionable
- You want fast retries
- Cost is a concern

**Use `template` when:**
- You know failure patterns in advance
- You want precise control over retry prompts
- You have structured requirements

### Setting max_attempts

```yaml
# Conservative (fast failure)
max_attempts: 2

# Standard (balance)
max_attempts: 3

# Aggressive (maximize success rate)
max_attempts: 5
```

**Consider:**
- Cost: More attempts = more API calls
- Time: Each attempt adds latency
- Success rate: Diminishing returns after 3-4 attempts

### Error Handling Strategies

```yaml
# Critical validation - fail fast
on_failure: fail

# Standard validation - retry with reprompt
on_failure: retry

# Optional validation - log but continue
on_failure: continue
```

## Next Steps

- [Reprompting Guide](../../guides/reprompting.md) - Detailed documentation
- [Custom Validators](../custom-validators.md) - More code examples
- [Configuration Reference](../../reference/configuration-fields.md#interceptors) - All options
