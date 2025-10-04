---
title: Validation UDF Examples
description: Common validation patterns with @udf_tool
sidebar_position: 3
---

# Validation UDF Examples

Collection of common validation patterns using the `@udf_tool` decorator for data quality and business rule enforcement.

## Overview

Validation UDFs check data against rules and constraints. They either:
- **Return the original data** if valid
- **Raise ValueError** with a descriptive message if invalid

## Pattern 1: Required Fields Validation

**Use case**: Ensure all required fields are present

```python
from agent_actions import udf_tool

@udf_tool
def validate_required_fields(data, **kwargs):
    """
    Validate that all required fields are present and non-null.

    Config usage:
      validator_args:
        fields: ['name', 'email', 'age']
    """
    required_fields = kwargs.get('validator_args', {}).get('fields', [])

    if not required_fields:
        raise ValueError("No required fields specified in validator_args")

    missing = []
    for field in required_fields:
        if field not in data or data[field] is None:
            missing.append(field)

    if missing:
        raise ValueError(
            f"Missing required fields: {', '.join(missing)}. "
            f"Received fields: {', '.join(data.keys())}"
        )

    return data
```

**Config**:
```yaml
actions:
  - name: check_required
    impl: validate_required_fields
    validator_args:
      fields: ['customer_name', 'email', 'order_id']
```

## Pattern 2: Email Validation

**Use case**: Validate email address format

```python
from agent_actions import udf_tool
import re

@udf_tool
def validate_email_address(data, **kwargs):
    """
    Validate email field has correct format.

    Checks:
      - Contains @ symbol
      - Has valid domain structure
      - No spaces
      - Valid characters only

    Config usage:
      Validates 'email' field in data dict
    """
    email = data.get('email', '')

    if not email:
        raise ValueError("Email field is missing or empty")

    # Email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(pattern, email):
        raise ValueError(
            f"Invalid email format: '{email}'. "
            "Expected format: user@domain.com"
        )

    # Additional checks
    if ' ' in email:
        raise ValueError(f"Email cannot contain spaces: '{email}'")

    if email.count('@') != 1:
        raise ValueError(f"Email must contain exactly one @ symbol: '{email}'")

    return data
```

## Pattern 3: Numeric Range Validation

**Use case**: Validate numeric fields are within acceptable ranges

```python
from agent_actions import udf_tool

@udf_tool
def validate_numeric_range(data, **kwargs):
    """
    Validate numeric field is within specified range.

    Config usage:
      validator_args:
        field: 'age'
        min: 0
        max: 150
    """
    args = kwargs.get('validator_args', {})
    field = args.get('field')
    min_val = args.get('min')
    max_val = args.get('max')

    if not field:
        raise ValueError("validator_args must specify 'field'")

    if field not in data:
        raise ValueError(f"Field '{field}' not found in data")

    value = data[field]

    # Check type
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"Field '{field}' must be numeric, got {type(value).__name__}"
        )

    # Check minimum
    if min_val is not None and value < min_val:
        raise ValueError(
            f"Field '{field}' value {value} is below minimum {min_val}"
        )

    # Check maximum
    if max_val is not None and value > max_val:
        raise ValueError(
            f"Field '{field}' value {value} exceeds maximum {max_val}"
        )

    return data
```

**Config**:
```yaml
actions:
  - name: validate_age
    impl: validate_numeric_range
    validator_args:
      field: 'age'
      min: 18
      max: 120

  - name: validate_price
    impl: validate_numeric_range
    validator_args:
      field: 'price'
      min: 0.01
      max: 100000
```

## Pattern 4: Enum/Choice Validation

**Use case**: Validate field value is from allowed list

```python
from agent_actions import udf_tool

@udf_tool
def validate_enum_value(data, **kwargs):
    """
    Validate field value is one of allowed choices.

    Config usage:
      validator_args:
        field: 'status'
        choices: ['pending', 'approved', 'rejected']
    """
    args = kwargs.get('validator_args', {})
    field = args.get('field')
    choices = args.get('choices', [])

    if not field:
        raise ValueError("validator_args must specify 'field'")

    if not choices:
        raise ValueError("validator_args must specify 'choices' list")

    if field not in data:
        raise ValueError(f"Field '{field}' not found in data")

    value = data[field]

    # Case-insensitive comparison
    value_lower = value.lower() if isinstance(value, str) else value
    choices_lower = [c.lower() if isinstance(c, str) else c for c in choices]

    if value_lower not in choices_lower:
        raise ValueError(
            f"Field '{field}' has invalid value '{value}'. "
            f"Allowed values: {', '.join(map(str, choices))}"
        )

    return data
```

**Config**:
```yaml
actions:
  - name: validate_order_status
    impl: validate_enum_value
    validator_args:
      field: 'status'
      choices: ['pending', 'processing', 'shipped', 'delivered', 'cancelled']
```

## Pattern 5: JSON Structure Validation

**Use case**: Validate JSON has expected structure

```python
from agent_actions import udf_tool

@udf_tool
def validate_json_structure(data, **kwargs):
    """
    Validate data has expected nested structure.

    Config usage:
      validator_args:
        required_keys: ['user', 'order', 'items']
        nested_checks:
          user: ['id', 'email']
          order: ['total', 'date']
    """
    args = kwargs.get('validator_args', {})
    required_keys = args.get('required_keys', [])
    nested_checks = args.get('nested_checks', {})

    # Check top-level keys
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required top-level keys: {', '.join(missing_keys)}"
        )

    # Check nested structures
    for parent_key, child_keys in nested_checks.items():
        if parent_key not in data:
            raise ValueError(f"Missing nested object: '{parent_key}'")

        parent_obj = data[parent_key]

        if not isinstance(parent_obj, dict):
            raise ValueError(
                f"Key '{parent_key}' must be an object, got {type(parent_obj).__name__}"
            )

        missing_children = [
            key for key in child_keys
            if key not in parent_obj
        ]

        if missing_children:
            raise ValueError(
                f"Missing keys in '{parent_key}': {', '.join(missing_children)}"
            )

    return data
```

**Config**:
```yaml
actions:
  - name: validate_order_structure
    impl: validate_json_structure
    validator_args:
      required_keys: ['customer', 'order', 'items']
      nested_checks:
        customer: ['id', 'name', 'email']
        order: ['order_id', 'total', 'created_at']
```

## Pattern 6: String Format Validation

**Use case**: Validate string matches expected format/pattern

```python
from agent_actions import udf_tool
import re

@udf_tool
def validate_string_pattern(data, **kwargs):
    """
    Validate string field matches regex pattern.

    Config usage:
      validator_args:
        field: 'sku'
        pattern: '^[A-Z]{3}-\d{4}$'
        description: 'ABC-1234 format'
    """
    args = kwargs.get('validator_args', {})
    field = args.get('field')
    pattern = args.get('pattern')
    description = args.get('description', 'expected format')

    if not field or not pattern:
        raise ValueError("validator_args must specify 'field' and 'pattern'")

    if field not in data:
        raise ValueError(f"Field '{field}' not found in data")

    value = data[field]

    if not isinstance(value, str):
        raise ValueError(
            f"Field '{field}' must be a string, got {type(value).__name__}"
        )

    if not re.match(pattern, value):
        raise ValueError(
            f"Field '{field}' value '{value}' does not match {description}. "
            f"Pattern: {pattern}"
        )

    return data
```

**Config examples**:
```yaml
actions:
  # SKU validation
  - name: validate_sku
    impl: validate_string_pattern
    validator_args:
      field: 'sku'
      pattern: '^[A-Z]{3}-\d{4}$'
      description: '3 uppercase letters, hyphen, 4 digits (e.g., ABC-1234)'

  # Phone validation
  - name: validate_phone
    impl: validate_string_pattern
    validator_args:
      field: 'phone'
      pattern: '^\+1-\d{3}-\d{3}-\d{4}$'
      description: 'US phone format: +1-555-123-4567'

  # Date validation
  - name: validate_date
    impl: validate_string_pattern
    validator_args:
      field: 'created_date'
      pattern: '^\d{4}-\d{2}-\d{2}$'
      description: 'ISO date format: YYYY-MM-DD'
```

## Pattern 7: Business Rule Validation

**Use case**: Enforce complex business logic

```python
from agent_actions import udf_tool
from datetime import datetime, timedelta

@udf_tool
def validate_order_business_rules(data, **kwargs):
    """
    Validate order meets all business rules.

    Rules:
      - Order total matches sum of item prices
      - Shipping date is after order date
      - Quantity is positive for all items
      - Discount doesn't exceed total
    """
    # Rule 1: Total matches sum of items
    items = data.get('items', [])
    if not items:
        raise ValueError("Order must have at least one item")

    calculated_total = sum(
        item.get('price', 0) * item.get('quantity', 0)
        for item in items
    )

    order_total = data.get('total', 0)
    if abs(calculated_total - order_total) > 0.01:  # Allow small rounding diff
        raise ValueError(
            f"Order total ${order_total} does not match sum of items ${calculated_total}"
        )

    # Rule 2: Shipping date validation
    order_date = datetime.fromisoformat(data.get('order_date', ''))
    ship_date = datetime.fromisoformat(data.get('ship_date', ''))

    if ship_date <= order_date:
        raise ValueError("Shipping date must be after order date")

    max_ship_delay = timedelta(days=30)
    if ship_date - order_date > max_ship_delay:
        raise ValueError("Shipping date cannot be more than 30 days after order")

    # Rule 3: Positive quantities
    for i, item in enumerate(items):
        qty = item.get('quantity', 0)
        if qty <= 0:
            raise ValueError(f"Item {i+1} quantity must be positive, got {qty}")

    # Rule 4: Discount validation
    discount = data.get('discount', 0)
    if discount < 0:
        raise ValueError("Discount cannot be negative")

    if discount > order_total:
        raise ValueError(
            f"Discount ${discount} cannot exceed order total ${order_total}"
        )

    return data
```

## Pattern 8: Conditional Validation

**Use case**: Validate based on other field values

```python
from agent_actions import udf_tool

@udf_tool
def validate_conditional_requirements(data, **kwargs):
    """
    Validate fields required based on other field values.

    Example: If order_type is 'international', require customs_info
    """
    order_type = data.get('order_type', '').lower()

    # International orders need customs info
    if order_type == 'international':
        if 'customs_info' not in data:
            raise ValueError(
                "International orders must include 'customs_info' field"
            )

        customs = data['customs_info']
        required_customs_fields = ['country_of_origin', 'hs_code', 'value']

        missing = [
            field for field in required_customs_fields
            if field not in customs
        ]

        if missing:
            raise ValueError(
                f"customs_info missing required fields: {', '.join(missing)}"
            )

    # Express shipping needs delivery time
    shipping_speed = data.get('shipping_speed', '').lower()
    if shipping_speed == 'express':
        if 'delivery_time' not in data:
            raise ValueError("Express shipping requires 'delivery_time' field")

    # Corporate orders need company info
    customer_type = data.get('customer_type', '').lower()
    if customer_type == 'corporate':
        if 'company_name' not in data or 'tax_id' not in data:
            raise ValueError(
                "Corporate orders require 'company_name' and 'tax_id'"
            )

    return data
```

## Complete Validation Pipeline Example

**`user_code/validators/order_validators.py`**:
```python
from agent_actions import udf_tool

# Combine multiple validators above...
@udf_tool
def validate_required_fields(data, **kwargs):
    # ... implementation

@udf_tool
def validate_email_address(data, **kwargs):
    # ... implementation

@udf_tool
def validate_numeric_range(data, **kwargs):
    # ... implementation

@udf_tool
def validate_order_business_rules(data, **kwargs):
    # ... implementation
```

**`agent_configs/order_validator.yml`**:
```yaml
agent: order_validator
description: "Comprehensive order validation pipeline"

actions:
  # Stage 1: Basic field validation
  - name: check_required_fields
    impl: validate_required_fields
    validator_args:
      fields: ['customer_email', 'items', 'total', 'order_date']

  - name: validate_customer_email
    impl: validate_email_address

  - name: validate_total_amount
    impl: validate_numeric_range
    validator_args:
      field: 'total'
      min: 0.01
      max: 1000000

  # Stage 2: Business rules
  - name: enforce_business_rules
    impl: validate_order_business_rules

  # Stage 3: Conditional requirements
  - name: check_conditional_fields
    impl: validate_conditional_requirements
```

## Testing Validators

```python
import pytest
from user_code.validators.order_validators import validate_required_fields

def test_required_fields_all_present():
    data = {'name': 'John', 'email': 'john@test.com', 'age': 30}
    kwargs = {'validator_args': {'fields': ['name', 'email', 'age']}}

    result = validate_required_fields(data, **kwargs)
    assert result == data

def test_required_fields_missing():
    data = {'name': 'John'}
    kwargs = {'validator_args': {'fields': ['name', 'email', 'age']}}

    with pytest.raises(ValueError, match="Missing required fields: email, age"):
        validate_required_fields(data, **kwargs)

def test_required_fields_null_value():
    data = {'name': 'John', 'email': None}
    kwargs = {'validator_args': {'fields': ['name', 'email']}}

    with pytest.raises(ValueError, match="Missing required fields: email"):
        validate_required_fields(data, **kwargs)
```

## Key Takeaways

1. **Raise ValueError** with descriptive messages for validation failures
2. **Return original data** when validation passes
3. **Use validator_args** for configurable validation rules
4. **Validate early** to fail fast and provide clear feedback
5. **Test thoroughly** with both valid and invalid cases
6. **Provide context** in error messages (field name, expected format, actual value)

## Next Steps

- **Transformations**: See [Transformation UDFs](./transformation-udfs) for data processing
- **Organization**: Learn [Multiple Files](./multiple-files) for larger projects
- **Full guide**: Read the [UDF Decorator Guide](/guides/udf-decorator)
