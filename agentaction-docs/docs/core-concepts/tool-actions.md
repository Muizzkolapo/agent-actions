# Tool Actions

Tool actions execute Python functions instead of calling LLM APIs. They allow you to integrate custom logic, external APIs, data transformations, and validations into your workflows.

## When to Use Tool Actions

Use `kind: tool` when you need to:

- **Execute custom Python logic** - Run your own functions as part of the workflow
- **Call external APIs** - Integrate with third-party services without LLM mediation
- **Perform data transformations** - Clean, reshape, or enrich data
- **Validate or enrich data** - Apply business rules or validation logic
- **Bridge systems** - Connect different data sources or services

## Required Configuration

Tool actions have a simpler configuration than LLM actions:

```yaml
actions:
  - name: my_tool
    kind: tool                    # REQUIRED: Identifies this as a tool action
    impl: module.function         # REQUIRED: Python function path
    reads: [input_fields]         # Fields this tool reads
    writes: [output_fields]       # Fields this tool produces
```

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| `kind` | Must be `"tool"` | `kind: tool` |
| `impl` | Python function path (module.function) | `impl: my_tools.validators.check_schema` |
| `reads` | List of input fields | `reads: [raw_data, metadata]` |
| `writes` | List of output fields | `writes: [validated_data, errors]` |

## Automatic Behavior

Tool actions automatically receive special handling:

### 1. **Vendor and Model Auto-Set**
- `model_vendor` is automatically set to `'tool'`
- `model_name` is automatically set to your `impl` value

You don't need to specify these fields.

### 2. **Online Mode Only**
Tool actions execute locally and synchronously, so they:
- Always run in `online` mode (never `batch`)
- If you inherit `run_mode: batch` from defaults, it's silently overridden to `online`
- If you explicitly set `run_mode: batch` on a tool action, you'll get an error

### 3. **No API Key Required**
Tool actions don't call LLM APIs, so they don't need an `api_key` field.

## What Tool Actions DON'T Need

Tool actions ignore these fields:

- ❌ `model_vendor` - Auto-set to `'tool'`
- ❌ `model_name` - Auto-set to your `impl` value
- ❌ `api_key` - Not needed for local Python functions
- ❌ `prompt` - Tools don't use prompts

## Limitations

### Cannot Use Batch Mode

Tool actions execute locally and must run immediately. They cannot be queued for batch processing.

**If you inherit batch mode from defaults:**
```yaml
defaults:
  run_mode: batch    # All actions get this

actions:
  - name: my_tool
    kind: tool
    impl: my_tools.process
    # Automatically overridden to online mode
```

**If you explicitly set batch mode:**
```yaml
actions:
  - name: my_tool
    kind: tool
    impl: my_tools.process
    run_mode: batch    # ERROR! Tool actions don't support batch
```

You'll get:
```
ConfigurationError: Tool actions do not support batch processing.
Please set run_mode='online' or remove the run_mode setting.
```

## Implementation Function Signature

Your tool function should accept these parameters:

```python
from typing import Dict, Any

def my_tool_function(
    item_data: Dict[str, Any],     # Current item being processed
    context: Dict[str, Any],        # Full workflow context
    config: Dict[str, Any]          # Tool configuration
) -> Dict[str, Any]:
    """
    Process data and return results.

    Args:
        item_data: The current record/item being processed
        context: Full workflow context including previous action outputs
        config: Tool-specific configuration from workflow file

    Returns:
        Dictionary with fields matching the 'writes' declaration
    """
    # Your logic here
    result = {
        'output_field': 'value',
        # ... other fields declared in 'writes'
    }
    return result
```

## Example: Data Validation Tool

```yaml
# workflow.yml
defaults:
  model_vendor: openai
  model_name: gpt-4
  api_key: ${OPENAI_API_KEY}

actions:
  # Tool action: Validate data schema
  - name: validate_schema
    kind: tool
    impl: my_tools.validators.check_schema
    reads: [raw_data]
    writes: [is_valid, errors]

  # LLM action: Enrich valid data
  - name: enrich_data
    kind: llm  # Uses defaults above
    reads: [raw_data, is_valid]
    writes: [enriched_data]
    prompt: |
      {% if is_valid %}
      Enrich this data: {{ raw_data }}
      {% else %}
      This data is invalid, skip enrichment.
      {% endif %}
```

```python
# my_tools/validators.py
from typing import Dict, Any
import jsonschema

def check_schema(item_data: Dict[str, Any], context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate data against JSON schema."""
    raw_data = item_data.get('raw_data', {})

    # Define your schema
    schema = {
        "type": "object",
        "required": ["name", "email"],
        "properties": {
            "name": {"type": "string"},
            "email": {"type": "string", "format": "email"}
        }
    }

    try:
        jsonschema.validate(raw_data, schema)
        return {
            'is_valid': True,
            'errors': []
        }
    except jsonschema.ValidationError as e:
        return {
            'is_valid': False,
            'errors': [str(e)]
        }
```

## Example: External API Tool

```yaml
actions:
  - name: fetch_user_data
    kind: tool
    impl: integrations.api_client.get_user
    reads: [user_id]
    writes: [user_profile, api_status]
```

```python
# integrations/api_client.py
import requests
from typing import Dict, Any

def get_user(item_data: Dict[str, Any], context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch user data from external API."""
    user_id = item_data.get('user_id')

    try:
        response = requests.get(f"https://api.example.com/users/{user_id}")
        response.raise_for_status()

        return {
            'user_profile': response.json(),
            'api_status': 'success'
        }
    except requests.RequestException as e:
        return {
            'user_profile': None,
            'api_status': f'error: {str(e)}'
        }
```

## Mixing Tool and LLM Actions

Tool actions work seamlessly with LLM actions in the same workflow:

```yaml
defaults:
  model_vendor: anthropic
  model_name: claude-3-sonnet-20240229
  api_key: ${ANTHROPIC_API_KEY}

actions:
  # Step 1: Tool validates input
  - name: validate_input
    kind: tool
    impl: validators.check_input
    reads: [raw_text]
    writes: [is_valid, validation_errors]

  # Step 2: LLM processes valid input
  - name: analyze_text
    kind: llm
    reads: [raw_text, is_valid]
    writes: [analysis]
    prompt: "{% if is_valid %}Analyze: {{ raw_text }}{% endif %}"

  # Step 3: Tool formats output
  - name: format_output
    kind: tool
    impl: formatters.create_report
    reads: [analysis, validation_errors]
    writes: [final_report]
```

## Best Practices

1. **Keep tools focused** - Each tool should do one thing well
2. **Handle errors gracefully** - Return error information in outputs
3. **Document function signatures** - Make it clear what inputs are expected
4. **Use type hints** - Help other developers understand your tools
5. **Test independently** - Tool functions are just Python - easy to unit test

## See Also

- [Workflows](workflows.md) - Understanding workflow structure
- [Configuration Hierarchy](configuration-hierarchy.md) - How config is inherited
- [Agents](agents.md) - LLM action configuration
