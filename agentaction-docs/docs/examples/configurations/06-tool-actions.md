# Example 6: Tool Actions Configuration

This example demonstrates how to configure and use tool actions (non-LLM actions) in your workflows, including validation, API calls, data transformation, and mixing tool actions with LLM actions.

## What are Tool Actions?

Tool actions execute Python functions instead of calling LLM APIs. Use them for:
- Data validation and transformation
- External API calls
- File operations
- Database queries
- Business logic
- Any non-LLM processing

## Basic Tool Action Configuration

### Required Fields

```yaml
actions:
  - name: my_tool
    kind: tool                    # REQUIRED: Identifies as tool action
    impl: module.function_name    # REQUIRED: Python function to execute
    reads: [input_fields]         # Fields this tool reads
    writes: [output_fields]       # Fields this tool produces
```

### Automatic Behavior

When `kind: tool` is set:
- ✅ Automatically sets `model_vendor: tool`
- ✅ Automatically sets `model_name` to impl path
- ✅ Runs in online mode only (no batch support)
- ❌ Cannot specify `model_vendor`, `model_name`, or `api_key`

## Example 1: Data Validation Tool

### Implementation Function

Create `my_project/validators.py`:

```python
def validate_email(data: dict) -> dict:
    """
    Validates email addresses in input data.

    Args:
        data: Input data with 'email' field

    Returns:
        Dictionary with validation results
    """
    import re

    email = data.get('email', '')
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    is_valid = bool(re.match(email_pattern, email))

    return {
        'email': email,
        'is_valid': is_valid,
        'validation_message': 'Valid email' if is_valid else 'Invalid email format'
    }
```

### Workflow Configuration

```yaml
# workflows/validate-contacts.yml
actions:
  - name: validate_email
    kind: tool
    impl: my_project.validators.validate_email

    reads:
      - email

    writes:
      - is_valid
      - validation_message

# Automatic configuration:
# - model_vendor: tool (set automatically)
# - model_name: my_project.validators.validate_email (set automatically)
```

### Running

```bash
# Input data (contacts.jsonl)
{"email": "user@example.com"}
{"email": "invalid-email"}
{"email": "another@domain.org"}

# Run workflow
agent-actions run validate-contacts --input contacts.jsonl --output results.jsonl

# Output (results.jsonl)
{"email": "user@example.com", "is_valid": true, "validation_message": "Valid email"}
{"email": "invalid-email", "is_valid": false, "validation_message": "Invalid email format"}
{"email": "another@domain.org", "is_valid": true, "validation_message": "Valid email"}
```

## Example 2: External API Call

### Implementation Function

Create `my_project/external_apis.py`:

```python
import requests

def fetch_weather(data: dict) -> dict:
    """
    Fetches weather data from external API.

    Args:
        data: Input with 'location' field

    Returns:
        Dictionary with weather information
    """
    location = data.get('location')
    api_key = data.get('api_key')  # Could also use env var

    # Call external weather API
    url = f"https://api.weatherapi.com/v1/current.json"
    params = {
        'key': api_key,
        'q': location
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        weather_data = response.json()

        return {
            'location': location,
            'temperature': weather_data['current']['temp_c'],
            'condition': weather_data['current']['condition']['text'],
            'humidity': weather_data['current']['humidity'],
            'fetch_success': True
        }
    except Exception as e:
        return {
            'location': location,
            'fetch_success': False,
            'error': str(e)
        }
```

### Workflow Configuration

```yaml
# workflows/weather-analysis.yml
actions:
  - name: fetch_weather
    kind: tool
    impl: my_project.external_apis.fetch_weather

    reads:
      - location
      - api_key

    writes:
      - temperature
      - condition
      - humidity
      - fetch_success
```

## Example 3: Mixed Tool and LLM Actions

This example shows a realistic pipeline mixing tool actions (validation, API calls) with LLM actions (analysis).

### Implementation Functions

Create `my_project/tools.py`:

```python
def validate_and_clean(data: dict) -> dict:
    """Clean and validate input text."""
    text = data.get('raw_text', '').strip()

    return {
        'raw_text': text,
        'cleaned_text': text,
        'is_valid': len(text) > 10,
        'word_count': len(text.split())
    }

def enrich_with_metadata(data: dict) -> dict:
    """Add metadata from external source."""
    import datetime

    return {
        **data,
        'processed_at': datetime.datetime.utcnow().isoformat(),
        'version': '1.0',
        'enriched': True
    }
```

### Workflow Configuration

```yaml
# workflows/mixed-pipeline.yml

# Project defaults apply to LLM actions only
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7

actions:
  # STEP 1: Tool action - validate and clean
  - name: validate_input
    kind: tool
    impl: my_project.tools.validate_and_clean

    reads:
      - raw_text

    writes:
      - cleaned_text
      - is_valid
      - word_count

  # STEP 2: LLM action - analyze (only if valid)
  - name: analyze_content
    # No 'kind' specified = LLM action
    # Uses project config: openai, gpt-4o-mini

    reads:
      - cleaned_text
      - is_valid

    writes:
      - analysis
      - sentiment

    prompt: |
      {% if is_valid %}
      Analyze this text: {{ cleaned_text }}

      Provide analysis and sentiment.
      {% else %}
      Text is invalid. Skip analysis.
      {% endif %}

    schema:
      analysis: string
      sentiment: string

  # STEP 3: LLM action - generate summary
  - name: generate_summary

    reads:
      - cleaned_text
      - analysis

    writes:
      - summary

    prompt: |
      Based on this analysis: {{ analysis }}

      Summarize the original text: {{ cleaned_text }}

    schema:
      summary: string

  # STEP 4: Tool action - enrich with metadata
  - name: add_metadata
    kind: tool
    impl: my_project.tools.enrich_with_metadata

    reads:
      - cleaned_text
      - analysis
      - sentiment
      - summary

    writes:
      - processed_at
      - version
      - enriched
```

### Data Flow

```
Input: { raw_text: "..." }
   ↓
[validate_input] TOOL ACTION
   Adds: cleaned_text, is_valid, word_count
   ↓
[analyze_content] LLM ACTION (OpenAI)
   Adds: analysis, sentiment
   ↓
[generate_summary] LLM ACTION (OpenAI)
   Adds: summary
   ↓
[add_metadata] TOOL ACTION
   Adds: processed_at, version, enriched
   ↓
Output: { all accumulated fields }
```

### Configuration Resolution

```yaml
# Step 1: validate_input (tool action)
model_vendor: tool                              # Automatic
model_name: my_project.tools.validate_and_clean # Automatic

# Step 2: analyze_content (LLM action)
model_vendor: openai                            # From project
model_name: gpt-4o-mini                         # From project
api_key: ${OPENAI_API_KEY}                      # From project
temperature: 0.7                                # From project

# Step 3: generate_summary (LLM action)
model_vendor: openai                            # From project
model_name: gpt-4o-mini                         # From project
api_key: ${OPENAI_API_KEY}                      # From project
temperature: 0.7                                # From project

# Step 4: add_metadata (tool action)
model_vendor: tool                              # Automatic
model_name: my_project.tools.enrich_with_metadata # Automatic
```

## Example 4: Database Operations

### Implementation Function

```python
import sqlite3

def query_database(data: dict) -> dict:
    """
    Query database for additional information.

    Args:
        data: Input with 'user_id' field

    Returns:
        User information from database
    """
    user_id = data.get('user_id')

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name, email, account_type FROM users WHERE id = ?",
        (user_id,)
    )

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'user_id': user_id,
            'user_name': result[0],
            'user_email': result[1],
            'account_type': result[2],
            'found': True
        }
    else:
        return {
            'user_id': user_id,
            'found': False
        }
```

### Workflow Configuration

```yaml
actions:
  - name: lookup_user
    kind: tool
    impl: my_project.database.query_database

    reads:
      - user_id

    writes:
      - user_name
      - user_email
      - account_type
      - found

  - name: personalize_message
    # LLM action using user data
    reads:
      - user_name
      - account_type

    writes:
      - personalized_message

    prompt: |
      Create a personalized message for {{ user_name }}.
      Account type: {{ account_type }}

    schema:
      personalized_message: string
```

## Configuration Rules and Limitations

### What You CANNOT Do with Tool Actions

```yaml
# ❌ INVALID: Cannot specify model_vendor for tool actions
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    model_vendor: openai        # ERROR: tool actions don't use vendors

# ❌ INVALID: Cannot specify model_name for tool actions
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    model_name: gpt-4o          # ERROR: model_name is auto-set

# ❌ INVALID: Cannot specify api_key for tool actions
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    api_key: ${KEY}             # ERROR: tool actions don't use API keys

# ❌ INVALID: Cannot use batch mode with tool actions
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    batch_mode: true            # ERROR: tools run in online mode only
```

### What You CAN Do

```yaml
# ✅ VALID: Minimal tool action
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    reads: [input]
    writes: [output]

# ✅ VALID: Tool action with conditional execution
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    reads: [input]
    writes: [output]
    where_clause:
      clause: input != null
      scope: item
      behavior: filter

# ✅ VALID: Mix tool and LLM actions in same workflow
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

actions:
  - name: tool_step
    kind: tool                  # Tool action
    impl: my_module.function
    # ...

  - name: llm_step             # LLM action (uses project config)
    reads: [data]
    writes: [analysis]
    prompt: "Analyze: {{ data }}"
    schema: { analysis: string }
```

## Error Handling in Tool Actions

### Implementation with Error Handling

```python
def safe_transformation(data: dict) -> dict:
    """
    Transform data with error handling.

    Args:
        data: Input data

    Returns:
        Transformed data or error information
    """
    try:
        value = data.get('value')

        if value is None:
            raise ValueError("Missing required field 'value'")

        # Perform transformation
        result = complex_operation(value)

        return {
            'value': value,
            'result': result,
            'success': True,
            'error': None
        }

    except Exception as e:
        return {
            'value': data.get('value'),
            'result': None,
            'success': False,
            'error': str(e)
        }

def complex_operation(value):
    # Your transformation logic here
    return value.upper()
```

### Workflow with Error Handling

```yaml
actions:
  - name: transform_data
    kind: tool
    impl: my_module.safe_transformation

    reads:
      - value

    writes:
      - result
      - success
      - error

  - name: handle_result
    # LLM action that handles errors
    reads:
      - success
      - result
      - error

    writes:
      - final_output

    prompt: |
      {% if success %}
      Process this successful result: {{ result }}
      {% else %}
      Handle this error: {{ error }}
      Provide fallback output.
      {% endif %}

    schema:
      final_output: string
```

## Best Practices

### 1. Function Signature

Always use this signature for tool functions:

```python
def my_tool(data: dict) -> dict:
    """
    Description of what this tool does.

    Args:
        data: Input data dictionary

    Returns:
        Output data dictionary
    """
    # Implementation
    return {...}
```

### 2. Document Reads and Writes

```yaml
actions:
  - name: my_tool
    kind: tool
    impl: my_module.my_function

    # Clearly document what fields are used
    reads:
      - field1    # Description of field1
      - field2    # Description of field2

    # Clearly document what fields are produced
    writes:
      - output1   # Description of output1
      - output2   # Description of output2
```

### 3. Return All Read Fields

Include all read fields in the output:

```python
def my_tool(data: dict) -> dict:
    input_value = data.get('input_field')

    # Process...
    result = process(input_value)

    # Return input fields plus new fields
    return {
        'input_field': input_value,  # Include input
        'result': result              # Add output
    }
```

### 4. Validate Inputs

```python
def my_tool(data: dict) -> dict:
    # Validate required fields
    required_fields = ['field1', 'field2']
    missing = [f for f in required_fields if f not in data]

    if missing:
        return {
            'success': False,
            'error': f"Missing required fields: {', '.join(missing)}"
        }

    # Process...
    return {
        'success': True,
        'result': ...
    }
```

### 5. Use Environment Variables

```python
import os

def api_call(data: dict) -> dict:
    # Get API key from environment
    api_key = os.getenv('EXTERNAL_API_KEY')

    if not api_key:
        return {
            'success': False,
            'error': 'EXTERNAL_API_KEY environment variable not set'
        }

    # Make API call...
    return {...}
```

## When to Use Tool Actions vs LLM Actions

### Use Tool Actions For:

✅ Data validation and cleaning
✅ External API calls
✅ Database queries
✅ File operations
✅ Mathematical calculations
✅ Data transformations
✅ Business logic
✅ Deterministic operations

### Use LLM Actions For:

✅ Text analysis and understanding
✅ Content generation
✅ Summarization
✅ Classification (when rules are complex)
✅ Sentiment analysis
✅ Translation
✅ Question answering
✅ Creative tasks

## Next Steps

- [Example 7: Batch Mode](./07-batch-mode.md) - High-volume processing
- [Core Concepts: Tool Actions](../../core-concepts/tool-actions.md) - Detailed documentation
- [Core Concepts: Workflows](../../core-concepts/workflows.md) - Workflow design patterns

## Complete Working Example

See `templates/workflows/multi-vendor-workflow.yml` for a complete example mixing tool and LLM actions in a production pipeline.
