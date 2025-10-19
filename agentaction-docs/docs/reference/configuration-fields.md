---
title: Configuration Fields Reference
description: Complete reference for all configuration fields
sidebar_position: 2
---

# Configuration Fields Reference

This page documents every configuration field available in Agent Actions, organized by category. Each field includes type information, defaults, and examples.

## Core Fields

### `name`
- **Type**: `string`
- **Required**: Yes (action level)
- **Default**: None
- **Description**: Unique identifier for the action within the workflow
- **Example**:
  ```yaml
  name: extract_entities
  ```
- **Notes**: Must be unique within the workflow. Used in dependency declarations and execution plan.

### `intent`
- **Type**: `string`
- **Required**: Yes (action level)
- **Default**: None
- **Description**: Clear description of what the action does
- **Example**:
  ```yaml
  intent: Extract named entities from the input text
  ```
- **Notes**: Helps document the workflow and appears in logs/error messages.

### `model_vendor`
- **Type**: `string` (enum)
- **Required**: At least one level (project/workflow/action)
- **Default**: None
- **Valid Values**: `openai`, `anthropic`, `google`, `gemini`, `groq`, `cohere`, `mistral`, `deepseek`, `ollama`, `tool`
- **Description**: LLM vendor/provider to use for this action
- **Example**:
  ```yaml
  model_vendor: anthropic
  ```
- **Notes**:
  - Project-level uses this field name
  - Workflow/action-level also uses this field name (standardized in Phase 3)
  - Required after configuration hierarchy resolution
  - Validated against `VendorType` enum

### `model_name`
- **Type**: `string`
- **Required**: At least one level (project/workflow/action)
- **Default**: None
- **Description**: Specific model identifier for the vendor
- **Examples**:
  ```yaml
  # OpenAI
  model_name: gpt-4o-mini
  model_name: gpt-4-turbo

  # Anthropic
  model_name: claude-3-5-sonnet-20241022
  model_name: claude-3-haiku-20240307

  # Google
  model_name: gemini-1.5-flash
  model_name: gemini-1.5-pro

  # Groq
  model_name: llama-3.1-70b-versatile
  model_name: mixtral-8x7b-32768
  ```
- **Notes**:
  - Project-level uses this field name
  - Workflow/action-level also uses this field name (standardized in Phase 3)
  - Validated per-vendor (e.g., must start with `gpt-` for OpenAI)

### `api_key`
- **Type**: `string`
- **Required**: At least one level (project/workflow/action)
- **Default**: None
- **Description**: API key for the vendor, typically an environment variable reference
- **Examples**:
  ```yaml
  # Environment variable reference (recommended)
  api_key: ${ANTHROPIC_API_KEY}
  api_key: ${OPENAI_API_KEY}

  # Direct value (NOT recommended for production)
  api_key: sk-ant-api03-...
  ```
- **Notes**:
  - Use `${VAR_NAME}` syntax for environment variables
  - Validated to ensure env var exists at parse time
  - Never commit actual API keys to version control

## Execution Fields

### `kind`
- **Type**: `string` (enum: `ActionKind`)
- **Required**: No
- **Default**: `llm`
- **Valid Values**: `llm`, `tool`
- **Description**: Type of action - LLM-based or tool/function execution
- **Example**:
  ```yaml
  # LLM action (default)
  kind: llm

  # Tool action (requires impl field)
  kind: tool
  impl: tools.validation.check_data
  ```
- **Notes**:
  - `llm` actions call LLM APIs
  - `tool` actions execute Python functions
  - Tool actions require `impl` field

### `impl`
- **Type**: `string`
- **Required**: Yes (if `kind: tool`)
- **Default**: None
- **Description**: Python import path to tool implementation
- **Example**:
  ```yaml
  kind: tool
  impl: agent_actions.tools.validators.check_schema
  ```
- **Notes**:
  - Only used for tool actions
  - Must be a valid Python import path
  - Function must accept input data and return output data

### `run_mode`
- **Type**: `string`
- **Required**: No
- **Default**: `online`
- **Valid Values**: `online`, `batch`
- **Description**: Execution mode for the action
- **Example**:
  ```yaml
  # Immediate execution
  run_mode: online

  # Batch processing (50% cost savings with Anthropic)
  run_mode: batch
  ```
- **Notes**:
  - `online`: Immediate synchronous execution
  - `batch`: Asynchronous batch processing (not all vendors support)
  - Batch mode has 24-hour processing window

### `granularity`
- **Type**: `string` (enum: `Granularity`)
- **Required**: No
- **Default**: `record` (typically)
- **Valid Values**: `record`, `file`
- **Description**: Processing granularity for the action
- **Example**:
  ```yaml
  # Process each record individually
  granularity: record

  # Process entire file at once
  granularity: file
  ```
- **Notes**:
  - `record`: Each item in input processed separately
  - `file`: All items processed together as a batch

### `is_operational`
- **Type**: `boolean`
- **Required**: No
- **Default**: `true`
- **Description**: Whether the action is enabled
- **Example**:
  ```yaml
  # Enable action
  is_operational: true

  # Disable action (skipped during execution)
  is_operational: false
  ```
- **Notes**: Useful for temporarily disabling actions without removing them

## LLM Configuration Fields

### `json_mode`
- **Type**: `boolean`
- **Required**: No
- **Default**: `true` (for most vendors)
- **Description**: Enable JSON response mode
- **Example**:
  ```yaml
  json_mode: true
  ```
- **Notes**:
  - Forces LLM to return valid JSON
  - Required for schema validation to work
  - Most vendors support this
  - **EXCEPTION**: Ollama does **NOT** support `json_mode: true` and will fail fast with a `ConfigurationError`
  - When using Ollama, you **MUST** set `json_mode: false`

### `few_shot`
- **Type**: `integer`
- **Required**: No
- **Default**: `0` or `null`
- **Description**: Number of few-shot examples to include in prompts
- **Example**:
  ```yaml
  few_shot: 3
  ```
- **Notes**:
  - Improves output quality by providing examples
  - Must be ≥ 0
  - Examples must exist in the system

### `output_field`
- **Type**: `string`
- **Required**: No
- **Default**: `raw_response`
- **Description**: Field name for wrapping LLM response when `json_mode: false`
- **Example**:
  ```yaml
  # Ollama configuration with custom output field
  model_vendor: ollama
  json_mode: false
  output_field: extracted_facts
  ```
- **Notes**:
  - Only applies when `json_mode: false` (non-JSON mode)
  - Used by vendors like Ollama and OpenAI for plain text responses
  - Response will be wrapped as: `{"<output_field>": "LLM response text"}`
  - Default wrapping: `{"raw_response": "LLM response text"}`

### `base_url`
- **Type**: `string`
- **Required**: No
- **Default**: Vendor-specific (Ollama: `http://localhost:11434`)
- **Description**: Base URL for vendor API endpoint
- **Example**:
  ```yaml
  # Ollama on custom server
  model_vendor: ollama
  base_url: http://192.168.1.100:11434

  # Ollama using environment variable
  # (Leave base_url unset, set OLLAMA_HOST env var instead)
  ```
- **Notes**:
  - Primarily used by Ollama for local model servers
  - Falls back to environment variables (e.g., `OLLAMA_HOST` for Ollama)
  - Other vendors use their standard cloud endpoints

### `temperature`
- **Type**: `number`
- **Required**: No
- **Default**: Vendor default (typically 0.7-1.0)
- **Description**: Sampling temperature for LLM (0.0 to 2.0)
- **Example**:
  ```yaml
  # Deterministic output
  temperature: 0.0

  # Balanced
  temperature: 0.7

  # Creative output
  temperature: 1.5
  ```
- **Notes**:
  - Lower = more deterministic
  - Higher = more creative/random
  - Range: 0.0-2.0

### `max_tokens`
- **Type**: `integer`
- **Required**: No
- **Default**: Vendor default
- **Description**: Maximum tokens in response
- **Example**:
  ```yaml
  max_tokens: 2000
  ```
- **Notes**:
  - Limits response length
  - Affects cost
  - Must be ≥ 1

### `anthropic_version`
- **Type**: `string`
- **Required**: No (Anthropic only)
- **Default**: `2023-06-01`
- **Description**: API version header for Anthropic requests
- **Example**:
  ```yaml
  anthropic_version: "2023-06-01"
  ```
- **Notes**: Anthropic-specific field, controls API features

### `enable_prompt_caching`
- **Type**: `boolean`
- **Required**: No (Anthropic only)
- **Default**: `false`
- **Description**: Enable Anthropic's prompt caching feature
- **Example**:
  ```yaml
  enable_prompt_caching: true
  ```
- **Notes**:
  - Reduces costs for repeated prompts
  - Anthropic-specific feature
  - See Anthropic docs for cache behavior

## Data Flow Fields

### `observe`
- **Type**: `array` of `string`
- **Required**: No
- **Default**: `[]` (empty list)
- **Description**: Fields to pass-through from input to output without LLM generation. These fields ARE visible to the LLM but are not regenerated by it.
- **Example**:
  ```yaml
  observe:
    - document_id
    - timestamp
    - source_url
  ```
- **Notes**:
  - Fields ARE available to the LLM (can be referenced in prompts)
  - Fields are copied from input to output (not generated by LLM)
  - Useful for preserving metadata and correlation IDs
  - Allows LLM to reference these fields when making decisions

### `drops`
- **Type**: `array` of `string`
- **Required**: No
- **Default**: `[]` (empty list)
- **Description**: Fields to exclude from both LLM prompt AND final output
- **Example**:
  ```yaml
  drops:
    - raw_html
    - debug_info
    - _internal
  ```
- **Notes**:
  - Completely removes fields from processing
  - Use for sensitive data or large unnecessary fields
  - More aggressive than `observe`

### `schema` / `output_schema`
- **Type**: `string` or `object`
- **Required**: No (but recommended for LLM actions)
- **Default**: None
- **Description**: Output schema for validation
- **Examples**:
  ```yaml
  # Reference to schema file
  schema: sentiment_analysis

  # Inline schema object
  schema:
    type: object
    properties:
      sentiment:
        type: string
        enum: [positive, negative, neutral]
      confidence:
        type: number
    required: [sentiment, confidence]
  ```
- **Notes**:
  - Both `schema` and `output_schema` are valid (alias)
  - Can be schema name or inline JSON Schema object
  - Enables validation of LLM outputs

### `prompt`
- **Type**: `string`
- **Required**: No
- **Default**: None
- **Description**: Prompt template for the LLM
- **Example**:
  ```yaml
  prompt: |
    Analyze the sentiment of the following text.

    Text: {input_text}

    Return a JSON object with sentiment (positive/negative/neutral) and confidence (0-1).
  ```
- **Notes**:
  - Supports templating with `{variable}` syntax
  - Can be multiline using YAML `|` syntax
  - Variables interpolated from input data

## Advanced Fields

### `guard`
- **Type**: `string` or `object`
- **Required**: No
- **Default**: None
- **Description**: Conditional execution guard
- **Examples**:
  ```yaml
  # String format (legacy)
  guard: "len(items) > 0"

  # Object format (new consolidated guard)
  guard:
    condition: has_data
    field: items
  ```
- **Notes**:
  - Action only executes if guard evaluates to true
  - Validated for security (blocks `exec`, `eval`, etc.)
  - See [Configuration Schema](./configuration-schema.md#guard-expression-validator) for details

### `policy`
- **Type**: `string`
- **Required**: No
- **Default**: None
- **Description**: Execution policy (e.g., retry behavior)
- **Example**:
  ```yaml
  policy: retry
  ```
- **Notes**: Controls retry and error handling behavior

### `loop`
- **Type**: `object` (`LoopConfig`)
- **Required**: No
- **Default**: None
- **Description**: Loop configuration for parametric execution with support for parallel and sequential execution modes

#### Loop Configuration Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `param` | `string` | Yes | - | Variable name for loop parameter |
| `range` | `array` | Yes | - | Range of values: `[start, end]` (inclusive) or explicit list `[10, 20, 30]` |
| `mode` | `string` | No | `"parallel"` | Execution mode: `"parallel"` or `"sequential"` |

#### Execution Modes

**`parallel` (default)**
- All loop iterations run independently
- Iterations execute concurrently
- Each iteration depends on the same parent agents
- Best for independent processing tasks

**`sequential`**
- Iterations run in order: iteration N+1 waits for iteration N
- Creates dependency chain: iteration 2 ← iteration 1
- Each iteration can access previous iteration's output
- Best for iterative refinement workflows

#### Template Variables

Loop parameters support template variable syntax in all configuration fields:

- **`${param}`**: Replaced with current iteration value
- **`${param-1}`**: Replaced with previous iteration value (empty string on first iteration)

Template variables work in: `prompt`, `observe`, `drops`, `reads`, `writes`, `schema`, and all other config fields.

#### Examples

**Basic Parallel Loop (Default)**
```yaml
loop:
  param: i
  range: [1, 5]
  # mode: parallel is implicit
```

Creates 5 independent iterations: `action_1`, `action_2`, `action_3`, `action_4`, `action_5`

**Sequential Refinement Loop**
```yaml
loop:
  param: stage
  range: [1, 3]
  mode: sequential

prompt: "Refine stage ${stage}: improve output from stage ${stage-1}"
observe:
  - refined_output_${stage}
```

Creates 3 sequential iterations:
- `action_1`: depends on parent, `${stage-1}` → empty string
- `action_2`: depends on `action_1`, `${stage-1}` → `"1"`
- `action_3`: depends on `action_2`, `${stage-1}` → `"2"`

**Explicit Range Values**
```yaml
loop:
  param: level
  range: [10, 20, 30]  # Explicit list instead of [start, end]
  mode: sequential

prompt: "Process level ${level} (previous: ${level-1})"
```

Creates iterations with values 10, 20, 30:
- `${level}` in iteration 1 → `"10"`, `${level-1}` → empty string
- `${level}` in iteration 2 → `"20"`, `${level-1}` → `"10"`
- `${level}` in iteration 3 → `"30"`, `${level-1}` → `"20"`

**Template Variables in Schema**
```yaml
loop:
  param: pass
  range: [1, 4]
  mode: sequential

schema:
  pass_number: integer
  current_data: refined_${pass}
  previous_data: refined_${pass-1}

observe:
  - refined_${pass}
```

#### Notes
- **Backward Compatibility**: Loops without `mode` default to `parallel` (existing behavior)
- **Template Expansion**: `${param}` and `${param-1}` are replaced during loop expansion
- **Dependency Chaining**: Sequential mode automatically creates `iteration_N+1 <- iteration_N` dependencies
- **Error Propagation**: In sequential mode, if iteration N fails, iterations N+1 onwards are skipped
- **Performance**: Sequential loops have linear execution time (sum of all iterations), parallel loops can run concurrently

### `loop_consumption`
- **Type**: `object` (`LoopConsumptionConfig`)
- **Required**: No
- **Default**: None
- **Description**: Configuration for consuming outputs from looped actions
- **Example**:
  ```yaml
  loop_consumption:
    source: process_batch
    pattern: merge
  ```
- **Notes**:
  - `source`: Name of the looped action to consume from
  - `pattern`: `merge` (dict.update() behavior - last wins)

### `idempotency_key`
- **Type**: `string`
- **Required**: No
- **Default**: None
- **Description**: Template for idempotency key
- **Example**:
  ```yaml
  idempotency_key: "process_{document_id}_{version}"
  ```
- **Notes**:
  - Prevents duplicate processing
  - Supports templating with `{variable}` syntax

### `chunk_config`
- **Type**: `object`
- **Required**: No
- **Default**: `{}`
- **Description**: Configuration for text chunking
- **Example**:
  ```yaml
  chunk_config:
    chunk_size: 1000
    chunk_overlap: 100
  ```
- **Notes**: Used when processing large texts that exceed token limits

### `interceptors`
- **Type**: `List[InterceptorConfig]`
- **Required**: No
- **Default**: `[]`
- **Level**: Action level
- **Description**: Response interceptors for validation and automatic reprompting when validation fails
- **Schema Reference**: `InterceptorConfig` in `core/parser/config_schema.py`
- **Example**:
  ```yaml
  interceptors:
    # Validation interceptor
    - type: validation
      validator_function: "agent_actions.agents.validators.functions.validate_word_count"
      validator_args:
        expected: 5
      on_failure: retry

    # Reprompt interceptor
    - type: reprompt
      strategy: "llm"
      max_attempts: 3
      llm_config:
        model_vendor: "openai"
        model_name: "gpt-4"
  ```
- **See Also**: [Reprompting & Custom Validators Guide](../guides/reprompting.md)

#### `interceptors[].type`
- **Type**: `string` (enum)
- **Required**: Yes
- **Valid Values**: `validation`, `reprompt`, `logging`
- **Description**: Type of interceptor
- **Example**:
  ```yaml
  interceptors:
    - type: validation  # Validates response
    - type: reprompt    # Generates improved prompts
  ```

#### `interceptors[].validator_function`
- **Type**: `string`
- **Required**: Yes (when `type: validation`)
- **Description**: Validator function reference in format `module_name.function_name`
- **Examples**:
  ```yaml
  # Built-in validator
  validator_function: "agent_actions.agents.validators.functions.validate_word_count"

  # Custom validator (in tools directory)
  validator_function: "my_validators.validate_json_structure"
  ```
- **Notes**:
  - Loads from `tools.path` directory for custom validators
  - Validator must return `Tuple[bool, str | None]`
  - See [Custom Validators](../guides/reprompting.md#custom-validators) for details

#### `interceptors[].validator_args`
- **Type**: `dict`
- **Required**: No
- **Default**: `{}`
- **Description**: Arguments passed to the validator function
- **Example**:
  ```yaml
  interceptors:
    - type: validation
      validator_function: "agent_actions.agents.validators.functions.validate_char_count"
      validator_args:
        min_chars: 100
        max_chars: 500
  ```
- **Notes**: Merged with workflow context data, accessible via `**kwargs` in validator

#### `interceptors[].on_failure`
- **Type**: `string` (enum)
- **Required**: No
- **Default**: `retry`
- **Valid Values**: `retry`, `fail`, `continue`
- **Description**: Action to take when validation fails
- **Examples**:
  ```yaml
  # Trigger reprompt on failure (default)
  on_failure: retry

  # Stop immediately and raise error
  on_failure: fail

  # Log error but continue processing
  on_failure: continue
  ```
- **Notes**:
  - `retry`: Triggers reprompt interceptor to improve and retry
  - `fail`: Stops execution immediately
  - `continue`: Non-blocking validation (for monitoring)

#### `interceptors[].strategy`
- **Type**: `string` (enum)
- **Required**: Yes (when `type: reprompt`)
- **Valid Values**: `llm`, `simple`, `template`
- **Description**: Strategy for generating improved prompts
- **Examples**:
  ```yaml
  # LLM-based improvement
  strategy: "llm"

  # Append error to prompt
  strategy: "simple"

  # Use predefined templates
  strategy: "template"
  ```
- **Notes**:
  - `llm`: Uses LLM to analyze failure and craft better prompt (most sophisticated)
  - `simple`: Appends error message to original prompt (fast, no extra LLM call)
  - `template`: Uses pattern-matched templates (precise control)

#### `interceptors[].max_attempts`
- **Type**: `integer`
- **Required**: Yes (when `type: reprompt`)
- **Default**: `3`
- **Description**: Maximum number of retry attempts
- **Example**:
  ```yaml
  interceptors:
    - type: reprompt
      strategy: "simple"
      max_attempts: 2  # Try up to 2 times
  ```
- **Notes**: Prevents infinite retry loops

#### `interceptors[].llm_config`
- **Type**: `object`
- **Required**: Yes (when `strategy: llm`)
- **Description**: LLM configuration for reprompt generation
- **Example**:
  ```yaml
  interceptors:
    - type: reprompt
      strategy: "llm"
      llm_config:
        model_vendor: "openai"    # Required
        model_name: "gpt-4"       # Optional
        temperature: 0.7          # Optional
  ```
- **Sub-fields**:
  - `model_vendor` (required): Vendor for reprompt generation
  - `model_name` (optional): Specific model to use
  - `temperature` (optional): Sampling temperature

#### `interceptors[].templates`
- **Type**: `dict`
- **Required**: Yes (when `strategy: template`)
- **Description**: Template patterns for reprompt generation
- **Example**:
  ```yaml
  interceptors:
    - type: reprompt
      strategy: "template"
      templates:
        "too short": |
          {original_prompt}

          IMPORTANT: Must be at least {min_chars} characters.
        "missing keywords": |
          {original_prompt}

          CRITICAL: Include these keywords: {required_keywords}
  ```
- **Notes**:
  - Keys are pattern matchers for error messages
  - Values are template strings with {variable} placeholders
  - Variables come from validation_criteria/context

## Filtering and Conditional Fields

### `where_clause`
- **Type**: `object` (`WhereClauseConfig`)
- **Required**: No
- **Default**: None
- **Description**: SQL-like WHERE clause for filtering
- **Example**:
  ```yaml
  where_clause:
    clause: "confidence > 0.8"
    scope: item
    behavior: filter
  ```
- **Notes**:
  - `clause`: SQL-like condition
  - `scope`: `item` or `agent`
  - `behavior`: `skip` (passthrough) or `filter` (remove)
  - Validated for security

### `skip_condition`
- **Type**: `object` (`SkipConditionConfig`)
- **Required**: No
- **Default**: None
- **Description**: Safe skip condition configuration
- **Example**:
  ```yaml
  skip_condition:
    condition_type: previous_outputs_empty
    agent_name: extract
  ```
- **Notes**:
  - Replacement for unsafe `skip_if` eval-based conditions
  - Types: `previous_outputs_empty`, `previous_outputs_count`, `field_condition`, `custom`

### `conditional_clause` (Deprecated)
- **Type**: `string`
- **Required**: No
- **Default**: None
- **Description**: Legacy conditional clause
- **Example**:
  ```yaml
  conditional_clause: "item.score > 0.5"
  ```
- **Notes**: **Deprecated** - use `where_clause` instead

### `skip_if` (Deprecated)
- **Type**: `string`
- **Required**: No
- **Default**: None
- **Description**: Legacy skip condition
- **Example**:
  ```yaml
  skip_if: "len(previous_outputs['extract']) == 0"
  ```
- **Notes**: **Deprecated** - use `skip_condition` instead for safety

## Workflow-Level Fields

### `name` (Workflow)
- **Type**: `string`
- **Required**: Yes (workflow level)
- **Default**: None
- **Description**: Workflow name
- **Example**:
  ```yaml
  name: document_processing_pipeline
  ```

### `description` (Workflow)
- **Type**: `string`
- **Required**: Yes (workflow level)
- **Default**: None
- **Description**: Workflow description
- **Example**:
  ```yaml
  description: Multi-step pipeline for processing and analyzing documents
  ```

### `version` (Workflow)
- **Type**: `string`
- **Required**: Yes (workflow level)
- **Default**: None
- **Description**: Workflow version
- **Example**:
  ```yaml
  version: "1.0.0"
  ```

### `defaults` (Workflow)
- **Type**: `object` (`DefaultsConfig`)
- **Required**: No
- **Default**: None
- **Description**: Default settings applied to all actions
- **Example**:
  ```yaml
  defaults:
    model_vendor: openai
    model_name: gpt-4o-mini
    json_mode: true
    granularity: record
  ```
- **Notes**: Can include any action-level field

### `plan` (Workflow)
- **Type**: `array` of `string`
- **Required**: Yes (workflow level)
- **Default**: None
- **Description**: Execution plan with dependencies
- **Example**:
  ```yaml
  plan:
    - extract
    - analyze <- extract
    - summarize <- analyze
  ```
- **Notes**:
  - Lists actions in execution order
  - Use `<-` syntax to declare dependencies
  - All actions must be defined

## Vendor-Specific Fields

### OpenAI Fields

#### `frequency_penalty`
- **Type**: `number`
- **Range**: -2.0 to 2.0
- **Default**: 0.0
- **Description**: Penalize frequent token repetition

#### `presence_penalty`
- **Type**: `number`
- **Range**: -2.0 to 2.0
- **Default**: 0.0
- **Description**: Penalize token presence

#### `top_k`
- **Type**: `integer`
- **Range**: ≥ 1
- **Description**: Top-k sampling parameter

#### `response_format`
- **Type**: `string` (enum)
- **Valid Values**: `json`, `text`, `json_schema`
- **Default**: `json_schema`
- **Description**: Response format type

### Anthropic Fields

#### `tools_mode`
- **Type**: `boolean`
- **Default**: `true`
- **Description**: Use tools for JSON responses

### Google Fields

#### `safety_settings`
- **Type**: `object`
- **Default**: None
- **Description**: Safety filter settings
- **Example**:
  ```yaml
  safety_settings:
    HARM_CATEGORY_HARASSMENT: BLOCK_NONE
  ```

#### `generation_config`
- **Type**: `object`
- **Default**: None
- **Description**: Generation configuration
- **Example**:
  ```yaml
  generation_config:
    candidate_count: 1
    stop_sequences: ["END"]
  ```

## Deprecated Fields

### `vendor` (Deprecated)
- **Replacement**: `model_vendor`
- **Status**: Deprecated in Phase 3
- **Notes**: Use `model_vendor` at all configuration levels

### `model` (Deprecated)
- **Replacement**: `model_name`
- **Status**: Deprecated in Phase 3
- **Notes**: Use `model_name` at all configuration levels

## Field Type Reference

### Simple Types
- `string`: Text value
- `integer`: Whole number
- `number`: Decimal number (float)
- `boolean`: `true` or `false`

### Complex Types
- `array`: List of values (YAML list syntax)
- `object`: Nested key-value pairs (YAML dict syntax)

### Enums
- `ActionKind`: `llm`, `tool`
- `Granularity`: `record`, `file`
- `VendorType`: See [`model_vendor`](#model_vendor)
- `FilterScope`: `item`, `agent`
- `WhereClauseBehavior`: `skip`, `filter`

## Configuration Hierarchy

Fields can be specified at three levels:

1. **Project-level** (`agent_actions.yml`) - Organization-wide defaults
2. **Workflow-level** (`workflows/*.yml` defaults section) - Workflow-specific defaults
3. **Action-level** (individual action in workflow) - Action-specific settings

**Precedence**: Action > Workflow > Project

See [Configuration Hierarchy](../core-concepts/configuration-hierarchy.md) for details.

## Related Documentation

- [Configuration Schema](./configuration-schema.md) - Pydantic schema mapping
- [Configuration Hierarchy](../core-concepts/configuration-hierarchy.md) - How inheritance works
- [Configuration Examples](../examples/configurations/index.md) - Real-world examples
- [Workflows](../core-concepts/workflows.md) - Workflow structure
