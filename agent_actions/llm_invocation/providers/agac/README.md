# Agac Provider

A mock LLM provider for testing agent-actions workflows without real API calls.

## Overview

The `agac-provider` generates **realistic fake data** based on JSON schemas and prompts. It's designed for:

- **Testing recovery mechanisms** (reprompt, retry)
- **CI/CD pipelines** (no API keys needed)
- **Local development** (instant responses)
- **Feature development** (predictable behavior)

## Quick Start

```yaml
# In your workflow config
defaults:
  model_vendor: agac-provider
  model_name: agac-model
  json_mode: true
```

That's it! No API keys required.

## Key Features

### 1. Realistic Data Generation

Unlike simple mock providers, agac generates **contextually appropriate data**:

```yaml
schema:
  type: object
  properties:
    name: { type: string }
    email: { type: string }
    age: { type: integer }
    company: { type: string }
    status: { type: string }
```

```json
{
  "name": "Charlotte Johnson",
  "email": "james.williams2@test.org",
  "age": 32,
  "company": "CoreLogic",
  "status": "pending"
}
```

### 2. Field-Name-Aware Generation

The generator recognizes field names and produces appropriate values:

| Field Pattern | Generated Data |
|--------------|----------------|
| `email`, `*_email` | `james.smith@example.com` |
| `name`, `fullname` | `Charlotte Johnson` |
| `first_name` | `James` |
| `last_name` | `Williams` |
| `url`, `link`, `href` | `https://example.com/resource/1` |
| `id`, `*_id` | `user_id_4521_1` |
| `date`, `created_at` | `2024-03-15T14:30:00Z` |
| `title`, `subject` | `Primary Module Process Report` |
| `description`, `summary` | Varied sentence |
| `status` | `pending`, `active`, `completed`... |
| `priority` | `low`, `medium`, `high`... |
| `category`, `type` | `technology`, `business`... |
| `company`, `organization` | `TechFlow Inc`, `Acme Corp`... |
| `city`, `location` | `New York`, `San Francisco`... |
| `country` | `USA`, `Canada`, `UK`... |
| `phone`, `mobile` | `+1-555-123-4567` |
| `address` | `1234 Smith Street` |
| `age` | 18-80 |
| `price`, `amount` | 9.99-999.99 |
| `score`, `rating` | 1-100 |

### 3. Prompt-Aware Generation

The generator uses prompts to seed the random number generator, ensuring:
- **Reproducibility**: Same prompt = same output
- **Variety**: Different prompts = different outputs

```python
# Same schema, different prompts = different data
FakeDataGenerator.set_context(prompt="Generate HR employee data")
data1 = FakeDataGenerator.generate_from_schema(schema, 3)

FakeDataGenerator.set_context(prompt="Generate customer data")
data2 = FakeDataGenerator.generate_from_schema(schema, 3)
# data1 != data2
```

### 4. Attempt-Based Quality Variation

Data quality varies by attempt number (for testing reprompt/retry):

| Attempt | String Length | Array Size | Purpose |
|---------|--------------|------------|---------|
| 1 | 3 words | 1 item | Fails most validations |
| 2 | 8 words | 2 items | May still fail |
| 3+ | 25 words | 3 items | Passes most validations |

## Supported Schema Types

### Primitives

| Type | Example Output |
|------|----------------|
| `string` | Contextual or varied sentence |
| `integer` | `32`, `45`, `78` (varies) |
| `number` | `123.45`, `67.89` (varies) |
| `boolean` | `true` / `false` (random) |
| `null` | `null` |

### Complex Types

| Type | Behavior |
|------|----------|
| `object` | Generates all properties with field-aware values |
| `array` | Generates items (size based on attempt) |

### Advanced Schema Features

| Feature | Behavior |
|---------|----------|
| `enum` | Returns random enum value |
| `const` | Returns the const value |
| `oneOf` | Generates from option based on attempt |
| `anyOf` | Generates from option based on attempt |
| `allOf` | Merges all schemas |

### String Formats

| Format | Example Output |
|--------|----------------|
| `email` | `james.smith1@example.com` |
| `uri` | `https://demo.io/module/1` |
| `date` | `2024-07-15` |
| `date-time` | `2024-07-15T14:30:00Z` |
| `time` | `14:30:45` |
| `uuid` | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `ipv4` | `192.168.1.45` |
| `ipv6` | `2001:db8::1234:5678` |

### Constraints

| Constraint | Behavior |
|------------|----------|
| `minLength` | Extends string to meet minimum |
| `maxLength` | Truncates string to maximum |
| `minimum` | Clamps number to minimum |
| `maximum` | Clamps number to maximum |
| `minItems` | Ensures minimum array length |
| `maxItems` | Limits array length |

## Usage Examples

### Testing Reprompt

```yaml
actions:
  - name: generate_summary
    schema: summary_schema
    reprompt:
      validation: check_length
      max_attempts: 3
      on_exhausted: return_last
```

The provider will:
1. Return short strings on attempt 1 → validation fails
2. Return medium strings on attempt 2 → validation may fail
3. Return full strings on attempt 3 → validation passes

### Testing Batch Processing

```yaml
defaults:
  run_mode: batch
  model_vendor: agac-provider
```

Batch jobs complete instantly with deterministic results.

### Non-JSON Mode

```yaml
defaults:
  json_mode: false
  model_vendor: agac-provider
```

Returns varied text in the configured `output_field`.

## Files

| File | Description |
|------|-------------|
| `client.py` | Online/realtime client (extends BaseClient) |
| `batch_client.py` | Batch client (extends BaseBatchClient) |
| `fake_data_generator.py` | Schema and prompt-aware data generation |

## API Reference

### AgacClient

```python
from agent_actions.llm_invocation.providers.agac import AgacClient

# Follows same interface as OpenAIClient
result = AgacClient.invoke(
    agent_config={"json_mode": True},
    prompt_config="Generate employee records for the HR department",
    context_data={"source_guid": "emp-001"},
    schema={"type": "object", "properties": {...}}
)
```

### AgacBatchClient

```python
from agent_actions.llm_invocation.providers.agac import AgacBatchClient

client = AgacBatchClient(polls_until_complete=2)
batch_id, status = client.submit_batch(tasks, batch_dir, batch_name)
results = client.retrieve_results(batch_id)
```

### FakeDataGenerator

```python
from agent_actions.llm_invocation.providers.agac import FakeDataGenerator

# Set context for reproducibility
FakeDataGenerator.set_context(seed=42, prompt="Generate user data")

# Generate from any schema
schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "email": {"type": "string"},
        "age": {"type": "integer", "minimum": 18, "maximum": 80}
    }
}

data = FakeDataGenerator.generate_from_schema(schema, attempt=3)
# {"name": "Charlotte Johnson", "email": "james.williams3@test.org", "age": 45}

# Generate plain text response
text = FakeDataGenerator.generate_text_response("Describe the weather", attempt=2)
# "Public event invoke cycle secondary stage route report."
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGAC_BATCH_POLLS_UNTIL_COMPLETE` | Polls before batch completes | `0` |

## Resetting State

For tests, reset state between test cases:

```python
from agent_actions.llm_invocation.providers.agac import AgacClient, AgacBatchClient

# Reset online client (clears attempt tracking)
AgacClient.reset()

# Reset batch client (clears batch state)
AgacBatchClient.reset()
```

## Comparison with Real Providers

| Feature | agac-provider | openai |
|---------|--------------|--------|
| API Key Required | No | Yes |
| Network Calls | No | Yes |
| Response Time | Instant | Variable |
| Deterministic | Yes (seeded) | No |
| Cost | Free | Pay per token |
| Schema Support | Full | Full |
| Batch Support | Yes | Yes |
| Realistic Data | Yes | Yes |
| Field-Aware | Yes | N/A |
| Prompt-Aware | Yes | Yes |

## Best Practices

1. **Use for CI/CD**: No API keys or network needed
2. **Test validation logic**: Predictable failures on attempts 1-2
3. **Test recovery flows**: Automatic success on attempt 3+
4. **Reset between tests**: Call `AgacClient.reset()` to clear state
5. **Set seeds for reproducibility**: Use `FakeDataGenerator.set_context(seed=42)`

## Word Pools

The generator uses curated word pools for realistic output:

- **Nouns**: system, user, data, process, service, module, component...
- **Adjectives**: primary, active, pending, valid, critical, standard...
- **Verbs**: process, analyze, validate, transform, generate, create...
- **Names**: James, Emma, Liam, Olivia, Noah, Ava, Oliver...
- **Companies**: Acme Corp, TechFlow Inc, DataSync Systems...
- **Cities**: New York, Los Angeles, Chicago, Houston...
