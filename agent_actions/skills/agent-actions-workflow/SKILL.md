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
│       │   ├── staging/        # Input data (base data to process)
│       │   └── target/         # Output per node (created by agac)
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

## Loop Execution

Execute actions multiple times with varying parameters:

```yaml
- name: generate_distractor
  loop:
    param: stage
    range: [1, 2, 3]
    mode: parallel  # or sequential
  schema:
    distractor_${stage}: string        # Dynamic: distractor_1, distractor_2, etc.
    explanation_${stage}: string
  prompt: |
    Generate distractor {{ loop.stage }} for the question.
```

**Loop Consumption:** Merge outputs from looped actions:

```yaml
- name: combine_distractors
  dependencies: [generate_distractor]
  loop_consumption:
    source: generate_distractor
    pattern: merge  # Combines all loop outputs
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

### Template Variable Prefixes

All context sources use **explicit namespacing** by design:

| Prefix | Source | Example |
|--------|--------|---------|
| `source.` | Input data from staging | `{{ source.title }}`, `{{ source.content }}` |
| `seed.` | Static reference data | `{{ seed.config.setting }}` |
| `<action_name>.` | Previous action output | `{{ classify.category }}`, `{{ validate.is_valid }}` |

### Why Explicit Namespacing (Design Principle)

Explicit namespacing is **required by design**, not a limitation:

| Benefit | Description |
|---------|-------------|
| **Clarity** | Always know where a field comes from |
| **No conflicts** | Multiple actions can output same field name |
| **Self-documenting** | Templates are readable without context |
| **Safe refactoring** | Rename actions without hidden breakage |
| **Easy debugging** | Trace fields to their source action |

```jinja2
{# CORRECT - explicit namespacing #}
{{ source.title }}                        {# from staging #}
{{ seed.exam_syllabus.exam_name }}        {# from seed_data #}
{{ classify_genre.primary_bisac_code }}   {# from classify_genre action #}
{{ generate_seo.primary_keywords }}       {# from generate_seo action #}

{# WRONG - implicit access not allowed #}
{{ title }}              {# Ambiguous: staging or action output? #}
{{ primary_keywords }}   {# Ambiguous: which action? #}
```

### Avoiding Field Name Conflicts

With explicit namespacing, actions can safely output the same field name:

```yaml
actions:
  - name: extract_entities
    schema: { count: integer }  # entity count

  - name: extract_keywords
    schema: { count: integer }  # keyword count

  - name: summarize
    dependencies: [extract_entities, extract_keywords]
    prompt: |
      Entity count: {{ extract_entities.count }}
      Keyword count: {{ extract_keywords.count }}
      {# No ambiguity - each 'count' is namespaced #}
```

## Workflow Patterns

Use these patterns for common parallel and merge scenarios:

| Pattern | Structure | Use Case |
|---------|-----------|----------|
| **Diamond/Fan-in** | split → parallel branches → merge | Enrich from multiple angles, combine results |
| **Multi-enrichment** | single source → parallel specialists → unified | Extract different aspects independently |
| **Ensemble/Voting** | same input → multiple LLMs → consensus | Compare model outputs, pick best |
| **Conditional Merge** | parallel with guards → merge available | Only merge branches that ran |

### Diamond/Fan-in Pattern

Split to parallel branches, merge all results:

```yaml
actions:
  - name: validate
    schema: { title: string, content: string }

  - name: generate_seo
    dependencies: [validate]
    schema: { primary_keywords: list }

  - name: generate_recommendations
    dependencies: [validate]
    schema: { similar_books: list }

  - name: assess_reading_level
    dependencies: [validate]
    schema: { reading_level: string }

  - name: score_quality
    dependencies: [generate_seo, generate_recommendations, assess_reading_level]
    # All 3 parallel parents accessible via namespacing:
    prompt: |
      SEO: {{ generate_seo.primary_keywords }}
      Similar: {{ generate_recommendations.similar_books }}
      Level: {{ assess_reading_level.reading_level }}
```

### Multi-enrichment Pattern

Multiple specialists extract different aspects:

```yaml
actions:
  - name: extract_entities
    dependencies: [prepare]
    schema: { entities: list, count: integer }

  - name: extract_sentiment
    dependencies: [prepare]
    schema: { sentiment: string, confidence: number }

  - name: extract_topics
    dependencies: [prepare]
    schema: { topics: list, count: integer }

  - name: unified_analysis
    dependencies: [extract_entities, extract_sentiment, extract_topics]
    prompt: |
      Entities: {{ extract_entities.entities }}
      Sentiment: {{ extract_sentiment.sentiment }}
      Topics: {{ extract_topics.topics }}
```

### Ensemble/Voting Pattern

Multiple LLMs, pick best answer:

```yaml
actions:
  - name: gpt4_answer
    dependencies: [prepare]
    model_vendor: openai
    model_name: gpt-4o

  - name: claude_answer
    dependencies: [prepare]
    model_vendor: anthropic
    model_name: claude-sonnet-4-20250514

  - name: best_answer
    dependencies: [gpt4_answer, claude_answer]
    prompt: |
      Compare and select the best answer:
      GPT-4: {{ gpt4_answer.response }}
      Claude: {{ claude_answer.response }}
```

### Conditional Merge Pattern

Merge only branches that ran (using guards):

```yaml
actions:
  - name: classify
    schema: { complexity: string }

  - name: fast_path
    dependencies: [classify]
    guard:
      condition: 'complexity == "low"'
      on_false: "skip"
    schema: { result: string }

  - name: slow_path
    dependencies: [classify]
    guard:
      condition: 'complexity == "high"'
      on_false: "skip"
    schema: { result: string }

  - name: combine
    dependencies: [fast_path, slow_path]
    # Handle potentially missing branches in prompt:
    prompt: |
      {% if fast_path %}Fast result: {{ fast_path.result }}{% endif %}
      {% if slow_path %}Slow result: {{ slow_path.result }}{% endif %}
```

### Chained Actions

Sequential dependency access:

```markdown
{prompt Second_Step}
## INPUT
Original data: {{ source.title }}
Previous result: {{ first_action.processed_field }}

## TASK
Build on the previous action's output.
{end_prompt}
```

## UDF Tool Pattern

```python
from typing import List, TypedDict
from agent_actions import udf_tool

class MyInput(TypedDict, total=False):
    """Source: node_N output, Destination: node_M output.

    Use total=False to make all fields optional.
    """
    question: str
    options: List[str]
    metadata: dict  # Passthrough fields

@udf_tool(input_type=MyInput)
def my_function(data: dict) -> dict:
    """Process data and return modified dict."""
    # Handle content wrapper if present
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Copy to avoid mutating input
    result = content.copy()

    # Add/modify fields
    result['processed'] = True
    result['result_value'] = content.get('question', '')[:50]

    return result
```

### Granularity Options

**Record (default):** Process one record at a time
```yaml
- name: filter_questions
  kind: tool
  impl: filter_by_score
  granularity: record
```

**File:** Process all records at once (for aggregation, dedup, clustering)
```python
from agent_actions.configuration.new_format_schema import Granularity

@udf_tool(input_type=DedupInput, granularity=Granularity.FILE)
def run_dedup(data: List[Dict]) -> List[Dict]:
    seen = set()
    return [r for r in data if r['fact'] not in seen and not seen.add(r['fact'])]
```

### FileUDFResult for Lineage

Track input→output mapping in FILE granularity:

```python
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult

@udf_tool(input_type=DedupInput, granularity=Granularity.FILE)
def dedup_with_lineage(data: List[Dict]) -> FileUDFResult:
    seen = {}
    outputs = []
    source_mapping = {}

    for idx, record in enumerate(data):
        fact = record['fact']
        if fact not in seen:
            seen[fact] = len(outputs)
            outputs.append(record)
            source_mapping[len(outputs) - 1] = idx

    return FileUDFResult(
        outputs=outputs,
        source_mapping=source_mapping,
        input_count=len(data)
    )
```

### Type Mapping

| JSON | Python | Notes |
|------|--------|-------|
| string | `str` | |
| integer | `int` | |
| number | `float` | |
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
