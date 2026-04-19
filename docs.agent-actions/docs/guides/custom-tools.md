---
title: Custom Tools
description: Extend agentic workflows with Python tools
sidebar_position: 3
---

# Custom Tools

Add custom code to your workflows for validation, transformation, API calls, or any deterministic logic.

:::note
Tools currently support Python only. Support for Docker containers and other runtimes is planned.
:::

## Quick Start

**`tools/validators.py`**:
```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def validate_product_price(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure product price is positive and reasonable."""
    price = data.get('price', 0)
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")
    return data
```

**Reference in workflow**:
```yaml
actions:
  - name: price_validator
    kind: tool
    impl: validate_product_price
```

Agent Actions discovers tools automatically—no module paths needed.

## Tool Signature

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_tool(data: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        data: Input dict from upstream action (defined by context_scope)

    Returns:
        Modified data dict

    Raises:
        ValueError: Triggers validation failure
    """
    return data
```

## Examples

### Validation

```python
@udf_tool()
def validate_email(data: dict[str, Any]) -> dict[str, Any]:
    import re
    email = data.get('email', '')
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise ValueError(f"Invalid email: {email}")
    return data
```

### Transformation

```python
@udf_tool()
def enrich_customer_data(data: dict[str, Any]) -> dict[str, Any]:
    ltv = data.get('lifetime_value', 0)
    if ltv > 10000:
        data['tier'] = 'platinum'
    elif ltv > 5000:
        data['tier'] = 'gold'
    else:
        data['tier'] = 'silver'
    return data
```

### External API

```python
@udf_tool()
def fetch_product_details(data: dict[str, Any]) -> dict[str, Any]:
    import requests
    product_id = data.get('product_id')
    response = requests.get(f"https://api.example.com/products/{product_id}")
    if response.ok:
        data['external_details'] = response.json()
    return data
```

### Aggregation

```python
@udf_tool()
def calculate_order_totals(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get('items', [])
    subtotal = sum(item['price'] * item['quantity'] for item in items)
    data['subtotal'] = subtotal
    data['tax'] = subtotal * 0.08
    data['total'] = subtotal + data['tax']
    return data
```

## File-Level Tools

For operations that need access to all records at once (deduplication, aggregation, cross-record analysis), use `Granularity.FILE`. FILE tools receive **full records** with framework metadata.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def deduplicate_questions(data: list[dict]) -> list[dict]:
    """Dedup by question text — return full records to preserve lineage."""
    seen = set()
    result = []
    for record in data:
        content = record.get("content", record)
        question = content.get("question_text", "")
        if question not in seen:
            seen.add(question)
            result.append(record)  # pass through the full record
    return result
```

**Key differences from record-level tools:**

| | Record-level | File-level |
|---|---|---|
| Input | Single `dict` with unwrapped business fields | `list[dict]` — each record has `content`, `node_id`, `lineage` |
| Read fields | `data["field"]` | `record["content"]["field"]` |
| Passthrough | Return modified dict | Return the original record dict |
| New records | N/A | Return a new dict without `node_id` |

:::tip Lineage tracking
Each record carries a `node_id` that the framework uses to track lineage. When you return the original record, lineage extends automatically. When you return a new dict (aggregation), the framework creates fresh lineage. You never manage `node_id` directly.
:::

## CLI Commands

```bash
# List discovered tools
agac list-udfs -u tools/

# Validate tool references in workflow
agac validate-udfs -a my_workflow -u tools/
```

## Learn More

- **[Tool Actions Reference](../reference/tools/index.md)**
- **[Tool CLI Commands](../reference/cli/tools)**
