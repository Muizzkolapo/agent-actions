---
title: Basic UDF Example
description: Your first User-Defined Function with @udf_tool
sidebar_position: 1
---

# Basic UDF Example

This example shows how to create a simple UDF for data validation using the `@udf_tool` decorator.

## Scenario

You need to validate that incoming product data has all required fields and correct types before processing.

## Directory Structure

```
my_project/
├── agent_actions.yml
├── agent_configs/
│   └── product_validator.yml
├── user_code/
│   └── validators.py          # Our UDF file
└── inputs/
    └── product.json
```

## Step 1: Create the UDF

**`user_code/validators.py`**:
```python
from agent_actions import udf_tool

@udf_tool
def validate_product(data, **kwargs):
    """
    Validate product data has required fields and correct types.

    Required fields:
      - product_name (str)
      - price (number, > 0)
      - sku (str, format: ABC-1234)

    Args:
        data: Product data dict
        **kwargs: Workflow context (unused)

    Returns:
        Original data if valid

    Raises:
        ValueError: If validation fails
    """
    import re

    # Check required fields
    required_fields = ['product_name', 'price', 'sku']
    missing = [field for field in required_fields if field not in data]

    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    # Validate product_name
    if not isinstance(data['product_name'], str) or not data['product_name'].strip():
        raise ValueError("product_name must be a non-empty string")

    # Validate price
    price = data['price']
    if not isinstance(price, (int, float)):
        raise ValueError(f"price must be a number, got {type(price).__name__}")

    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    # Validate SKU format
    sku = data['sku']
    sku_pattern = r'^[A-Z]{3}-\d{4}$'

    if not re.match(sku_pattern, sku):
        raise ValueError(
            f"Invalid SKU format: '{sku}'. Expected format: ABC-1234 "
            "(3 uppercase letters, hyphen, 4 digits)"
        )

    return data
```

## Step 2: Create the Agent Config

**`agent_configs/product_validator.yml`**:
```yaml
# Simple agent that validates product data
agent: product_validator
description: "Validate incoming product data"

# Use our UDF by name only
actions:
  - name: validate_product_data
    impl: validate_product  # <- Just the function name!
    type: tool
    description: "Validate product has required fields and formats"

# Optional: Add context for better errors
context:
  purpose: "Data validation for product catalog"
  stage: "input_validation"
```

## Step 3: Create Input Data

**`inputs/product.json`**:
```json
{
  "product_name": "Wireless Mouse",
  "price": 29.99,
  "sku": "ELE-1234",
  "description": "Ergonomic wireless mouse with USB receiver",
  "in_stock": true
}
```

## Step 4: Run the Workflow

```bash
$ agent-actions run product_validator \
    -i inputs/product.json \
    -u user_code/

🔍 Discovering UDFs...
✅ Discovered 1 UDF(s)

Running workflow: product_validator
✅ validate_product_data: PASSED

Output:
{
  "product_name": "Wireless Mouse",
  "price": 29.99,
  "sku": "ELE-1234",
  "description": "Ergonomic wireless mouse with USB receiver",
  "in_stock": true
}
```

## Testing the Validator

### Test 1: Valid Input

```json
{
  "product_name": "Keyboard",
  "price": 59.99,
  "sku": "ELE-5678"
}
```

**Result**: ✅ PASSED

### Test 2: Missing Field

```json
{
  "product_name": "Monitor",
  "price": 299.99
}
```

**Result**: ❌ ERROR
```
ValueError: Missing required fields: sku
```

### Test 3: Invalid Price

```json
{
  "product_name": "Headphones",
  "price": -10,
  "sku": "ELE-9999"
}
```

**Result**: ❌ ERROR
```
ValueError: price must be positive, got -10
```

### Test 4: Invalid SKU Format

```json
{
  "product_name": "Webcam",
  "price": 79.99,
  "sku": "invalid"
}
```

**Result**: ❌ ERROR
```
ValueError: Invalid SKU format: 'invalid'. Expected format: ABC-1234
```

## Listing Your UDFs

See what was discovered:

```bash
$ agent-actions list-udfs -u user_code/

Available User-Defined Functions

Function           Location      File
validate_product   validators    /path/to/user_code/validators.py
                                 Validate product data has required fields

Total: 1 function(s)
```

## Validating Config References

Check that your config references the correct function:

```bash
$ agent-actions validate-udfs -a product_validator -u user_code/

🔍 Discovering UDFs...
✅ Discovered 1 UDF(s)

Loading configuration...
Validating UDF references in config...

✅ All UDF references valid
✅ No duplicate function names

Summary:
  - 1 UDF(s) referenced in config
  - 1 UDF(s) discovered and registered
  - All functions found

Referenced UDFs:
  • validate_product (/path/to/user_code/validators.py)
```

## Writing Unit Tests

Create tests for your UDF:

**`tests/test_validators.py`**:
```python
import pytest
from user_code.validators import validate_product

def test_validate_product_success():
    """Test valid product data passes."""
    data = {
        'product_name': 'Test Product',
        'price': 99.99,
        'sku': 'TST-1234'
    }
    result = validate_product(data)
    assert result == data

def test_validate_product_missing_field():
    """Test missing field raises error."""
    data = {
        'product_name': 'Test Product',
        'price': 99.99
    }
    with pytest.raises(ValueError, match="Missing required fields: sku"):
        validate_product(data)

def test_validate_product_invalid_price():
    """Test negative price raises error."""
    data = {
        'product_name': 'Test Product',
        'price': -10,
        'sku': 'TST-1234'
    }
    with pytest.raises(ValueError, match="price must be positive"):
        validate_product(data)

def test_validate_product_invalid_sku():
    """Test invalid SKU format raises error."""
    data = {
        'product_name': 'Test Product',
        'price': 99.99,
        'sku': 'invalid'
    }
    with pytest.raises(ValueError, match="Invalid SKU format"):
        validate_product(data)

def test_validate_product_empty_name():
    """Test empty product name raises error."""
    data = {
        'product_name': '',
        'price': 99.99,
        'sku': 'TST-1234'
    }
    with pytest.raises(ValueError, match="product_name must be a non-empty string"):
        validate_product(data)
```

Run your tests:

```bash
$ pytest tests/test_validators.py -v

tests/test_validators.py::test_validate_product_success PASSED
tests/test_validators.py::test_validate_product_missing_field PASSED
tests/test_validators.py::test_validate_product_invalid_price PASSED
tests/test_validators.py::test_validate_product_invalid_sku PASSED
tests/test_validators.py::test_validate_product_empty_name PASSED

5 passed in 0.02s
```

## Key Takeaways

1. **Import the decorator**: `from agent_actions import udf_tool`
2. **Decorate your function**: `@udf_tool` above the function definition
3. **Follow the signature**: `def func(data, **kwargs)`
4. **Add docstrings**: Help other developers understand your function
5. **Reference by name**: Use `impl: function_name` in your config
6. **Test your UDFs**: Write unit tests just like any Python function

## Next Steps

- **Multiple files**: Learn to organize UDFs across files in [Multiple Files](./multiple-files)
- **More patterns**: See advanced validation in [Validation UDFs](./validation-udfs)
- **Transformations**: Check out [Transformation UDFs](./transformation-udfs)
- **Full guide**: Read the complete [UDF Decorator Guide](/guides/udf-decorator)
