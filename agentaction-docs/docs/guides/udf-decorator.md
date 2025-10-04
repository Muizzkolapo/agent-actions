---
title: UDF Decorator Guide
description: How to create and use User-Defined Functions with the @udf_tool decorator
sidebar_position: 3
---

# UDF Decorator Guide

Learn how to create User-Defined Functions (UDFs) using the `@udf_tool` decorator for automatic function discovery and registration.

## What is @udf_tool?

The `@udf_tool` decorator enables automatic discovery and registration of custom functions in your Agent Actions workflows. Similar to dbt's macro system, you decorate your functions once and reference them by name only — no module paths needed.

**Why use it?**
- **Simple references**: Use `impl: my_function` instead of `impl: module.path.my_function`
- **Refactoring safety**: Move functions between files without breaking configs
- **Namespace validation**: Duplicate names caught at load time (no silent conflicts)
- **Better DX**: Matches the dbt/Jinja mental model

## Basic Usage

### 1. Create a UDF

Create a Python file in your `user_code/` directory:

**`user_code/my_functions.py`**:
```python
from agent_actions import udf_tool

@udf_tool
def validate_email(data, **kwargs):
    """Validate that data contains a valid email address."""
    import re

    email = data.get('email', '')
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if re.match(email_pattern, email):
        return data
    else:
        raise ValueError(f"Invalid email address: {email}")
```

### 2. Reference by Name

Use the function name directly in your workflow config:

**`agent_configs/my_agent.yml`**:
```yaml
actions:
  - name: email_validator
    impl: validate_email  # Just the function name!
    type: tool
```

### 3. Auto-Discovery

When you run your workflow, Agent Actions automatically:
1. Scans your `user_code/` directory
2. Imports all Python files
3. Registers all `@udf_tool` decorated functions
4. Validates your config references

```bash
$ agent-actions run my_agent -i input.json -u user_code/

🔍 Discovering UDFs...
✅ Discovered 1 UDF(s)
```

## How Auto-Discovery Works

### Discovery Process

1. **Directory Scan**: Agent Actions uses `pathlib.rglob('*.py')` to find all Python files in your user code directory
2. **Import Trigger**: Each file is imported using `importlib.import_module()`
3. **Decorator Registration**: When `@udf_tool` executes, it adds the function to the global `UDF_REGISTRY`
4. **Metadata Storage**: Function name, module, file path, docstring, and signature are captured

### What Gets Discovered

✅ **Discovered**:
- All `.py` files in the user code directory
- Files in nested subdirectories
- Functions decorated with `@udf_tool`

❌ **Skipped**:
- Files starting with `_` (e.g., `__init__.py`, `_helpers.py`)
- Non-Python files
- Functions without the decorator

### Discovery Timing

UDFs are discovered once at workflow initialization, before any agents execute. The registry is cached for performance.

## Function Naming Best Practices

### Naming Rules

1. **Unique Names Required**: Function names must be unique across your entire project
2. **Case-Insensitive Matching**: `MyFunction`, `myfunction`, and `MYFUNCTION` are considered duplicates
3. **Valid Python Identifiers**: Use letters, numbers, and underscores only
4. **Descriptive Names**: Use clear, action-oriented names (e.g., `validate_email` not `check`)

### Good Examples

```python
# ✅ Good: Clear, descriptive, unique
@udf_tool
def validate_product_sku(data, **kwargs):
    pass

@udf_tool
def transform_json_to_csv(data, **kwargs):
    pass

@udf_tool
def enrich_customer_data(data, **kwargs):
    pass
```

### Bad Examples

```python
# ❌ Bad: Too generic
@udf_tool
def validate(data, **kwargs):
    pass

# ❌ Bad: Unclear purpose
@udf_tool
def process(data, **kwargs):
    pass

# ❌ Bad: Duplicate names in different files
# File: validators.py
@udf_tool
def check_format(data, **kwargs):
    pass

# File: transforms.py
@udf_tool
def check_format(data, **kwargs):  # ERROR: Duplicate!
    pass
```

## Handling Duplicate Names

### Error Detection

Agent Actions detects duplicate function names at load time and provides both locations:

```
❌ Error: Duplicate function name 'process_data'

First definition:
  Location: validators.process_data
  File: /path/to/user_code/validators.py

Duplicate definition:
  Location: transforms.process_data
  File: /path/to/user_code/transforms.py

Fix:
  Function names must be unique. Rename one of these functions.
```

### Resolution Strategies

1. **Rename for Clarity**: Add context to make names specific
   ```python
   # validators.py
   @udf_tool
   def validate_product_data(data, **kwargs):
       pass

   # transforms.py
   @udf_tool
   def transform_product_data(data, **kwargs):
       pass
   ```

2. **Use Prefixes**: Group related functions with prefixes
   ```python
   @udf_tool
   def email_validate_format(data, **kwargs):
       pass

   @udf_tool
   def email_validate_domain(data, **kwargs):
       pass
   ```

3. **Be Specific**: Replace generic names with specific ones
   ```python
   # Instead of: process_data
   @udf_tool
   def calculate_product_discount(data, **kwargs):
       pass
   ```

## Writing UDFs

### Function Signature

All UDFs must follow this signature:

```python
def my_function(data, **kwargs):
    """
    Args:
        data: The input data from the workflow (dict, str, list, etc.)
        **kwargs: Additional context from the workflow

    Returns:
        Processed data (any JSON-serializable type)
    """
    pass
```

**Parameters**:
- `data`: The primary input, typically from the previous agent or initial input
- `**kwargs`: Optional keyword arguments containing:
  - `validator_args`: Arguments from your config
  - Workflow context data
  - Agent metadata

**Return Value**:
- Must be JSON-serializable (dict, list, str, int, float, bool, None)
- Returned data becomes input for the next agent in the workflow

### Docstring Conventions

Always include a docstring — it appears in `list-udfs` output and helps other developers:

```python
@udf_tool
def validate_product_price(data, **kwargs):
    """
    Validate that product price is positive and within allowed range.

    Checks:
      - Price is a number
      - Price is greater than 0
      - Price is less than max_price (from validator_args)

    Args:
        data: Dict with 'price' field
        **kwargs: Contains 'max_price' in validator_args

    Returns:
        Original data if valid

    Raises:
        ValueError: If validation fails
    """
    price = data.get('price')
    max_price = kwargs.get('validator_args', {}).get('max_price', 10000)

    if not isinstance(price, (int, float)):
        raise ValueError(f"Price must be a number, got {type(price)}")

    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")

    if price > max_price:
        raise ValueError(f"Price {price} exceeds maximum {max_price}")

    return data
```

### Error Handling

**Option 1: Raise Exceptions** (Recommended for validators)

```python
@udf_tool
def validate_required_fields(data, **kwargs):
    """Ensure all required fields are present."""
    required = kwargs.get('validator_args', {}).get('fields', [])

    missing = [field for field in required if field not in data]

    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    return data
```

**Option 2: Return Error Data** (For transformations)

```python
@udf_tool
def safe_json_parse(data, **kwargs):
    """Parse JSON string, return error dict if invalid."""
    import json

    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        return {
            'error': True,
            'message': f"Invalid JSON: {str(e)}",
            'original_data': data
        }
```

### Testing UDFs

Write unit tests for your UDFs just like any Python function:

**`tests/test_my_functions.py`**:
```python
import pytest
from user_code.my_functions import validate_email

def test_validate_email_success():
    """Test valid email passes."""
    data = {'email': 'user@example.com', 'name': 'John'}
    result = validate_email(data)
    assert result == data

def test_validate_email_invalid():
    """Test invalid email raises error."""
    data = {'email': 'not-an-email', 'name': 'John'}

    with pytest.raises(ValueError, match="Invalid email address"):
        validate_email(data)

def test_validate_email_missing():
    """Test missing email field raises error."""
    data = {'name': 'John'}

    with pytest.raises(ValueError):
        validate_email(data)
```

## Advanced Usage

### Organizing UDFs in Multiple Files

You can organize UDFs across multiple files and nested directories:

```
user_code/
├── validators/
│   ├── email_validators.py
│   ├── data_validators.py
│   └── format_validators.py
├── transformers/
│   ├── json_transforms.py
│   └── csv_transforms.py
└── utilities/
    └── helpers.py
```

**All files are automatically discovered** as long as they're in the user code directory.

**Example - `user_code/validators/email_validators.py`**:
```python
from agent_actions import udf_tool

@udf_tool
def validate_email_format(data, **kwargs):
    """Check email format is valid."""
    pass

@udf_tool
def validate_email_domain(data, **kwargs):
    """Check email domain is allowed."""
    pass
```

### Custom User Code Paths

#### Via CLI Flag

Specify a custom path when running workflows:

```bash
agent-actions run my_agent -i input.json -u /path/to/my/functions/
```

#### Via Environment Variable

Set the default user code path:

```bash
export USER_CODE_PATH=/path/to/my/functions
agent-actions run my_agent -i input.json
```

### Debugging UDF Issues

#### List All UDFs

See what's been discovered:

```bash
$ agent-actions list-udfs -u user_code/

Available User-Defined Functions

Function             Location            File
validate_email       my_functions        /path/to/user_code/my_functions.py
                                         Validate email address format
transform_json       transformers        /path/to/user_code/transformers.py
                                         Transform JSON to dict

Total: 2 function(s)
```

**JSON output** for programmatic use:

```bash
$ agent-actions list-udfs -u user_code/ --json
[
  {
    "name": "validate_email",
    "module": "my_functions",
    "file": "/path/to/user_code/my_functions.py",
    "signature": "(data, **kwargs)"
  }
]
```

#### Validate Config References

Check that all `impl` references in your config exist:

```bash
$ agent-actions validate-udfs -a my_agent -u user_code/

🔍 Discovering UDFs...
✅ Discovered 5 UDF(s)

Loading configuration...
Validating UDF references in config...

✅ All UDF references valid
✅ No duplicate function names

Summary:
  - 3 UDF(s) referenced in config
  - 5 UDF(s) discovered and registered
  - All functions found

Referenced UDFs:
  • validate_email (/path/to/user_code/my_functions.py)
  • transform_data (/path/to/user_code/transformers.py)
  • enrich_product (/path/to/user_code/enrichers.py)
```

#### Common Errors

**Function Not Found**:
```
❌ Function 'validate_emai' not found

This function is not registered. Did you forget the @udf_tool decorator?

Available functions (10):
  • validate_email (/path/to/user_code/my_functions.py)
  • validate_phone (/path/to/user_code/my_functions.py)
  ...

Fix:
  1. Check the function name spelling
  2. Ensure the function has @udf_tool decorator
  3. Verify the file is in the user code directory
```

**Import Error**:
```
❌ Error loading UDF module

Module: my_functions
File: /path/to/user_code/my_functions.py
Error: No module named 'missing_dependency'

Fix:
  Check the Python file for syntax errors or import issues.
```

### Performance Considerations

#### Discovery Performance

- **Typical Projects** (10-50 UDFs): <100ms discovery time
- **Large Projects** (100+ UDFs): <500ms discovery time
- **Registry Lookup**: O(1) constant time (dict lookup)

#### Optimization Tips

1. **Registry Caching**: UDFs are discovered once per workflow run
2. **Lazy Import**: Only user code files are imported (not entire Python environment)
3. **Skip Private Files**: Files starting with `_` are skipped automatically

#### Benchmarks

```
Discovery of 50 UDFs across 10 files: 85ms
Discovery of 100 UDFs across 20 files: 160ms
Registry lookup (any size): <1ms
```

## Complete Example

Here's a full example showing multiple UDFs working together:

**`user_code/product_validators.py`**:
```python
from agent_actions import udf_tool
import re

@udf_tool
def validate_product_sku(data, **kwargs):
    """Validate product SKU format (ABC-1234)."""
    sku = data.get('sku', '')
    pattern = r'^[A-Z]{3}-\d{4}$'

    if not re.match(pattern, sku):
        raise ValueError(f"Invalid SKU format: {sku}. Expected: ABC-1234")

    return data

@udf_tool
def validate_product_price(data, **kwargs):
    """Validate product price is positive."""
    price = data.get('price')

    if not isinstance(price, (int, float)) or price <= 0:
        raise ValueError(f"Invalid price: {price}")

    return data

@udf_tool
def enrich_product_category(data, **kwargs):
    """Add category based on SKU prefix."""
    sku = data.get('sku', '')
    prefix = sku[:3]

    category_map = {
        'ELE': 'Electronics',
        'CLO': 'Clothing',
        'FOO': 'Food'
    }

    data['category'] = category_map.get(prefix, 'Unknown')
    return data
```

**`agent_configs/product_processor.yml`**:
```yaml
actions:
  - name: sku_validator
    impl: validate_product_sku
    type: tool

  - name: price_validator
    impl: validate_product_price
    type: tool

  - name: category_enricher
    impl: enrich_product_category
    type: tool
```

**Run the workflow**:
```bash
$ agent-actions run product_processor -i product.json -u user_code/

🔍 Discovering UDFs...
✅ Discovered 3 UDF(s)
Running workflow: product_processor
✅ sku_validator: PASSED
✅ price_validator: PASSED
✅ category_enricher: COMPLETED
```

## Summary

- Use `@udf_tool` decorator to register functions automatically
- Reference functions by name only in configs (`impl: function_name`)
- Organize UDFs across multiple files and directories
- Function names must be unique (case-insensitive)
- Use `list-udfs` to see what's discovered
- Use `validate-udfs` to check config before running
- Write tests for your UDFs just like any Python function

**Next Steps**:
- See [UDF Examples](/examples/udfs/) for real-world patterns
- Check [CLI Reference](/cli-reference) for command details
- Read [Custom Validators](/examples/custom-validators) for validation patterns
