---
title: Custom Validator Examples
description: Code examples for creating custom validation functions
sidebar_position: 9
---

# Custom Validator Examples

Complete code examples showing how to create custom validators for different use cases.

## Validator Function Requirements

All custom validators must follow this signature:

```python
from typing import Tuple, Any

def my_validator(response: Any, **kwargs) -> Tuple[bool, str | None]:
    """
    Args:
        response: The LLM response to validate
        **kwargs: Contains validator_args + workflow context data

    Returns:
        (is_valid, error_message)
        - is_valid: True if validation passes, False otherwise
        - error_message: None if valid, descriptive error message if invalid
    """
    # Validation logic here
    pass
```

## Example 1: JSON Structure Validator

Validates response is valid JSON with required fields.

```python
# tools/json_validators.py
from typing import Tuple
import json

def validate_json_structure(response: str, required_fields: list = None, **kwargs) -> Tuple[bool, str | None]:
    """
    Validate that response is valid JSON with all required fields.

    Args:
        response: String response from LLM
        required_fields: List of field names that must be present
        **kwargs: Additional context (unused in this validator)

    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    # Check 1: Valid JSON
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON format: {str(e)}. Please return valid JSON with proper syntax."

    # Check 2: Required fields present
    if required_fields:
        missing = [field for field in required_fields if field not in data]
        if missing:
            return False, (
                f"Missing required fields: {', '.join(missing)}. "
                f"Your JSON must include all of: {', '.join(required_fields)}"
            )

    return True, None
```

**Usage:**
```yaml
interceptors:
  - type: validation
    validator_function: "json_validators.validate_json_structure"
    validator_args:
      required_fields: ["name", "email", "phone"]
    on_failure: retry
```

## Example 2: Email Format Validator

Validates email addresses in response using regex.

```python
# tools/format_validators.py
from typing import Tuple
import re
import json

def validate_email_format(response: str, email_field: str = "email", **kwargs) -> Tuple[bool, str | None]:
    """
    Validate email format in JSON response.

    Args:
        response: JSON string containing email
        email_field: Name of the field containing the email
        **kwargs: Additional context

    Returns:
        (True, None) if email is valid
        (False, error_message) if email is invalid
    """
    # Parse JSON response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        # Let JSON validator handle this
        return True, None

    # Check if email field exists
    if email_field not in data:
        return False, f"Missing '{email_field}' field in response."

    email = data[email_field]

    # Validate email format
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, (
            f"Invalid email format: '{email}'. "
            f"Use format: username@domain.com"
        )

    return True, None


def validate_phone_format(response: str, phone_field: str = "phone", **kwargs) -> Tuple[bool, str | None]:
    """Validate phone number format (US format)."""
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return True, None

    if phone_field not in data:
        return False, f"Missing '{phone_field}' field."

    phone = data[phone_field]

    # Allow formats: (123) 456-7890, 123-456-7890, 1234567890
    phone_pattern = r'^(\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}$'
    if not re.match(phone_pattern, phone):
        return False, (
            f"Invalid phone format: '{phone}'. "
            f"Use format: (123) 456-7890 or 123-456-7890"
        )

    return True, None
```

**Usage:**
```yaml
interceptors:
  - type: validation
    validator_function: "format_validators.validate_email_format"
    validator_args:
      email_field: "email"
    on_failure: retry

  - type: validation
    validator_function: "format_validators.validate_phone_format"
    validator_args:
      phone_field: "contact_number"
    on_failure: retry
```

## Example 3: Date Range Validator

Validates dates fall within specified range.

```python
# tools/date_validators.py
from typing import Tuple
from datetime import datetime
import json

def validate_date_range(
    response: str,
    date_field: str = "date",
    min_date: str = None,
    max_date: str = None,
    date_format: str = "%Y-%m-%d",
    **kwargs
) -> Tuple[bool, str | None]:
    """
    Validate date is within specified range.

    Args:
        response: JSON string containing date
        date_field: Name of the field containing the date
        min_date: Minimum date (string in date_format)
        max_date: Maximum date (string in date_format)
        date_format: strptime format string
        **kwargs: Additional context

    Returns:
        (True, None) if date is valid and in range
        (False, error_message) otherwise
    """
    # Parse response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return True, None  # Let JSON validator handle this

    # Check field exists
    if date_field not in data:
        return False, f"Missing '{date_field}' field."

    date_str = data[date_field]

    # Parse date
    try:
        date_obj = datetime.strptime(date_str, date_format)
    except ValueError:
        return False, (
            f"Invalid date format: '{date_str}'. "
            f"Expected format: {date_format} (e.g., 2024-01-31)"
        )

    # Validate range
    if min_date:
        min_obj = datetime.strptime(min_date, date_format)
        if date_obj < min_obj:
            return False, (
                f"Date {date_str} is before minimum date {min_date}. "
                f"Please use a date on or after {min_date}."
            )

    if max_date:
        max_obj = datetime.strptime(max_date, date_format)
        if date_obj > max_obj:
            return False, (
                f"Date {date_str} is after maximum date {max_date}. "
                f"Please use a date on or before {max_date}."
            )

    return True, None
```

**Usage:**
```yaml
interceptors:
  - type: validation
    validator_function: "date_validators.validate_date_range"
    validator_args:
      date_field: "event_date"
      min_date: "2024-01-01"
      max_date: "2024-12-31"
      date_format: "%Y-%m-%d"
    on_failure: retry
```

## Example 4: Contextual Validator

Uses workflow context data for dynamic validation.

```python
# tools/contextual_validators.py
from typing import Tuple

def validate_word_count_from_context(response: str, **kwargs) -> Tuple[bool, str | None]:
    """
    Validate word count using value from workflow context.

    This validator demonstrates accessing workflow data through kwargs.

    Args:
        response: LLM response text
        **kwargs: Contains validator_args AND workflow context
                  Can access any field from the current data row

    Returns:
        (True, None) if word count matches
        (False, error_message) if mismatch
    """
    # Priority 1: validator_args.expected (explicit config)
    expected = kwargs.get("expected")

    # Priority 2: Workflow context data
    if expected is None:
        # Try common field names from workflow data
        expected = kwargs.get("target_words") or kwargs.get("word_count") or kwargs.get("expected_words")

    # Priority 3: Default
    if expected is None:
        expected = 5

    # Validate
    word_count = len(response.split())
    if word_count == expected:
        return True, None

    return False, f"Expected {expected} words (from workflow data), got {word_count}."


def validate_contains_entity(response: str, **kwargs) -> Tuple[bool, str | None]:
    """
    Validate response contains entity from workflow context.

    Useful for workflows where each row specifies what must be in the response.
    """
    # Get entity from workflow data
    entity = kwargs.get("entity_name") or kwargs.get("required_entity")

    if not entity:
        return False, "No entity specified in workflow data. Add 'entity_name' column."

    # Check if response contains the entity
    if entity.lower() not in response.lower():
        return False, (
            f"Response must mention '{entity}'. "
            f"This entity is required based on your workflow data."
        )

    return True, None
```

**Usage with workflow data:**
```yaml
# Data with dynamic requirements
data:
  loader: csv_loader
  source: "./data/tasks.csv"
  # CSV: article,target_words,entity_name

agents:
  - agent_type: ContextualSummarizer
    prompt: "Summarize focusing on {entity_name}: {article}"

    interceptors:
      # Word count from data
      - type: validation
        validator_function: "contextual_validators.validate_word_count_from_context"
        # No args needed - uses workflow context
        on_failure: retry

      # Entity from data
      - type: validation
        validator_function: "contextual_validators.validate_contains_entity"
        on_failure: retry
```

## Example 5: Multi-Condition Validator

Complex validation with multiple conditions.

```python
# tools/complex_validators.py
from typing import Tuple
import json

def validate_product_data(response: str, **kwargs) -> Tuple[bool, str | None]:
    """
    Complex validator with multiple validation rules.

    Validates:
    - JSON structure
    - Required fields
    - Price range
    - Category validity
    - Description length
    """
    # Parse JSON
    try:
        product = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"

    errors = []

    # Rule 1: Required fields
    required_fields = kwargs.get("required_fields", ["name", "price", "category", "description"])
    missing = [f for f in required_fields if f not in product]
    if missing:
        errors.append(f"Missing fields: {', '.join(missing)}")

    # Rule 2: Price validation
    if "price" in product:
        try:
            price = float(product["price"])
            min_price = kwargs.get("min_price", 0)
            max_price = kwargs.get("max_price", 10000)

            if price < min_price:
                errors.append(f"Price ${price} below minimum ${min_price}")
            if price > max_price:
                errors.append(f"Price ${price} above maximum ${max_price}")
        except (ValueError, TypeError):
            errors.append(f"Invalid price value: {product['price']}")

    # Rule 3: Category validation
    if "category" in product:
        valid_categories = kwargs.get("valid_categories", ["electronics", "clothing", "food", "books"])
        if product["category"].lower() not in [c.lower() for c in valid_categories]:
            errors.append(
                f"Invalid category '{product['category']}'. "
                f"Must be one of: {', '.join(valid_categories)}"
            )

    # Rule 4: Description length
    if "description" in product:
        desc = product["description"]
        min_chars = kwargs.get("min_description_chars", 50)
        max_chars = kwargs.get("max_description_chars", 500)

        if len(desc) < min_chars:
            errors.append(f"Description too short ({len(desc)} chars, minimum {min_chars})")
        if len(desc) > max_chars:
            errors.append(f"Description too long ({len(desc)} chars, maximum {max_chars})")

    # Return result
    if errors:
        return False, " | ".join(errors)

    return True, None
```

**Usage:**
```yaml
interceptors:
  - type: validation
    validator_function: "complex_validators.validate_product_data"
    validator_args:
      required_fields: ["name", "price", "category", "description"]
      min_price: 1.00
      max_price: 5000.00
      valid_categories: ["electronics", "clothing", "home", "sports"]
      min_description_chars: 100
      max_description_chars: 300
    on_failure: retry
```

## Example 6: Attempt-Aware Validator

Different validation strictness based on attempt number.

```python
# tools/progressive_validators.py
from typing import Tuple
import json

def validate_with_progressive_strictness(response: str, **kwargs) -> Tuple[bool, str | None]:
    """
    Validator that relaxes requirements on retry attempts.

    First attempt: Strict validation
    Later attempts: Relaxed validation

    Useful to prevent infinite loops while maintaining quality.
    """
    attempt = kwargs.get("attempt", 0)

    # Parse response
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"

    # First attempt: Require all fields
    if attempt == 0:
        required = ["id", "name", "email", "phone", "address", "company", "notes"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, (
                f"First attempt requires all fields. Missing: {', '.join(missing)}. "
                f"Please include: {', '.join(required)}"
            )

    # Second attempt: Require important fields
    elif attempt == 1:
        required = ["id", "name", "email", "phone"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, (
                f"At minimum, include these fields: {', '.join(missing)}. "
                f"Required: {', '.join(required)}"
            )

    # Third+ attempt: Only require critical fields
    else:
        required = ["id", "name"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, (
                f"Critical fields missing: {', '.join(missing)}. "
                f"At a minimum, you MUST include: {', '.join(required)}"
            )

    return True, None
```

**Usage:**
```yaml
interceptors:
  - type: validation
    validator_function: "progressive_validators.validate_with_progressive_strictness"
    on_failure: retry

  - type: reprompt
    strategy: "llm"
    max_attempts: 3
```

## Best Practices

### 1. Clear Error Messages

```python
# ❌ Bad: Vague error
def bad_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    if not is_valid(response):
        return False, "Invalid"  # Not helpful

# ✅ Good: Specific, actionable error
def good_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    if not is_valid(response):
        return False, "Expected JSON with 'name' and 'email' fields. Your response is missing 'email'."
```

### 2. Handle Edge Cases

```python
def robust_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    # Handle None/empty
    if not response:
        return False, "Empty response received. Please provide content."

    # Handle unexpected types
    if not isinstance(response, str):
        return False, f"Expected string, got {type(response).__name__}"

    # Your validation logic
    # ...
```

### 3. Use Type Hints

```python
from typing import Tuple, List, Dict, Any

def typed_validator(
    response: str,
    required_fields: List[str] = None,
    config: Dict[str, Any] = None,
    **kwargs
) -> Tuple[bool, str | None]:
    """Type hints improve IDE support and documentation."""
    # ...
```

### 4. Document Your Validators

```python
def well_documented_validator(response: str, **kwargs) -> Tuple[bool, str | None]:
    """
    Validate response meets specific criteria.

    Args:
        response: LLM-generated response to validate
        **kwargs: Configuration and context:
            - min_length (int): Minimum character count
            - max_length (int): Maximum character count
            - attempt (int): Current retry attempt number

    Returns:
        (True, None): Validation passed
        (False, error_msg): Validation failed with reason

    Example:
        >>> validate("short", min_length=10)
        (False, "Too short: 5 chars, minimum 10")
    """
    # ...
```

### 5. Make Validators Reusable

```python
# ✅ Generic, reusable
def validate_field_presence(
    response: str,
    required_fields: List[str],
    **kwargs
) -> Tuple[bool, str | None]:
    """Works with any JSON, any fields."""
    data = json.loads(response)
    missing = [f for f in required_fields if f not in data]
    if missing:
        return False, f"Missing: {', '.join(missing)}"
    return True, None

# ❌ Too specific
def validate_user_has_email(response: str, **kwargs) -> Tuple[bool, str | None]:
    """Only works for user objects."""
    data = json.loads(response)
    if "email" not in data:
        return False, "Missing email"
    return True, None
```

## Testing Validators

Test your validators before using in production:

```python
# test_validators.py
def test_json_validator():
    from json_validators import validate_json_structure

    # Test valid JSON
    valid_json = '{"name": "John", "email": "john@example.com"}'
    is_valid, error = validate_json_structure(
        valid_json,
        required_fields=["name", "email"]
    )
    assert is_valid is True
    assert error is None

    # Test invalid JSON
    invalid_json = '{invalid}'
    is_valid, error = validate_json_structure(invalid_json)
    assert is_valid is False
    assert "Invalid JSON" in error

    # Test missing fields
    missing_field = '{"name": "John"}'
    is_valid, error = validate_json_structure(
        missing_field,
        required_fields=["name", "email"]
    )
    assert is_valid is False
    assert "email" in error
```

## Next Steps

- [Reprompting Guide](../guides/reprompting.md) - Full documentation
- [Configuration Examples](./configurations/08-reprompting-validators.md) - YAML examples
- [Configuration Reference](../reference/configuration-fields.md#interceptors) - All options
