---
title: Custom Tools
description: Add Python tools to your workflows
sidebar_position: 3
---

# Custom Tools

A tool adds custom code to your workflow. Use tools for validation, transformation, API calls or any other deterministic logic.

:::note
Tools support Python only.
:::

## Quick Start

**`tools/validators.py`**:
```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def validate_product_price(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure product price is positive and reasonable."""
    price = data["source"]["price"]
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")
    return data
```

**Reference in the workflow**:
```yaml
actions:
  - name: price_validator
    kind: tool
    impl: validate_product_price
    intent: Check that the product price is positive
    schema: { source: object }
    context_scope:
      observe:
        - source.*
```

Agent Actions discovers tools automatically. You do not need module paths. A tool action must declare an `intent` and a `schema` for the fields that it returns. This tool returns `data` unchanged. Thus its schema is `{ source: object }`.

## Tool Signature

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_tool(data: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        data: Dict of namespaced fields from upstream actions.
              Each upstream action's output is nested under its
              action name: data["action_name"]["field"].
              Source data is under data["source"]["field"].

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
    email = data["source"]["email"]
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise ValueError(f"Invalid email: {email}")
    return data
```

### Transformation

```python
@udf_tool()
def enrich_customer_data(data: dict[str, Any]) -> dict[str, Any]:
    customer = data["classify_customer"]
    ltv = customer["lifetime_value"]
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
    product_id = data["extract_data"]["product_id"]
    response = requests.get(f"https://api.example.com/products/{product_id}")
    if response.ok:
        data['external_details'] = response.json()
    return data
```

### Aggregation

```python
@udf_tool()
def calculate_order_totals(data: dict[str, Any]) -> dict[str, Any]:
    items = data["source"]["items"]
    subtotal = sum(item['price'] * item['quantity'] for item in items)
    data['subtotal'] = subtotal
    data['tax'] = subtotal * 0.08
    data['total'] = subtotal + data['tax']
    return data
```

## File-Level Tools

Some operations need access to all records at once, for example deduplication, aggregation and cross-record analysis. For these operations, use `Granularity.FILE`. A FILE tool receives a list with one item for each record. Each item holds the fields that the action observes, as flat keys.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def deduplicate_questions(data: list[dict]) -> list[dict]:
    """Dedup by question text — return the items received to preserve lineage."""
    seen = set()
    result = []
    for record in data:
        question = record["question_text"]
        if question not in seen:
            seen.add(question)
            result.append(record)  # pass through the item as received
    return result
```

**Key differences between file-level tools and record-level tools:**

| | Record-level | File-level |
|---|---|---|
| Input | One `dict` with namespaced upstream data | `list[dict]`. Each item holds the observed fields as flat keys |
| Read fields | `data["action_name"]["field"]` | `record["field"]`. A named field is always bare. Only a real collision gives a key `record["action_name.field"]` |
| Passthrough | Return the modified dict | Return the item that you received |
| New records | N/A | Return `FileUDFResult` with `source_index: None` |

:::note[Lineage tracking]
The framework tracks the identity of each item that it gives to the tool. When you return an item that you received, the lineage extends automatically. When you return a `FileUDFResult` output that declares `source_index: None` (aggregation), the framework creates new lineage. You never manage `node_id` directly.
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
