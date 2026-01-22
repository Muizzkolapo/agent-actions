---
title: Custom Functions (UDFs)
description: Extend agentic workflows with Python user-defined functions
sidebar_position: 3
---

# Custom Functions (UDFs)

**What if you need logic that an LLM cannot handle?** User-Defined Functions (UDFs) let you extend Agent Actions with custom Python code. Use them for data validation, transformation, API calls, or any business logic that requires deterministic execution.

Think of UDFs as specialized stations in your assembly line—they do precise, repeatable work that complements the creative capabilities of LLM actions.

## Quick Example

**Create a UDF** (`user_code/validators.py`):
```python
from agent_actions import udf_tool

@udf_tool
def validate_product_price(data, **kwargs):
    """Ensure product price is positive and reasonable."""
    price = data.get('price', 0)

    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")

    if price > 100000:
        raise ValueError(f"Price {price} seems unreasonably high")

    return data
```

**Reference in your agentic workflow**:
```yaml
actions:
  - name: price_validator
    kind: tool
    impl: validate_product_price  # Just the function name
```

**Run with UDF discovery**:
```bash
agac run -a my_workflow

Discovering UDFs...
Discovered 1 UDF(s)
```

Notice that you reference the function by name alone—no module paths needed. Agent Actions discovers your UDFs automatically.

## Why Use UDFs?

You might wonder: why not just write Python scripts? UDFs integrate directly into the agentic workflow—they receive structured input, participate in the dependency graph, and their errors are handled consistently.

| Benefit | Description |
|---------|-------------|
| **Simple references** | Use `impl: function_name` instead of module paths |
| **Auto-discovery** | Functions are found automatically from your code directory |
| **Validation** | Duplicate names caught at load time |
| **Refactoring safe** | Move functions between files without breaking configs |

One limitation: UDFs must be synchronous. If you need async operations, wrap them with appropriate blocking calls.

## Common UDF Patterns

Let's explore the most common ways to use UDFs in your agentic workflows.

### Validation

Validation UDFs act as quality checkpoints. If data fails validation, raising `ValueError` stops the action and triggers appropriate error handling:

```python
@udf_tool
def validate_email(data, **kwargs):
    """Check email format is valid."""
    import re
    email = data.get('email', '')
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(pattern, email):
        raise ValueError(f"Invalid email: {email}")

    return data
```

### Transformation

Transformation UDFs add computed fields or restructure data. This is often faster and more reliable than asking an LLM to perform calculations:

```python
@udf_tool
def enrich_customer_data(data, **kwargs):
    """Add computed fields to customer data."""
    # Add customer tier based on lifetime value
    ltv = data.get('lifetime_value', 0)

    if ltv > 10000:
        data['tier'] = 'platinum'
    elif ltv > 5000:
        data['tier'] = 'gold'
    else:
        data['tier'] = 'silver'

    return data
```

### External API Calls

Need to fetch data from external services? UDFs can make HTTP requests and integrate the results into your agentic workflow:

```python
@udf_tool
def fetch_product_details(data, **kwargs):
    """Fetch additional product info from external API."""
    import requests

    product_id = data.get('product_id')
    response = requests.get(f"https://api.example.com/products/{product_id}")

    if response.ok:
        data['external_details'] = response.json()

    return data
```

Consider adding error handling for network failures in production UDFs.

### Data Aggregation

Aggregation UDFs perform calculations that require precision—financial computations, statistical analysis, or any math where LLM approximations would not suffice:

```python
@udf_tool
def calculate_order_totals(data, **kwargs):
    """Calculate order totals from line items."""
    items = data.get('items', [])

    subtotal = sum(item['price'] * item['quantity'] for item in items)
    tax = subtotal * 0.08
    total = subtotal + tax

    data['subtotal'] = subtotal
    data['tax'] = tax
    data['total'] = total

    return data
```

## UDF Function Signature

All UDFs follow the same signature. The `data` parameter contains input from upstream actions, and `**kwargs` provides execution context:

```python
@udf_tool
def my_function(data, **kwargs):
    """
    Args:
        data: The input data (dict) from the previous action
        **kwargs: Additional context (action_name, workflow_name, etc.)

    Returns:
        Modified data dict to pass to next action

    Raises:
        ValueError: To trigger validation failure and potential reprompt
    """
    # Your logic here
    return data
```

The return value becomes the action's output. Downstream actions can reference fields from this output using standard field reference syntax.

## Discovery and Validation

Agent Actions provides commands to inspect and validate your UDFs before running an agentic workflow.

### List Available UDFs

```bash
agac udfs list
```

This shows all discovered UDFs and their source files—useful for debugging when a function is not found.

### Validate UDFs

```bash
agac udfs validate
```

Validation catches common issues like duplicate function names or missing decorators.

## Learn More

- **[UDF Decorator Specification](../reference/tools/udf-decorator)** - Complete guide with examples
- **[UDF Commands](../cli-reference/udfs)** - `list-udfs` and `validate-udfs` commands
- **[Output Validation](../reference/validation/output-validation)** - How UDFs integrate with the validation pipeline
