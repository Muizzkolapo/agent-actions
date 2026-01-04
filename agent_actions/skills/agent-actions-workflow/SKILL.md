---
name: agent-actions-workflow
description: Build, debug, and manage agent-actions workflows with YAML configs, UDF tools, and TypedDict schemas. Use when (1) creating new agent-actions workflows, (2) adding/modifying workflow actions, (3) creating UDF tool files with TypedDict schemas, (4) debugging schema validation errors, (5) tracing field flow between nodes, (6) understanding context_scope (observe/passthrough/drop), (7) configuring guards and conditional execution, (8) setting up cross-workflow dependencies, (9) using the agac CLI.
---

# Agent Actions Workflow Builder

Build production-ready agent-actions workflows with proper typing, context scoping, and tool integration.

## Quick Start

```bash
# Run a workflow
agac run -a my_workflow

# Run with upstream dependencies
agac run -a my_workflow --upstream

# Validate without executing
agac run -a my_workflow --validate-only

# Debug mode
agac run -a my_workflow --debug
```

## Project Structure

```
project/
├── agent_actions.yml           # Project config
├── agent_workflow/
│   └── my_workflow/
│       ├── agent_config/
│       │   └── my_workflow.yml # Workflow definition
│       ├── agent_io/
│       │   ├── source/         # Input data
│       │   └── target/         # Output per node
│       └── seed_data/          # Static reference data
├── prompt_store/               # Prompt templates
├── schema/                     # Output schemas
└── tools/                      # Python UDFs
```

## Configuration Hierarchy

```
agent_actions.yml (Project) → workflow.yml defaults → action fields
```

Higher specificity wins.

## Action Types

### LLM Action (default)

```yaml
- name: generate_explanation
  dependencies: [previous_action]
  intent: "Generate educational explanation"
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  schema: {
    explanation: string,
    key_points: array
  }
  prompt: $workflow_name.Prompt_Name
  json_mode: true
  prompt_debug: true
```

### Tool Action

```yaml
- name: process_data
  dependencies: [previous_action]
  kind: tool
  impl: function_name        # Must match @udf_tool function
  intent: "Process the data"
  granularity: record        # record | file
```

## Context Scope

Control field visibility between actions:

| Directive | In LLM Context | In Output | Use Case |
|-----------|----------------|-----------|----------|
| `observe` | Yes | No | LLM needs to see, but drop after |
| `passthrough` | No | Yes | Forward without LLM seeing |
| `drop` | No | No | Explicitly remove |

```yaml
context_scope:
  observe:
    - source.raw_content      # LLM sees, dropped after
  passthrough:
    - previous.field_a        # Forwarded to output
  drop:
    - previous.internal       # Removed
  seed_data:
    config: $file:config.json # Static reference data
```

See `references/context-scope-guide.md` for complete documentation.

## Guards

Filter or skip records conditionally:

```yaml
guard:
  condition: 'status == "KEEP"'
  on_false: "filter"         # filter | skip
```

**Operators:** `==`, `!=`, `>`, `<`, `>=`, `<=`, `and`, `or`, `not`, `IN`, `CONTAINS`, `LIKE`, `BETWEEN`, `IS NULL`

**Functions:** `len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`

```yaml
# Filter empty arrays
guard:
  condition: 'candidate_facts_list != []'
  on_false: "filter"

# Skip based on count
guard:
  condition: 'len(items) >= 3'
  on_false: "skip"
```

## Cross-Workflow Dependencies

```yaml
dependencies:
  - workflow: upstream_workflow
    action: final_action
```

Run with: `agac run -a downstream_workflow --upstream`

## Prompt Store

Define prompts in `prompt_store/workflow_name.md`:

```markdown
{prompt Extract_Facts}
Extract facts from: {{ source.page_content }}

Using syllabus: {{ seed.exam_syllabus.exam_name }}

{% for skill in seed.exam_syllabus.skills_measured %}
## {{ skill.skill_area }}
{% endfor %}
{end_prompt}
```

Reference: `prompt: $workflow_name.Extract_Facts`

## UDF Tool Pattern

```python
from typing import List, TypedDict
from agent_actions import udf_tool

class MyInput(TypedDict, total=False):
    """Source: node_N output, Destination: node_M output"""
    question: str
    options: List[str]

@udf_tool(input_type=MyInput)
def my_function(data: dict) -> dict:
    result = data.copy()
    result['processed'] = True
    return result
```

**Type Mapping:**

| JSON | Python | Notes |
|------|--------|-------|
| string | `str` | |
| integer | `int` | |
| array | `List[str]` or `List[Any]` | |
| object | `dict` | For mixed-type dicts |
| varies | `Any` | When type can change |

See `references/udf-decorator.md` for complete documentation.

## Common Errors

**"X was unexpected"** - Field in data but not in TypedDict
- Fix: Add field to TypedDict

**"X is not of type Y"** - Type mismatch
- Fix: Use correct type or `Any`

**Mixed-type dict error:**
```python
# BAD
target_counts: Dict[str, int]  # Fails if values include strings

# GOOD
target_counts: dict            # Allows any structure
```

## Type Consistency Across Actions (CRITICAL)

### What is an Action?

An **action** is a single step in a workflow that either:
- Calls an LLM with a prompt (LLM action)
- Runs a Python function (tool action)

Actions are defined in your workflow YAML and execute sequentially based on dependencies. Each action reads from upstream actions and writes to its output directory (`agent_io/target/node_<index>_<action_name>/`), where index starts at 0.

When a field flows through multiple actions, **ALL tools must use the same type**.

### Problem: Field Type Changes Mid-Pipeline

```
add_answer_text creates answer_text → generate_distractor_1 → ... → filter_questions uses answer_text
```

If `add_answer_text` outputs `List[str]` but `filter_questions`'s tool expects `str`, you get:
```
validation_error: ['item1', 'item2'] is not of type 'string'
schema_constraint: {'type': 'string'}
```

### Solution: Use Consistent Types

**BAD - Variable type:**
```python
# Some tools expect string, others list
answer_text: str                    # Tool A
answer_text: Union[str, List[str]]  # Tool B - Union doesn't work!
answer_text: Any                    # Tool C
```

**GOOD - Always use list:**
```python
# ALL tools use List[str]
answer_text: List[str]  # Even for single items: ["answer"]
```

### When Changing Field Types

1. **Update ALL downstream tools** that touch the field
2. **Fix existing data** in all action output directories:

```python
import json
import glob

# Each action writes to agent_io/target/node_<index>_<action_name>/
for json_file in glob.glob("agent_io/target/node_*/combined_scraped_sample.json"):
    with open(json_file, 'r') as f:
        data = json.load(f)

    for record in data:
        if 'content' in record and 'answer_text' in record['content']:
            val = record['content']['answer_text']
            if isinstance(val, str):
                record['content']['answer_text'] = [val]  # Convert to list

    with open(json_file, 'w') as f:
        json.dump(data, f, indent=4)
```

### Avoid Union Types

`Union[str, List[str]]` doesn't translate properly to JSON schema. Use:
- `List[str]` - Always a list (even single items)
- `Any` - When you truly need flexibility (less safe)

## Debugging

Enable debug mode for detailed tracebacks:

```bash
agac run -a my_workflow --debug --verbose
```

Common validation errors and fixes:

| Error | Cause | Fix |
|-------|-------|-----|
| `X is not of type 'string'` | Type mismatch | Convert in UDF or use `dict` |
| `X was unexpected` | Extra field | Add to TypedDict |
| `X is a required property` | Missing field | Ensure UDF returns it |

Use reprompting for auto-retry on schema failures:

```yaml
reprompt: smart  # Retry with LLM feedback
```

See `references/debugging-guide.md` for complete troubleshooting.

## Advanced Features

### Loop with Dynamic Schema

Generate multiple outputs with parameter expansion:

```yaml
- name: generate_distractor
  loop:
    param: stage
    range: [1, 2, 3]
    mode: sequential  # or parallel
  schema:
    distractor_${stage}: string           # → distractor_1, distractor_2
    explanation_${stage}: string
  prompt: $workflow.Generate_Distractor
  context_scope:
    observe:
      - generate_distractor_${stage-1}    # Previous iteration
```

### Reprompt Strategies

Auto-retry with increasing sophistication:

```yaml
- name: extract_facts
  reprompt: smart          # Presets: basic, smart, thorough
  # Or custom:
  reprompt:
    max_attempts: 5
    json_repair: true       # Fix brackets, commas, escapes
    use_llm_critique: true  # Analyze why validation failed
    critique_after_attempt: 2
```

| Preset | Attempts | JSON Repair | LLM Critique |
|--------|----------|-------------|--------------|
| `basic` | 3 | Yes | No |
| `smart` | 4 | Yes | After 2nd |
| `thorough` | 5 | Yes | After 1st + self-reflection |

### Granularity: File-Level Processing

Process all records at once (for aggregation, clustering, deduplication):

```yaml
- name: cluster_facts
  kind: tool
  impl: cluster_similar_facts
  granularity: file       # Default is "record"
```

```python
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult

@udf_tool(input_type=..., granularity=Granularity.FILE)
def cluster_similar_facts(data: List[Dict]) -> FileUDFResult:
    # Process ALL records together
    clusters = group_similar(data)
    return FileUDFResult(
        outputs=clusters,
        source_mapping=mapping,  # Track input → output lineage
        input_count=len(data)
    )
```

### Batch Mode (50% Cost Savings)

For 100+ records, use async batch API:

```yaml
defaults:
  run_mode: batch          # vs "online" (default)
```

```bash
# Submit batch
agac run -a my_workflow

# Check status
agac batch status --batch-id <id>

# Retrieve results
agac batch retrieve --batch-id <id> -o ./output

# Retry failed
agac batch retry --batch-id <id> --max-attempts 3
```

**Batch context note:** Data is at root level (not under `source`). Write mode-agnostic prompts:
```jinja2
{% if source is defined %}{{ source.field }}{% else %}{{ field }}{% endif %}
```

### Few-Shot Examples

Include examples from training data:

```yaml
- name: generate_question
  few_shot: 3              # Include 3 examples in prompt
```

### Resumable Execution

Re-running skips completed actions:

```bash
# First run fails at action 5
agac run -a my_workflow

# Fix the issue, re-run - actions 0-4 are skipped
agac run -a my_workflow
```

Status tracked in `agent_io/.agent_status.json`.

### Validation Commands

```bash
# Validate without executing
agac run -a my_workflow --validate-only

# Check UDF references
agac validate-udfs -a my_workflow -u ./tools

# Inspect field flow
agac inspect field-flow -a my_workflow

# Detect field conflicts
agac inspect conflicts -a my_workflow

# View rendered prompts (debugging)
agac render -a my_workflow
```

### Execution Metrics

Track in `artefact/runs.json`:

```json
{
  "workflow_name": "my_workflow",
  "total_runs": 15,
  "successful_runs": 14,
  "success_rate": 0.93,
  "total_tokens": 125000,
  "avg_duration_seconds": 45.2
}
```

### Operational Control

```yaml
- name: expensive_action
  is_operational: false    # Disable without removing
  max_execution_time: 600  # Timeout (seconds)
  enable_caching: true     # Cache responses
  temperature: 0.1         # LLM temperature
  max_tokens: 4000         # Response limit
```

## Resources

**Core References:**
- `references/yaml-schema.md` - Complete YAML configuration reference
- `references/context-scope-guide.md` - Context scope deep dive
- `references/udf-decorator.md` - UDF tool decorator reference
- `references/cli-reference.md` - CLI commands and options

**Pattern Guides:**
- `references/debugging-guide.md` - Error types and troubleshooting
- `references/prompt-patterns.md` - Effective prompt writing patterns
- `references/data-flow-patterns.md` - Node data flow and tracing

**Scripts:**
- `scripts/generate_typeddict.py` - Generate TypedDict from JSON
- `scripts/analyze_field_flow.py` - Trace fields across nodes
- `scripts/init_workflow.py` - Scaffold new workflow
