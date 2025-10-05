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

## Migration from Old Patterns

If you have existing workflows using old patterns, update them as follows:

### Old: `source_context{{}}`
```yaml
# ❌ Old
prompt: "Process source_context{{['page_content']}}"

# ✅ New
prompt: "Process {source.page_content}"
```

### Old: `return_collection[]`
```yaml
# ❌ Old (ambiguous source)
prompt: "Use return_collection[metrics]"

# ✅ New (explicit source)
prompt: "Use {extractor.metrics}"
depends_on: ["extractor"]
```

## See Also

- [Agents](/core-concepts/agents) - Agent configuration and dependencies
- [Workflows](/core-concepts/workflows) - Workflow structure and execution
- [Schemas](/core-concepts/schemas) - Output schema definitions
- [Sequential Loops](/examples/configurations/09-sequential-loops) - Loop execution examples
