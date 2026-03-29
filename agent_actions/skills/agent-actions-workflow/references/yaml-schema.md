# Workflow YAML Schema Reference

Complete reference for agent-actions workflow configuration.

## Configuration Hierarchy

```
agent_actions.yml (Project)
  └── workflow.yml defaults (Workflow)
        └── action fields (Action)
```

Higher specificity wins.

## Project Configuration

`agent_actions.yml` defines project-wide settings:

```yaml
default_agent_config:
  api_key: OPENAI_API_KEY
  model_name: gpt-4o-mini
  model_vendor: openai
  prompt_debug: false
  ephemeral: false
  chunk_config:
    overlap: 500
    chunk_size: 4000

tool_path: ["tools"]
```

## Workflow Configuration

```yaml
name: my_workflow
description: "Workflow description"
version: "1.0.0"

defaults:
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  json_mode: true
  granularity: record
  run_mode: online
  context_scope:
    seed_path:
      reference: $file:data.json

actions:
  - name: action_1
    # ...
```

## Action Fields Reference

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique action identifier |
| `intent` | string | Human-readable description |
| `kind` | string | `llm` (default) or `tool` |
| `impl` | string | Python function name (for tool actions) |
| `dependencies` | string/list | Input source(s) - see Dependency Patterns below |
| `primary_dependency` | string | Override which dependency is primary (for fan-in) |
| `reduce_key` | string | Aggregation key (groups merged outputs by this field) |
| `model_vendor` | string | LLM provider |
| `model_name` | string | Model identifier |
| `api_key` | string | Environment variable name |
| `prompt` | string | Prompt template or store reference |
| `schema` | string/object | Output schema |
| `json_mode` | boolean | Enable structured JSON output |
| `run_mode` | string | `online` or `batch` |
| `granularity` | string | `record` or `file` |
| `context_scope` | object | Data flow control |
| `guard` | object | Conditional execution |
| `prompt_debug` | boolean | Log rendered prompts |
| `reprompt` | false/object | Validation retry (requires explicit config) |
| `versions` | object | Version execution config |
| `is_operational` | boolean | Whether action is active (default: true) |
| `ephemeral` | boolean | Ephemeral execution mode |
| `max_tokens` | integer | Maximum tokens for LLM response |
| `temperature` | float | LLM temperature (0.0-2.0) |
| `max_execution_time` | integer | Timeout in seconds (default: 300) |
| `enable_caching` | boolean | Enable response caching (default: true) |
| `record_limit` | integer | Max records to process per file at start nodes (default: unlimited) |
| `file_limit` | integer | Max files to walk per action (default: unlimited) |

## LLM Action Example

```yaml
- name: extract_facts
  intent: "Extract facts from content"
  dependencies: prior_action           # Single input source

  # LLM Settings
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY

  # Prompt & Schema
  prompt: $prompts.extract_facts
  schema: facts_schema
  json_mode: true

  # Execution
  run_mode: online
  granularity: record

  # Context (context deps auto-inferred)
  context_scope:
    observe: [upstream.field]
    drop: [source.unused]
    passthrough: [source.metadata]

  # Conditional
  guard:
    condition: "facts != []"
    on_false: filter

  # Debug
  prompt_debug: true
```

## Tool Action Example

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
  dependencies: prior_action           # Single input source
```

## Versions Configuration

Execute actions in parallel or sequential versions:

```yaml
- name: generate_variant
  versions:
    param: variant_id
    range: [1, 2, 3]
    mode: parallel  # or sequential
  prompt: "Generate variant {{ variant_id }}"
```

**Dynamic Template Variables:**

```yaml
- name: generate_distractors
  versions:
    param: stage
    range: [1, 3]
  schema:
    distractor_${stage}: string        # → distractor_1, distractor_2, distractor_3
    why_incorrect_${stage}: string
```

**Version Consumption:**

```yaml
- name: combine_results
  dependencies: generate_distractors
  version_consumption:
    source: generate_distractors
    pattern: merge    # Combines all version outputs
```

## Dependency Patterns

| Pattern | Config | Behavior |
|---------|--------|----------|
| **Single** | `dependencies: action_A` | Output becomes input |
| **Parallel** | `dependencies: [classify_1, classify_2]` | Outputs **merged** (same base name) |
| **Fan-in** | `dependencies: [extract, enrich, validate]` | All available, **matched by lineage** |
| **Aggregation** | `dependencies: [...], reduce_key: id` | All **merged**, grouped by key |

**Parallel Branches** - created with `versions`:
```yaml
- name: research
  versions: { range: [1, 3], mode: parallel }

- name: synthesize
  dependencies: [research]
  version_consumption:
    source: research
    pattern: merge    # Combines all version outputs
```

> **Warning:** After expansion, versioned actions produce `research_1`, `research_2`, `research_3`. Listing base names like `dependencies: [research]` fails validation unless you use `version_consumption`. Either use `version_consumption` (preferred) or list every expanded name explicitly: `dependencies: [research_1, research_2, research_3]`.

**Fan-in** - different actions converging:
```yaml
# Default: first dependency is primary (determines execution count)
- name: generate_report
  dependencies: [analyze_sentiment, analyze_entities, analyze_topics]
  # analyze_sentiment determines execution count
  # analyze_entities and analyze_topics are loaded via context (lineage-matched)

# Override: explicit primary_dependency
- name: generate_report
  dependencies: [analyze_sentiment, analyze_entities, analyze_topics]
  primary_dependency: analyze_entities  # Override: analyze_entities is primary
```

**Aggregation** - merge and group by key:
```yaml
- name: aggregate_votes
  dependencies: [validator_a, validator_b, validator_c]
  reduce_key: content_id
```

## Cross-Workflow Dependencies

```yaml
actions:
  - name: process_upstream_data
    kind: tool
    impl: process_data
    dependencies:
      - workflow: upstream_workflow_name
        action: specific_action    # Optional
```

| Syntax | Description |
|--------|-------------|
| `action_name` | Single input source |
| `[{workflow: name}]` | Cross-workflow (all outputs) |
| `[{workflow: name, action: act}]` | Specific action from another workflow |

**Note:** Context dependencies (actions referenced in `context_scope` but not in `dependencies`) are auto-inferred via lineage matching.

## Guards

```yaml
guard:
  condition: "expression"
  on_false: "skip" | "filter"
```

**Comparison Operators:** `==`, `!=`, `>`, `>=`, `<`, `<=`

**Logical Operators:** `and`, `or`, `not`

**Advanced Operators:**
- `IN` / `NOT IN` - Membership check
- `CONTAINS` - String/list contains
- `LIKE` - Pattern matching
- `BETWEEN` - Range check
- `IS NULL` / `IS NOT NULL`

**Built-in Functions:** `len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`

```yaml
guard:
  condition: 'len(candidate_facts_list) >= 3 and status == "valid"'
  on_false: "filter"
```

## Supported Vendors

| Vendor | `model_vendor` | Example Models |
|--------|----------------|----------------|
| OpenAI | `openai` | gpt-4o, gpt-4o-mini |
| Anthropic | `anthropic` | claude-3-5-sonnet, claude-3-5-haiku |
| Google | `google` | gemini-1.5-pro, gemini-1.5-flash |
| Groq | `groq` | mixtral-8x7b, llama-3.1-70b |
| Mistral | `mistral` | mistral-large, mistral-medium |
| Cohere | `cohere` | command-r-plus |
| Ollama | `ollama` | llama3, mistral |

## Limiting Records and Files (Test Runs)

Cap processing for fast validation before full runs:

```yaml
defaults:
  file_limit: 3           # Walk at most 3 files per action

actions:
  - name: extract
    record_limit: 10      # Process 10 records per file (start nodes only)
```

- `record_limit` applies only at **start nodes** (initial data ingestion). Intermediate actions process whatever upstream produced.
- `file_limit` applies at **all stages** — directory walks, merged files, and storage backend reads.
- Both must be positive integers (`>= 1`). Omit or set to `null` for unlimited.
- Limits are stored in the status file. If you change limits between runs, the action automatically re-executes instead of being skipped.

**Typical testing workflow:**
1. Set `record_limit: 10` in your action config
2. Run and validate output
3. Remove `record_limit` and re-run for full processing

## Run Modes

**Online (Default):** Real-time, synchronous execution

**Batch:** Asynchronous batch API processing
- Up to 50% cost savings
- 24-hour processing window
- Supported: OpenAI, Anthropic, Google, Groq, Mistral

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `CLAUDE_API_KEY` | Anthropic Claude API key |
| `ANTHROPIC_API_KEY` | Alternative Anthropic key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `OLLAMA_HOST` | Ollama server URL |
| `AGENT_ACTIONS_DEBUG` | Enable debug mode (0/1) |
| `AGENT_ACTIONS_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) |

## Schema Types

| YAML Type | JSON Schema | Description |
|-----------|-------------|-------------|
| `string` | `{"type": "string"}` | Text value |
| `integer` | `{"type": "integer"}` | Whole number |
| `number` | `{"type": "number"}` | Decimal number |
| `boolean` | `{"type": "boolean"}` | true/false |
| `array` | `{"type": "array"}` | List of items |
| `object` | `{"type": "object"}` | Key-value pairs |

**Schema References:**
```yaml
schema: my_schema        # References schema/my_schema.yml - gets inlined during render
```

> Schema names are global -- reference by name only, never with a folder prefix. Use `schema: extract_claims`, not `schema: review_analyzer/extract_claims`.

**Inline Schemas:**
```yaml
schema:
  field1: string
  field2: number!        # ! marks required
  tags: array[string]    # Typed arrays
```

During the render step, all schemas are compiled:
- Named schemas (`schema: foo`) are loaded from `schema/foo.yml` and inlined
- Inline schemas (`{field: type}`) are expanded to unified format
- Use `agac render -a workflow` to see compiled output
