---
title: Multiple Files Example
description: Organizing UDFs across multiple files and directories
sidebar_position: 2
---

# Organizing UDFs Across Multiple Files

Learn how to structure your UDFs across multiple files and nested directories for better organization and maintainability.

## Scenario

You're building a data processing pipeline with multiple types of UDFs:
- Email and phone validators
- Data format validators
- JSON and CSV transformers
- Data enrichment functions

## Directory Structure

```
my_project/
├── agent_actions.yml
├── agent_configs/
│   └── data_pipeline.yml
├── user_code/                    # Auto-discovered recursively
│   ├── validators/
│   │   ├── email_validators.py  # Email-specific validators
│   │   ├── phone_validators.py  # Phone-specific validators
│   │   └── format_validators.py # General format validators
│   ├── transformers/
│   │   ├── json_transforms.py   # JSON transformations
│   │   └── csv_transforms.py    # CSV transformations
│   └── enrichers/
│       └── data_enrichers.py    # Data enrichment functions
└── inputs/
    └── contact.json
```

## File 1: Email Validators

**`user_code/validators/email_validators.py`**:
```python
from agent_actions import udf_tool
import re

@udf_tool
def validate_email_format(data, **kwargs):
    """Validate email address has correct format."""
    email = data.get('email', '')
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(email_pattern, email):
        raise ValueError(f"Invalid email format: {email}")

    return data

@udf_tool
def validate_email_domain(data, **kwargs):
    """Validate email domain is from allowed list."""
    email = data.get('email', '')
    allowed_domains = kwargs.get('validator_args', {}).get('allowed_domains', [])

    if not allowed_domains:
        return data  # No restriction if list not provided

    domain = email.split('@')[1] if '@' in email else ''

    if domain not in allowed_domains:
        raise ValueError(
            f"Email domain '{domain}' not allowed. "
            f"Allowed domains: {', '.join(allowed_domains)}"
        )

    return data

@udf_tool
def normalize_email(data, **kwargs):
    """Normalize email to lowercase and trim whitespace."""
    if 'email' in data:
        data['email'] = data['email'].strip().lower()
    return data
```

## File 2: Phone Validators

**`user_code/validators/phone_validators.py`**:
```python
from agent_actions import udf_tool
import re

@udf_tool
def validate_phone_format(data, **kwargs):
    """Validate phone number format (US numbers)."""
    phone = data.get('phone', '')

    # Supports: (123) 456-7890, 123-456-7890, 1234567890
    phone_pattern = r'^(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$'

    if not re.match(phone_pattern, phone):
        raise ValueError(f"Invalid phone format: {phone}")

    return data

@udf_tool
def normalize_phone(data, **kwargs):
    """Normalize phone to standard format: +1-XXX-XXX-XXXX."""
    phone = data.get('phone', '')

    # Extract digits only
    digits = re.sub(r'\D', '', phone)

    # Remove leading 1 if present
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]

    if len(digits) != 10:
        raise ValueError(f"Phone must have 10 digits, got {len(digits)}")

    # Format as +1-XXX-XXX-XXXX
    formatted = f"+1-{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    data['phone'] = formatted

    return data
```

## File 3: Format Validators

**`user_code/validators/format_validators.py`**:
```python
from agent_actions import udf_tool

@udf_tool
def validate_required_fields(data, **kwargs):
    """Validate all required fields are present."""
    required = kwargs.get('validator_args', {}).get('fields', [])
    missing = [field for field in required if field not in data or data[field] is None]

    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    return data

@udf_tool
def validate_non_empty_strings(data, **kwargs):
    """Validate specified fields are non-empty strings."""
    fields = kwargs.get('validator_args', {}).get('fields', [])

    for field in fields:
        value = data.get(field, '')
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Field '{field}' must be a non-empty string")

    return data
```

## File 4: JSON Transformers

**`user_code/transformers/json_transforms.py`**:
```python
from agent_actions import udf_tool
import json

@udf_tool
def parse_json_string(data, **kwargs):
    """Parse JSON string to dict."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")
    return data

@udf_tool
def stringify_json(data, **kwargs):
    """Convert dict to JSON string."""
    indent = kwargs.get('validator_args', {}).get('indent', 2)

    try:
        return json.dumps(data, indent=indent)
    except TypeError as e:
        raise ValueError(f"Cannot serialize to JSON: {str(e)}")
```

## File 5: Data Enrichers

**`user_code/enrichers/data_enrichers.py`**:
```python
from agent_actions import udf_tool
from datetime import datetime

@udf_tool
def add_timestamp(data, **kwargs):
    """Add processing timestamp to data."""
    data['processed_at'] = datetime.now().isoformat()
    return data

@udf_tool
def add_metadata(data, **kwargs):
    """Add metadata about the processing workflow."""
    data['metadata'] = {
        'workflow': 'data_pipeline',
        'version': '1.0.0',
        'environment': kwargs.get('environment', 'development')
    }
    return data

@udf_tool
def enrich_contact_info(data, **kwargs):
    """Enrich contact data with derived fields."""
    # Add email domain
    if 'email' in data and '@' in data['email']:
        data['email_domain'] = data['email'].split('@')[1]

    # Add area code from phone
    if 'phone' in data:
        # Assuming normalized format: +1-XXX-XXX-XXXX
        parts = data['phone'].split('-')
        if len(parts) >= 2:
            data['area_code'] = parts[1]

    return data
```

## Agent Configuration

**`agent_configs/data_pipeline.yml`**:
```yaml
agent: data_pipeline
description: "Multi-stage contact data processing pipeline"

actions:
  # Stage 1: Format validation
  - name: check_required_fields
    impl: validate_required_fields
    type: tool
    validator_args:
      fields: ['name', 'email', 'phone']

  # Stage 2: Email processing
  - name: validate_email
    impl: validate_email_format
    type: tool

  - name: check_email_domain
    impl: validate_email_domain
    type: tool
    validator_args:
      allowed_domains: ['company.com', 'example.org']

  - name: normalize_email_case
    impl: normalize_email
    type: tool

  # Stage 3: Phone processing
  - name: validate_phone
    impl: validate_phone_format
    type: tool

  - name: normalize_phone_format
    impl: normalize_phone
    type: tool

  # Stage 4: Enrichment
  - name: enrich_contact
    impl: enrich_contact_info
    type: tool

  - name: add_processing_time
    impl: add_timestamp
    type: tool

  - name: add_workflow_metadata
    impl: add_metadata
    type: tool
```

## Running the Pipeline

**Input** (`inputs/contact.json`):
```json
{
  "name": "John Doe",
  "email": "JOHN.DOE@company.com  ",
  "phone": "(555) 123-4567"
}
```

**Run the workflow**:
```bash
$ agent-actions run data_pipeline -i inputs/contact.json -u user_code/

🔍 Discovering UDFs...
✅ Discovered 11 UDF(s)

Running workflow: data_pipeline
✅ check_required_fields: PASSED
✅ validate_email: PASSED
✅ check_email_domain: PASSED
✅ normalize_email_case: COMPLETED
✅ validate_phone: PASSED
✅ normalize_phone_format: COMPLETED
✅ enrich_contact: COMPLETED
✅ add_processing_time: COMPLETED
✅ add_workflow_metadata: COMPLETED
```

**Output**:
```json
{
  "name": "John Doe",
  "email": "john.doe@company.com",
  "phone": "+1-555-123-4567",
  "email_domain": "company.com",
  "area_code": "555",
  "processed_at": "2025-01-15T14:30:00.123456",
  "metadata": {
    "workflow": "data_pipeline",
    "version": "1.0.0",
    "environment": "development"
  }
}
```

## Listing All Discovered UDFs

```bash
$ agent-actions list-udfs -u user_code/

Available User-Defined Functions

Function                      Location              File
validate_email_format         email_validators      user_code/validators/email_validators.py
validate_email_domain         email_validators      user_code/validators/email_validators.py
normalize_email               email_validators      user_code/validators/email_validators.py
validate_phone_format         phone_validators      user_code/validators/phone_validators.py
normalize_phone               phone_validators      user_code/validators/phone_validators.py
validate_required_fields      format_validators     user_code/validators/format_validators.py
validate_non_empty_strings    format_validators     user_code/validators/format_validators.py
parse_json_string             json_transforms       user_code/transformers/json_transforms.py
stringify_json                json_transforms       user_code/transformers/json_transforms.py
add_timestamp                 data_enrichers        user_code/enrichers/data_enrichers.py
add_metadata                  data_enrichers        user_code/enrichers/data_enrichers.py
enrich_contact_info           data_enrichers        user_code/enrichers/data_enrichers.py

Total: 12 function(s)
```

## Avoiding Name Collisions

### ❌ Bad: Duplicate Names Across Files

```python
# validators/email_validators.py
@udf_tool
def validate_format(data, **kwargs):  # Generic name
    pass

# validators/phone_validators.py
@udf_tool
def validate_format(data, **kwargs):  # DUPLICATE!
    pass
```

**Error**:
```
❌ Error: Duplicate function name 'validate_format'

First definition:
  Location: email_validators.validate_format
  File: user_code/validators/email_validators.py

Duplicate definition:
  Location: phone_validators.validate_format
  File: user_code/validators/phone_validators.py
```

### ✅ Good: Specific Names

```python
# validators/email_validators.py
@udf_tool
def validate_email_format(data, **kwargs):  # Specific
    pass

# validators/phone_validators.py
@udf_tool
def validate_phone_format(data, **kwargs):  # Specific
    pass
```

## Organizing by Feature

Alternative structure grouping by business domain:

```
user_code/
├── contacts/
│   ├── validators.py    # All contact validators
│   ├── transforms.py    # Contact transformations
│   └── enrichers.py     # Contact enrichment
├── products/
│   ├── validators.py    # Product validators
│   └── transforms.py    # Product transformations
└── orders/
    ├── validators.py    # Order validators
    └── transforms.py    # Order transformations
```

Function naming in this structure:

```python
# contacts/validators.py
@udf_tool
def validate_contact_email(data, **kwargs):
    """Use 'contact' prefix to avoid collision with product emails."""
    pass

# products/validators.py
@udf_tool
def validate_product_sku(data, **kwargs):
    """Use 'product' prefix for clarity."""
    pass
```

## Best Practices

### 1. Use Descriptive Names

```python
# ✅ Good: Clear and specific
@udf_tool
def validate_email_format(data, **kwargs):
    pass

@udf_tool
def normalize_phone_us_format(data, **kwargs):
    pass

# ❌ Bad: Too generic
@udf_tool
def validate(data, **kwargs):
    pass

@udf_tool
def process(data, **kwargs):
    pass
```

### 2. Group Related Functions

```python
# validators/email_validators.py - All email-related functions together
@udf_tool
def validate_email_format(data, **kwargs):
    pass

@udf_tool
def validate_email_domain(data, **kwargs):
    pass

@udf_tool
def normalize_email(data, **kwargs):
    pass
```

### 3. Use Consistent Prefixes

```python
# All validators start with 'validate_'
@udf_tool
def validate_email_format(data, **kwargs):
    pass

# All normalizers start with 'normalize_'
@udf_tool
def normalize_email(data, **kwargs):
    pass

# All enrichers start with 'enrich_' or 'add_'
@udf_tool
def enrich_contact_info(data, **kwargs):
    pass
```

### 4. Document File Purpose

```python
"""
Email validation functions for contact data.

Functions:
  - validate_email_format: Check email syntax
  - validate_email_domain: Check domain whitelist
  - normalize_email: Lowercase and trim
"""
from agent_actions import udf_tool

@udf_tool
def validate_email_format(data, **kwargs):
    pass
```

## Key Takeaways

1. **Auto-discovery is recursive**: All `.py` files in nested directories are discovered
2. **Names must be unique**: Function names are global across all files
3. **Use specific names**: Include context in function names to avoid collisions
4. **Organize by feature or type**: Group related functions together
5. **Files starting with `_` are skipped**: Use for private helpers
6. **Use `list-udfs` to verify**: Check what was discovered

## Next Steps

- **Validation patterns**: See [Validation UDFs](./validation-udfs) for more examples
- **Transformation patterns**: Check [Transformation UDFs](./transformation-udfs)
- **Full guide**: Read the [UDF Decorator Guide](/guides/udf-decorator)
