---
title: Field Referencing
description: How to reference data in agent prompts using {reference.field} syntax
sidebar_position: 3
---

# Field Referencing in Prompts

Agent Actions uses a unified `{reference.field}` syntax for accessing data in agent prompts. This pattern provides clear, explicit references to workflow inputs, agent outputs, loop contexts, and workflow metadata.

## Overview

Field references allow you to dynamically insert data into agent prompts using a simple, consistent syntax:

```yaml
prompt: "Analyze {source.content} using metrics from {extractor.results}"
```

## Reference Types

### 1. Source References (`{source.*}`)

Access the original workflow input data using `{source.field}` syntax.

```yaml
agents:
  - name: "analyzer"
    prompt: |
      Analyze this document:

      Title: {source.title}
      Content: {source.page_content}
      Author: {source.metadata.author}
    depends_on: []
```

**When to use:**
- Access original input data provided to the workflow
- Reference fields from source documents or files
- Available to all agents in the workflow

### 2. Agent References (`{agent_name.field}`)

Access outputs from dependency agents that completed before the current agent.

```yaml
agents:
  - name: "extractor"
    prompt: "Extract key data from: {source.content}"
    output_schema:
      type: object
      properties:
        metrics:
          type: object
        summary:
          type: string
    depends_on: []

  - name: "analyzer"
    prompt: |
      Analyze these results:

      Metrics: {extractor.metrics}
      Summary: {extractor.summary}
    depends_on: ["extractor"]
```

**When to use:**
- Access outputs from agents listed in `depends_on`
- Chain agent outputs through workflow DAG
- Reference specific fields from dependency outputs

**Requirements:**
- Agent must be listed in `depends_on`
- Referenced agent must execute before current agent
- Field must exist in dependency's output

### 3. Nested Field Access (`{reference.nested.field}`)

Navigate nested object structures using dot notation.

```yaml
prompt: |
  Report these metrics:

  Accuracy: {analyzer.results.metrics.accuracy}
  Count: {analyzer.results.metrics.count}
  Environment: {workflow.config.environment}
```

**Examples:**
- `{extractor.data.items.count}` - 3 levels deep
- `{source.metadata.author.name}` - Access nested author name
- `{loop.item.analysis.sentiment}` - Nested loop item field

### 4. Array Index Access (`{reference.array.0}`)

Access specific array elements using numeric indices (0-based).

```yaml
prompt: |
  First item: {extractor.items.0}
  Second item: {extractor.items.1}
  Last metric: {analyzer.metrics.2}
```

**When to use:**
- Access specific positions in arrays
- Reference first/last elements
- Extract individual list items

### 5. Loop Context (`{loop.*}`)

Access loop iteration metadata and current item when agent executes within a loop.

```yaml
agents:
  - name: "review_analyzer"
    prompt: |
      [Processing Review {loop.index} of {loop.total}]

      Review Text: {loop.item.text}
      Rating: {loop.item.rating}
      Reviewer: {loop.item.author}

      Previous Analysis: {extractor.summary}
    loop:
      mode: "sequential"
      items_from: "{source.reviews}"
    depends_on: ["extractor"]
```

**Available loop references:**
- `{loop.index}` - Current iteration (0-based)
- `{loop.total}` - Total number of iterations
- `{loop.item}` - Current item being processed
- `{loop.item.field}` - Access fields in current item

**When to use:**
- Track progress through iterations
- Access current item in loop
- Include iteration context in prompts

### 6. Workflow Metadata (`{workflow.*}`)

Access workflow-level metadata and configuration.

```yaml
prompt: |
  [{workflow.name}] Processing in {workflow.config.environment}

  Workflow Version: {workflow.version}
  Run ID: {workflow.run_id}

  Analyzing: {source.content}
```

**Available workflow references:**
- `{workflow.name}` - Workflow name
- `{workflow.version}` - Workflow version
- `{workflow.run_id}` - Unique run identifier
- `{workflow.config.*}` - Workflow configuration fields

**When to use:**
- Include workflow context in outputs
- Track execution metadata
- Environment-specific prompts

## Complete Example

Here's a workflow demonstrating all reference types:

```yaml
name: "comprehensive_analysis"
version: "1.0.0"

agents:
  - name: "preprocessor"
    prompt: |
      Workflow: {workflow.name} v{workflow.version}

      Preprocess this document:
      Title: {source.title}
      Content: {source.page_content}
    depends_on: []

  - name: "extractor"
    prompt: |
      Extract data from preprocessed text:
      {preprocessor.cleaned_text}

      Focus on these topics: {source.metadata.topics.0}
    depends_on: ["preprocessor"]

  - name: "sentiment_analyzer"
    prompt: |
      [Run: {workflow.run_id}]
      Analyzing review {loop.index} of {loop.total}

      Review: {loop.item.text}
      Rating: {loop.item.rating}

      Previous patterns: {extractor.patterns}
      Confidence threshold: {extractor.config.threshold}
    loop:
      mode: "batch"
      items_from: "{source.reviews}"
    depends_on: ["extractor"]

  - name: "aggregator"
    prompt: |
      Aggregate sentiment analysis results:

      Extracted Patterns: {extractor.patterns}
      Analysis Results: {sentiment_analyzer.results}

      First sentiment: {sentiment_analyzer.results.0}
    depends_on: ["extractor", "sentiment_analyzer"]
```

## Value Serialization

Field references are automatically serialized based on type:

| Data Type | Serialization | Example |
|-----------|---------------|---------|
| String | Direct insertion | `"hello"` |
| Number | String conversion | `42`, `0.95` |
| Boolean | Lowercase string | `true`, `false` |
| Dict/Object | Pretty JSON | `{\n  "key": "value"\n}` |
| Array/List | Pretty JSON | `[\n  "item1",\n  "item2"\n]` |
| null | `"null"` | `null` |

## Error Handling

Field referencing provides clear error messages when references fail:

### Missing Reference
```yaml
prompt: "{unknown_agent.field}"
```
**Error:** `Reference 'unknown_agent' not found. Available: [source, extractor, analyzer]`

### Missing Field
```yaml
prompt: "{extractor.missing_field}"
```
**Error:** `Field 'missing_field' not found in 'extractor'`

### Missing Nested Field
```yaml
prompt: "{extractor.data.metrics.unknown}"
```
**Error:** `Field 'data.metrics.unknown' not found in 'extractor'`

### Array Index Out of Range
```yaml
prompt: "{extractor.items.99}"
```
**Error:** `Index 99 out of range for array in 'extractor.items' (length: 3)`

## Best Practices

### 1. Use Explicit References

**Good:**
```yaml
prompt: "Analyze {extractor.metrics} and {classifier.labels}"
```

**Bad:**
```yaml
prompt: "Analyze {metrics} and {labels}"  # Unclear source
```

### 2. Declare Dependencies

Always list agents you reference in `depends_on`:

```yaml
agents:
  - name: "reporter"
    prompt: "Report on {extractor.data} and {analyzer.results}"
    depends_on: ["extractor", "analyzer"]  # ✅ Both declared
```

### 3. Handle Optional Fields

Use conditional logic or default values in your schemas:

```yaml
output_schema:
  type: object
  properties:
    summary:
      type: string
      default: "No summary available"
```

### 4. Keep References Simple

Break complex nested access into intermediate agents:

**Good:**
```yaml
# Extractor outputs simplified structure
- name: "extractor"
  output_schema:
    properties:
      accuracy: { type: "number" }

# Analyzer uses simple reference
- name: "analyzer"
  prompt: "Accuracy: {extractor.accuracy}"
```

**Avoid:**
```yaml
# Overly nested reference
prompt: "Accuracy: {extractor.results.analysis.metrics.validation.accuracy}"
```

### 5. Document Field Contracts

Use schema descriptions to document available fields:

```yaml
output_schema:
  type: object
  properties:
    metrics:
      type: object
      description: "Performance metrics for downstream agents to reference"
      properties:
        accuracy:
          type: number
          description: "Reference via {agent_name.metrics.accuracy}"
```

## Using Functions in Prompts with `dispatch_task()`

You can call custom Python functions directly within your prompts using `dispatch_task()`. This allows you to execute custom logic, data transformations, or validations as part of prompt processing.

### Basic Syntax

```yaml
prompt: |
  Process this data:
  dispatch_task('function_name')
```

The syntax is intentionally simple:
- **Function name only** - No arguments passed
- **Receives context** - Function gets the same `context_data` as the LLM
- **Returns string** - Function output replaces the `dispatch_task()` call in the prompt

### Function Signature

Your functions must parse the `context_data` JSON string to access fields:

```python
# workflow_tools/my_function.py
import json

def my_function(context_data):
    """
    Process data from workflow context.

    Args:
        context_data: JSON string containing all available context

    Returns:
        String to insert into the prompt
    """
    # Parse the JSON string
    data = json.loads(context_data)

    # Access fields from the context
    content = data.get('content', '')
    title = data.get('title', '')

    # Process and return
    return f"Processed: {content.upper()}"
```

**Important:** The `context_data` parameter is a **JSON string**, not a dict. You must use `json.loads()` to parse it.

### Working with Field References

Field references (`{source.field}`, `{agent.field}`) are **replaced BEFORE** `dispatch_task()` is processed, so your functions always receive resolved values.

```yaml
agents:
  - name: analyzer
    prompt: |
      Title: {source.title}

      Analysis:
      dispatch_task('analyze_content')
    tools:
      path: "./workflow_tools"
```

```python
# workflow_tools/analyze_content.py
import json

def analyze_content(context_data):
    """Analyze content from context."""
    data = json.loads(context_data)

    # Access source fields
    content = data.get('content', '')
    title = data.get('title', 'Untitled')

    # Access dependency outputs (if available)
    extracted_keywords = data.get('keywords', '')

    return f"Analysis of '{title}': {len(content)} characters, keywords: {extracted_keywords}"
```

### Processing Order

Understanding the processing order is crucial:

1. **Field references** (`{reference.field}`) are replaced first
2. **dispatch_task()** functions are called with resolved context
3. **LLM** receives the final prompt with all replacements

This ensures functions always receive actual values, never placeholder strings.

### Multiple Function Calls

You can call multiple functions in a single prompt:

```yaml
prompt: |
  Summary: dispatch_task('generate_summary')

  Keywords: dispatch_task('extract_keywords')

  Sentiment: dispatch_task('analyze_sentiment')
```

Each function receives the same `context_data` context.

### Accessing Dependency Outputs

Functions can access outputs from dependency agents through the context:

```yaml
agents:
  - name: extractor
    prompt: "Extract data from {source.content}"
    schema:
      fields:
        - name: metrics
          type: object
    depends_on: []

  - name: analyzer
    prompt: |
      Analysis: dispatch_task('create_report')
    depends_on: ["extractor"]
    tools:
      path: "./workflow_tools"
```

```python
# workflow_tools/create_report.py
import json

def create_report(context_data):
    """Create report using dependency outputs."""
    data = json.loads(context_data)

    # Access source data
    content = data.get('content', '')

    # Access dependency outputs (flattened into context)
    metrics = data.get('metrics', {})

    return f"Report: {len(content)} chars, metrics: {metrics}"
```

### Configuration

Functions are loaded from the `tools.path` directory specified in your agent config:

```yaml
agents:
  - name: my_agent
    prompt: "dispatch_task('my_function')"
    tools:
      path: "./workflow_tools"  # Directory containing your functions
```

### Complete Example

```yaml
# workflow.yml
settings:
  workflow_name: "document_analysis"

source:
  file_path: "documents.jsonl"
  # Format: {"content": "...", "title": "...", "category": "..."}

agents:
  - name: extract_keywords
    model_vendor: "tool"
    prompt: |
      Extract keywords:
      dispatch_task('extract_keywords')
    tools:
      path: "./workflow_tools"
    schema:
      fields:
        - name: keywords
          type: string
    granularity: record

  - name: create_summary
    model_vendor: "tool"
    prompt: |
      Title: {source.title}
      Keywords: {extract_keywords.keywords}

      Summary:
      dispatch_task('generate_summary')
    dependencies:
      - extract_keywords
    tools:
      path: "./workflow_tools"
    schema:
      fields:
        - name: summary
          type: string
    granularity: record
```

```python
# workflow_tools/extract_keywords.py
import json

def extract_keywords(context_data):
    """Extract keywords from document."""
    data = json.loads(context_data)
    content = data.get('content', '')

    # Simple keyword extraction
    words = content.lower().split()
    keywords = [w for w in words if len(w) > 5]
    return ", ".join(keywords[:5])
```

```python
# workflow_tools/generate_summary.py
import json

def generate_summary(context_data):
    """Generate summary using all available context."""
    data = json.loads(context_data)

    title = data.get('title', 'Untitled')
    content = data.get('content', '')
    keywords = data.get('keywords', '')  # From dependency

    summary = f"{title}: {content[:100]}... (Keywords: {keywords})"
    return summary
```

### Error Handling

If a function doesn't exist or returns `None`, you'll see an error:

```yaml
prompt: "dispatch_task('nonexistent_function')"
```
**Error:** `No module named 'nonexistent_function'` or similar import error.

```python
def my_function(context_data):
    return None  # Returns None
```
**Error in prompt:** `Error: No valid return from function.`

### Best Practices

1. **Always parse context_data** - Use `json.loads()` to convert the JSON string to a dict
2. **Handle missing fields** - Use `.get()` with defaults to avoid KeyError
3. **Return strings** - Functions should return string values for prompt insertion
4. **Keep functions focused** - Each function should do one thing well
5. **Use field references** - Let the system resolve references before dispatch

## Context Scope Control

The `context_scope` configuration provides granular control over how upstream fields flow through your agents. It allows you to specify which fields go to the LLM as context, which are blocked entirely, and which bypass the LLM to go directly to the output.

### Why Context Scope?

Without `context_scope`, all referenced fields must be included in the prompt. This creates challenges:

- **Large Reference Data**: Cannot send 50KB reference tables to LLM without bloating the prompt
- **Security**: No way to block sensitive data (API keys, credentials) from reaching the LLM
- **Lineage Tracking**: Must manually use `observe` to carry IDs through multi-stage pipelines

Context scope solves these problems with three directives: `observe`, `drop`, and `passthrough`.

### The Three Directives

#### 1. Observe - LLM Context Only

Send fields to the LLM as additional context without including them in the prompt or output.

```yaml
agents:
  - name: "researcher"
    prompt: "Research this topic: {source.topic}"
    schema:
      summary: string
      key_findings: array
      reference_tables: object  # 50KB of lookup data

  - name: "analyzer"
    prompt: |
      Analyze these findings:
      {researcher.summary}

    context_scope:
      observe:
        - researcher.reference_tables  # Sent to LLM, not in prompt or output

    schema:
      analysis: string
      confidence: number
```

**What happens:**
- `reference_tables` formatted and appended to the prompt before sending to LLM
- LLM sees the reference data for accurate analysis
- Output contains only `analysis` and `confidence` (not reference_tables)
- Prompt stays clean and focused

**Use cases:**
- Large reference tables or lookup dictionaries
- Historical context for LLM decision-making
- Metadata that influences analysis but isn't needed in output

#### 2. Drop - Block from LLM

Block sensitive fields from reaching the LLM entirely (security/privacy).

```yaml
agents:
  - name: "data_collector"
    prompt: "Collect data from API"
    schema:
      collected_data: array
      api_credentials: object
      internal_system_id: string

  - name: "public_analyzer"
    prompt: "Analyze: {data_collector.collected_data}"

    context_scope:
      drop:
        - data_collector.api_credentials
        - data_collector.internal_system_id
        - source.api_key

    schema:
      analysis: string
```

**What happens:**
- Dropped fields removed from field context
- Cannot reference them in prompt (e.g., `{data_collector.api_credentials}` would error)
- LLM never sees the data
- Not in final output

**Use cases:**
- API keys, credentials, tokens
- PII (personally identifiable information)
- Internal metadata
- Compliance requirements

#### 3. Passthrough - Output Only

Merge fields into the current action's output without sending them to the LLM.

```yaml
agents:
  - name: "fact_extractor"
    prompt: "Extract facts from: {source.content}"
    schema:
      facts: array
      document_id: string
      original_filename: string

  - name: "classifier"
    prompt: "Classify these facts: {fact_extractor.facts}"

    context_scope:
      passthrough:
        - fact_extractor.document_id
        - fact_extractor.original_filename

    schema:
      classification: string
      confidence: number
```

**What happens:**
- Passthrough fields removed from field context
- Cannot reference them in prompt
- LLM never sees them
- After LLM generates response, fields merged into output
- Next agent can reference them: `{classifier.document_id}`

**Final output:**
```json
{
  "classification": "positive",
  "confidence": 0.92,
  "document_id": "doc-123",
  "original_filename": "report.pdf"
}
```

**Use cases:**
- Lineage tracking (document_id, source_id)
- Metadata that flows through pipeline
- IDs for downstream correlation
- Timestamps, filenames, tags

### Using All Three Together

Combine directives for complete control over field flow:

```yaml
agents:
  - name: "advanced_analyzer"
    prompt: "Analyze: {extractor.summary}"

    context_scope:
      observe:
        - enricher.reference_database    # To LLM context
        - enricher.historical_statistics  # To LLM context

      drop:
        - source.api_credentials  # Block from LLM
        - extractor.internal_metadata  # Block from LLM

      passthrough:
        - extractor.document_id      # To output only
        - source.original_filename    # To output only

    schema:
      analysis: string
      confidence: number
```

**Result:**
- **Prompt:** Clean and focused (`{extractor.summary}`)
- **LLM Context:** Reference database + historical statistics (for accurate analysis)
- **LLM Never Sees:** API credentials, internal metadata (security)
- **Output:** `analysis`, `confidence`, `document_id`, `original_filename`

### Comparison with Observe and Drops

| Feature | Syntax | Purpose | LLM Sees It? |
|---------|--------|---------|--------------|
| **observe** | `observe: [field]` | Copy flat field to output | Yes, if in context |
| **drops** | `drops: [field]` | Remove from output | Yes, can be in prompt/context |
| **context_scope.observe** | `observe: [action.field]` | Send to LLM context only | Yes (context), not in prompt/output |
| **context_scope.drop** | `drop: [action.field]` | Block entirely | No (security) |
| **context_scope.passthrough** | `passthrough: [action.field]` | Merge to output only | No |

**Key differences:**
- `observe` works with flat fields from immediate predecessor
- `context_scope` uses `{action.field}` syntax for explicit references
- `context_scope.passthrough` can reference ANY upstream action (via historical nodes)
- `context_scope.drop` provides security guarantee (LLM never sees data)

### Output Formula

Without context_scope:
```
Final Output = (schema_fields + observe) - drops
```

With context_scope:
```
Final Output = (schema_fields + observe + passthrough) - drops
```

### Best Practices

#### 1. Security First

Always drop sensitive data:
```yaml
context_scope:
  drop:
    - source.api_key
    - collector.credentials
    - processor.internal_ids
```

#### 2. Large Reference Data

Use `observe` for large lookup data:
```yaml
context_scope:
  observe:
    - researcher.reference_tables  # 50KB lookup data
```

#### 3. Lineage Tracking

Use `passthrough` instead of manual `observe`:
```yaml
# Good - Explicit source
context_scope:
  passthrough:
    - extractor.document_id

# Less clear - Which action's document_id?
observe: [document_id]
```

#### 4. Combine with Field References

`context_scope` works seamlessly with existing field referencing:
```yaml
prompt: |
  Analyze {extractor.summary} considering:
  - Metrics: {analyzer.metrics}
  - Patterns: {classifier.patterns}

context_scope:
  observe: [analyzer.raw_data]
  passthrough: [extractor.doc_id]
```

### Backward Compatibility

Workflows without `context_scope` work unchanged:
- No `context_scope` → empty dicts passed internally
- Existing field references work normally
- No breaking changes

## See Also

- [Agents](/core-concepts/agents) - Agent configuration and dependencies
- [Workflows](/core-concepts/workflows) - Workflow structure and execution
- [Schemas](/core-concepts/schemas) - Output schema definitions
- [Sequential Loops](/examples/configurations/09-sequential-loops) - Loop execution examples
