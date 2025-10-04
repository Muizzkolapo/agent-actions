---
title: Transformation UDF Examples
description: Data transformation patterns with @udf_tool
sidebar_position: 4
---

# Transformation UDF Examples

Collection of common data transformation patterns using the `@udf_tool` decorator for converting, enriching, and processing data.

## Overview

Transformation UDFs modify data by:
- **Converting formats** (JSON ↔ CSV, case changes, etc.)
- **Enriching data** (adding computed fields, metadata)
- **Filtering/selecting** (extracting subsets)
- **Aggregating** (combining, grouping, summarizing)

Unlike validators, transformers always return modified data (no exceptions on success).

## Pattern 1: Format Conversion

### JSON to CSV

```python
from agent_actions import udf_tool
import csv
import json
from io import StringIO

@udf_tool
def convert_json_to_csv(data, **kwargs):
    """
    Convert list of dicts to CSV string.

    Input: [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]
    Output: "name,age\nJohn,30\nJane,25\n"
    """
    if not isinstance(data, list):
        raise ValueError("Input must be a list of dicts")

    if not data:
        return ""  # Empty list returns empty CSV

    # Get all unique keys from all dicts
    fieldnames = set()
    for item in data:
        if isinstance(item, dict):
            fieldnames.update(item.keys())

    fieldnames = sorted(fieldnames)  # Consistent order

    # Write to CSV string
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)

    return output.getvalue()
```

### CSV to JSON

```python
@udf_tool
def convert_csv_to_json(data, **kwargs):
    """
    Convert CSV string to list of dicts.

    Input: "name,age\nJohn,30\nJane,25"
    Output: [{"name": "John", "age": "30"}, {"name": "Jane", "age": "25"}]
    """
    if not isinstance(data, str):
        raise ValueError("Input must be a CSV string")

    input_io = StringIO(data)
    reader = csv.DictReader(input_io)

    result = list(reader)
    return result
```

### String Case Conversion

```python
@udf_tool
def convert_keys_to_snake_case(data, **kwargs):
    """
    Convert all dict keys from camelCase to snake_case.

    Input: {"firstName": "John", "lastName": "Doe"}
    Output: {"first_name": "John", "last_name": "Doe"}
    """
    import re

    def camel_to_snake(name):
        # Insert underscore before uppercase letters and convert to lowercase
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    if not isinstance(data, dict):
        return data

    converted = {}
    for key, value in data.items():
        new_key = camel_to_snake(key)

        # Recursively convert nested dicts
        if isinstance(value, dict):
            converted[new_key] = convert_keys_to_snake_case(value, **kwargs)
        elif isinstance(value, list):
            converted[new_key] = [
                convert_keys_to_snake_case(item, **kwargs)
                if isinstance(item, dict) else item
                for item in value
            ]
        else:
            converted[new_key] = value

    return converted
```

## Pattern 2: Data Enrichment

### Add Timestamps

```python
@udf_tool
def add_processing_timestamps(data, **kwargs):
    """
    Add processing timestamp metadata.

    Adds:
      - processed_at: Current ISO timestamp
      - processing_id: Unique processing ID
    """
    from datetime import datetime
    import uuid

    data['processed_at'] = datetime.now().isoformat()
    data['processing_id'] = str(uuid.uuid4())

    return data
```

### Compute Derived Fields

```python
@udf_tool
def compute_order_totals(data, **kwargs):
    """
    Compute order totals from line items.

    Adds:
      - subtotal: Sum of all items
      - tax: Subtotal * tax_rate
      - total: Subtotal + tax + shipping
    """
    items = data.get('items', [])

    # Calculate subtotal
    subtotal = sum(
        item.get('price', 0) * item.get('quantity', 1)
        for item in items
    )

    # Get or calculate tax
    tax_rate = data.get('tax_rate', 0.0)
    tax = subtotal * tax_rate

    # Get shipping
    shipping = data.get('shipping_cost', 0.0)

    # Add computed fields
    data['subtotal'] = round(subtotal, 2)
    data['tax'] = round(tax, 2)
    data['total'] = round(subtotal + tax + shipping, 2)

    return data
```

### Enrich with External Data

```python
@udf_tool
def enrich_with_geo_data(data, **kwargs):
    """
    Enrich address data with geocoding information.

    Note: In real use, you'd call a geocoding API.
    This example shows the pattern.
    """
    zip_code = data.get('zip_code')

    # Mock geocoding lookup (in reality, call external API)
    geo_database = {
        '10001': {'city': 'New York', 'state': 'NY', 'timezone': 'America/New_York'},
        '90210': {'city': 'Beverly Hills', 'state': 'CA', 'timezone': 'America/Los_Angeles'},
    }

    geo_data = geo_database.get(zip_code, {})

    # Enrich data
    data['geo'] = {
        'city': geo_data.get('city', 'Unknown'),
        'state': geo_data.get('state', 'Unknown'),
        'timezone': geo_data.get('timezone', 'UTC'),
        'enriched': bool(geo_data)
    }

    return data
```

## Pattern 3: Data Filtering & Selection

### Extract Specific Fields

```python
@udf_tool
def extract_fields(data, **kwargs):
    """
    Extract only specified fields from data.

    Config usage:
      validator_args:
        fields: ['id', 'name', 'email']
    """
    fields_to_keep = kwargs.get('validator_args', {}).get('fields', [])

    if not fields_to_keep:
        return data  # No filtering if no fields specified

    filtered = {
        key: value
        for key, value in data.items()
        if key in fields_to_keep
    }

    return filtered
```

### Filter List Items

```python
@udf_tool
def filter_items_by_condition(data, **kwargs):
    """
    Filter list items based on field condition.

    Config usage:
      validator_args:
        list_field: 'items'
        condition_field: 'status'
        condition_value: 'active'
    """
    args = kwargs.get('validator_args', {})
    list_field = args.get('list_field', 'items')
    condition_field = args.get('condition_field')
    condition_value = args.get('condition_value')

    if list_field not in data:
        return data

    items = data[list_field]
    if not isinstance(items, list):
        return data

    # Filter items
    filtered_items = [
        item for item in items
        if isinstance(item, dict) and
           item.get(condition_field) == condition_value
    ]

    data[list_field] = filtered_items
    return data
```

### Remove Null Values

```python
@udf_tool
def remove_null_fields(data, **kwargs):
    """
    Remove all fields with null/None values.

    Input: {"name": "John", "age": null, "email": "john@test.com"}
    Output: {"name": "John", "email": "john@test.com"}
    """
    if not isinstance(data, dict):
        return data

    cleaned = {
        key: value
        for key, value in data.items()
        if value is not None
    }

    return cleaned
```

## Pattern 4: Data Aggregation

### Group By Field

```python
@udf_tool
def group_items_by_field(data, **kwargs):
    """
    Group list items by a field value.

    Input: {"items": [{"cat": "A", "val": 1}, {"cat": "B", "val": 2}, {"cat": "A", "val": 3}]}
    Output: {"A": [{"cat": "A", "val": 1}, {"cat": "A", "val": 3}], "B": [{"cat": "B", "val": 2}]}

    Config usage:
      validator_args:
        list_field: 'items'
        group_by: 'category'
    """
    args = kwargs.get('validator_args', {})
    list_field = args.get('list_field', 'items')
    group_by = args.get('group_by')

    if not group_by:
        raise ValueError("validator_args must specify 'group_by' field")

    items = data.get(list_field, [])
    if not isinstance(items, list):
        return data

    # Group items
    grouped = {}
    for item in items:
        if not isinstance(item, dict):
            continue

        group_key = item.get(group_by, 'unknown')
        if group_key not in grouped:
            grouped[group_key] = []

        grouped[group_key].append(item)

    return grouped
```

### Calculate Statistics

```python
@udf_tool
def calculate_item_statistics(data, **kwargs):
    """
    Calculate statistics for numeric fields in a list.

    Computes: count, sum, average, min, max
    """
    args = kwargs.get('validator_args', {})
    list_field = args.get('list_field', 'items')
    numeric_field = args.get('numeric_field', 'value')

    items = data.get(list_field, [])

    # Extract numeric values
    values = [
        item.get(numeric_field, 0)
        for item in items
        if isinstance(item, dict) and
           isinstance(item.get(numeric_field), (int, float))
    ]

    if not values:
        stats = {'count': 0, 'sum': 0, 'average': 0, 'min': 0, 'max': 0}
    else:
        stats = {
            'count': len(values),
            'sum': round(sum(values), 2),
            'average': round(sum(values) / len(values), 2),
            'min': min(values),
            'max': max(values)
        }

    # Add stats to data
    data['statistics'] = stats

    return data
```

## Pattern 5: Data Normalization

### Normalize Phone Numbers

```python
@udf_tool
def normalize_phone_numbers(data, **kwargs):
    """
    Normalize phone number to standard format: +1-XXX-XXX-XXXX.

    Input: Various formats like (555) 123-4567, 555.123.4567, etc.
    Output: +1-555-123-4567
    """
    import re

    phone_field = kwargs.get('validator_args', {}).get('field', 'phone')

    if phone_field not in data:
        return data

    phone = data[phone_field]

    # Extract digits only
    digits = re.sub(r'\D', '', phone)

    # Remove leading 1 if present
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]

    if len(digits) != 10:
        # Can't normalize, keep original
        return data

    # Format as +1-XXX-XXX-XXXX
    normalized = f"+1-{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    data[phone_field] = normalized

    return data
```

### Normalize Text Fields

```python
@udf_tool
def normalize_text_fields(data, **kwargs):
    """
    Normalize text fields: trim whitespace, fix case, remove special chars.

    Config usage:
      validator_args:
        fields: ['name', 'company']
        case: 'title'  # Options: 'upper', 'lower', 'title'
    """
    args = kwargs.get('validator_args', {})
    fields = args.get('fields', [])
    case_format = args.get('case', 'title')

    for field in fields:
        if field not in data or not isinstance(data[field], str):
            continue

        value = data[field]

        # Trim whitespace
        value = value.strip()

        # Remove extra internal whitespace
        value = ' '.join(value.split())

        # Apply case formatting
        if case_format == 'upper':
            value = value.upper()
        elif case_format == 'lower':
            value = value.lower()
        elif case_format == 'title':
            value = value.title()

        data[field] = value

    return data
```

## Pattern 6: Complex Transformations

### Flatten Nested Structure

```python
@udf_tool
def flatten_nested_dict(data, **kwargs):
    """
    Flatten nested dict structure using dot notation.

    Input: {"user": {"name": "John", "address": {"city": "NYC"}}}
    Output: {"user.name": "John", "user.address.city": "NYC"}
    """
    def _flatten(obj, parent_key=''):
        items = []

        if isinstance(obj, dict):
            for key, value in obj.items():
                new_key = f"{parent_key}.{key}" if parent_key else key

                if isinstance(value, dict):
                    items.extend(_flatten(value, new_key).items())
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        list_key = f"{new_key}[{i}]"
                        if isinstance(item, dict):
                            items.extend(_flatten(item, list_key).items())
                        else:
                            items.append((list_key, item))
                else:
                    items.append((new_key, value))
        else:
            items.append((parent_key, obj))

        return dict(items)

    return _flatten(data)
```

### Merge Data Sources

```python
@udf_tool
def merge_with_reference_data(data, **kwargs):
    """
    Merge incoming data with reference data based on key.

    Config usage:
      validator_args:
        merge_key: 'product_id'
        reference_data: {...}
    """
    args = kwargs.get('validator_args', {})
    merge_key = args.get('merge_key')
    reference_data = args.get('reference_data', {})

    if not merge_key or merge_key not in data:
        return data

    key_value = data[merge_key]
    ref_item = reference_data.get(key_value, {})

    # Merge reference data into main data
    # (main data takes precedence on conflicts)
    merged = {**ref_item, **data}

    return merged
```

## Complete Transformation Pipeline Example

**`user_code/transformers/data_transforms.py`**:
```python
from agent_actions import udf_tool

@udf_tool
def normalize_input_data(data, **kwargs):
    """Stage 1: Clean and normalize input."""
    # Trim whitespace from all string fields
    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip()

    return data

@udf_tool
def enrich_customer_data(data, **kwargs):
    """Stage 2: Add computed and enriched fields."""
    # Add customer tier based on lifetime value
    ltv = data.get('lifetime_value', 0)

    if ltv > 10000:
        data['tier'] = 'platinum'
    elif ltv > 5000:
        data['tier'] = 'gold'
    elif ltv > 1000:
        data['tier'] = 'silver'
    else:
        data['tier'] = 'bronze'

    return data

@udf_tool
def format_output_data(data, **kwargs):
    """Stage 3: Format for output system."""
    # Remove internal fields
    internal_fields = ['internal_id', 'debug_info']
    for field in internal_fields:
        data.pop(field, None)

    # Add output metadata
    data['_metadata'] = {
        'format_version': '2.0',
        'transformed': True
    }

    return data
```

**`agent_configs/data_transformer.yml`**:
```yaml
agent: data_transformer
description: "Multi-stage data transformation pipeline"

actions:
  - name: normalize
    impl: normalize_input_data
    type: tool

  - name: enrich
    impl: enrich_customer_data
    type: tool

  - name: format_output
    impl: format_output_data
    type: tool
```

## Testing Transformers

```python
import pytest
from user_code.transformers.data_transforms import convert_keys_to_snake_case

def test_camel_to_snake_simple():
    data = {'firstName': 'John', 'lastName': 'Doe'}
    result = convert_keys_to_snake_case(data)

    assert result == {'first_name': 'John', 'last_name': 'Doe'}

def test_camel_to_snake_nested():
    data = {
        'userName': 'john',
        'userDetails': {
            'firstName': 'John',
            'homeAddress': {'streetName': 'Main St'}
        }
    }

    result = convert_keys_to_snake_case(data)

    assert result == {
        'user_name': 'john',
        'user_details': {
            'first_name': 'John',
            'home_address': {'street_name': 'Main St'}
        }
    }
```

## Key Takeaways

1. **Return transformed data** - Always return the modified data structure
2. **Preserve type contracts** - If input is dict, output should be dict
3. **Use validator_args** for configurable transformations
4. **Handle edge cases** - Check types, handle missing fields gracefully
5. **Document transformations** - Explain input/output format in docstrings
6. **Test with real data** - Use realistic test cases

## Next Steps

- **Validation**: See [Validation UDFs](./validation-udfs) for data validation patterns
- **Organization**: Learn [Multiple Files](./multiple-files) for larger projects
- **Full guide**: Read the [UDF Decorator Guide](/guides/udf-decorator)
