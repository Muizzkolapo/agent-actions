---
title: Workflows
description: Master DAG-based workflow orchestration and execution patterns
sidebar_position: 2
---

# Workflows

Workflows in Agent Actions orchestrate multiple agents in **Directed Acyclic Graph (DAG) patterns**. They define how agents interact, manage data flow, and coordinate execution to achieve complex processing goals.

## What Are DAG Workflows?

### Directed Acyclic Graphs
DAG workflows provide structure through:

- **Directed**: Data flows in specific directions between agents
- **Acyclic**: No circular dependencies (prevents infinite loops)
- **Graph**: Agents (nodes) connected by dependencies (edges)

### Benefits of DAG Structure

- **Explicit Dependencies**: Clear relationships between processing steps
- **Parallel Execution**: Independent agents run simultaneously
- **Deterministic Order**: Execution sequence is always predictable
- **Visual Clarity**: Easy to understand and debug workflows

## Workflow Configuration

### Basic Workflow Structure

```yaml
workflow_name: "document_processing_pipeline"
description: "Process documents through analysis and summarization"

# Schema definitions
schemas:
  extracted_data: "./schemas/extracted.json"
  analysis_result: "./schemas/analysis.json"
  final_summary: "./schemas/summary.json"

# Agent definitions
agents:
  - name: "extractor"
    model_vendor: "openai"
    model_name: "gpt-4"
    output_schema: "extracted_data"
    depends_on: []

  - name: "analyzer"
    model_vendor: "openai"
    model_name: "gpt-4"
    output_schema: "analysis_result"
    depends_on: ["extractor"]

  - name: "summarizer"
    model_vendor: "openai"
    model_name: "gpt-4"
    output_schema: "final_summary"
    depends_on: ["analyzer"]

# Workflow execution
workflow:
  input_data:
    document: "Document content to process..."
  agents: ["extractor", "analyzer", "summarizer"]
```

### Workflow Properties

| Property | Required | Description |
|----------|----------|-------------|
| `workflow_name` | Yes | Unique identifier for the workflow |
| `description` | No | Human-readable workflow description |
| `schemas` | Yes | JSON schema definitions for validation |
| `agents` | Yes | List of agent configurations |
| `workflow.input_data` | Yes | Initial input data for the workflow |
| `workflow.agents` | Yes | Ordered list of agents to execute |

## DAG Execution Patterns

### Linear Pipeline

Sequential processing where each agent depends on the previous:

```yaml
# Linear: A → B → C → D
agents:
  - name: "step_a"
    depends_on: []
  - name: "step_b"
    depends_on: ["step_a"]
  - name: "step_c"
    depends_on: ["step_b"]
  - name: "step_d"
    depends_on: ["step_c"]
```

**Use Cases**: Document processing, data transformation pipelines, sequential analysis

### Fan-Out Pattern

One agent feeds multiple parallel processors:

```yaml
# Fan-out: A → [B, C, D] → E
agents:
  - name: "splitter"
    depends_on: []

  # Parallel processing
  - name: "process_sentiment"
    depends_on: ["splitter"]
  - name: "process_entities"
    depends_on: ["splitter"]
  - name: "process_topics"
    depends_on: ["splitter"]

  # Merge results
  - name: "merger"
    depends_on: ["process_sentiment", "process_entities", "process_topics"]
```

**Use Cases**: Multi-aspect analysis, parallel feature extraction, distributed processing

### Diamond Pattern

Complex branching with multiple convergence points:

```yaml
# Diamond: A → [B, C] → [D, E] → F
agents:
  - name: "root"
    depends_on: []

  # First level branches
  - name: "branch_left"
    depends_on: ["root"]
  - name: "branch_right"
    depends_on: ["root"]

  # Second level processing
  - name: "process_left"
    depends_on: ["branch_left"]
  - name: "process_right"
    depends_on: ["branch_right"]

  # Final convergence
  - name: "final_merger"
    depends_on: ["process_left", "process_right"]
```

**Use Cases**: Complex analysis workflows, multi-stage validation, comparison tasks

### Tree Structure

Hierarchical processing with multiple levels:

```yaml
# Tree: A → [B, C] → [D, E, F, G] → H
agents:
  - name: "root_analyzer"
    depends_on: []

  # Level 2
  - name: "content_processor"
    depends_on: ["root_analyzer"]
  - name: "metadata_processor"
    depends_on: ["root_analyzer"]

  # Level 3
  - name: "text_analyzer"
    depends_on: ["content_processor"]
  - name: "image_analyzer"
    depends_on: ["content_processor"]
  - name: "author_analyzer"
    depends_on: ["metadata_processor"]
  - name: "date_analyzer"
    depends_on: ["metadata_processor"]

  # Final report
  - name: "comprehensive_report"
    depends_on: ["text_analyzer", "image_analyzer", "author_analyzer", "date_analyzer"]
```

**Use Cases**: Hierarchical analysis, multi-modal processing, detailed reporting

## Data Flow Management

### Input Distribution

Control how workflow input reaches different agents:

```yaml
workflow:
  input_data:
    primary_document: "Main content..."
    user_preferences: {"style": "formal", "length": "brief"}
    metadata: {"source": "api", "timestamp": "2024-01-01"}

agents:
  - name: "content_analyzer"
    prompt: |
      Analyze this document: {primary_document}
      Consider user preferences: {user_preferences}
    depends_on: []

  - name: "metadata_enricher"
    prompt: |
      Enrich metadata: {metadata}
      Based on content analysis: {content_analyzer.output}
    depends_on: ["content_analyzer"]
```

### Inter-Agent Communication

Agents communicate through structured outputs:

```yaml
agents:
  - name: "data_extractor"
    output_schema: "extracted_data"
    prompt: "Extract structured data from: {input_document}"
    depends_on: []

  - name: "quality_assessor"
    output_schema: "quality_report"
    prompt: |
      Assess data quality:
      Extracted Data: {data_extractor.output}

      Rate completeness, accuracy, and consistency.
    depends_on: ["data_extractor"]

  - name: "report_generator"
    output_schema: "final_report"
    prompt: |
      Generate comprehensive report:
      Raw Data: {data_extractor.output}
      Quality Assessment: {quality_assessor.output}
    depends_on: ["data_extractor", "quality_assessor"]
```

### Output Aggregation

Collect and structure final workflow results:

```yaml
workflow:
  output_format: "comprehensive_analysis"
  final_schema: "./schemas/workflow_output.json"

# The workflow automatically aggregates all agent outputs:
# {
#   "data_extractor": {...},
#   "quality_assessor": {...},
#   "report_generator": {...}
# }
```

### Field-Level Data Flow Control

Control precisely which fields are exposed to the LLM and which appear in the output using `drops` and `observe`:

#### `drops` - Hide from LLM and Output

Fields in `drops` are:
- **Excluded from the LLM prompt** (not visible to the model)
- **Removed from the action's output** (not passed to next actions)

Use `drops` for:
- Sensitive internal metadata
- Temporary processing fields
- Fields that should not propagate

```yaml
actions:
  - name: extract_facts
    schema: candidate_facts_list
    drops: [id, url, internal_metadata]
    # id, url, internal_metadata won't be sent to LLM
    # and won't appear in output
    prompt: $fact_extraction
```

#### `observe` - Hide from LLM, Pass to Output

Fields in `observe` are:
- **Excluded from the LLM prompt** (not visible to the model)
- **Included in the action's output** (passed through to next actions)

Use `observe` for:
- Context fields needed downstream but not for processing
- Passthrough metadata
- Correlation IDs and tracking information

```yaml
actions:
  - name: classify_content
    schema: {content_type: string, confidence: number}
    observe: [document_id, timestamp, source_url]
    # document_id, timestamp, source_url hidden from LLM
    # but passed through to output for next actions
    prompt: "Classify the content type"
```

#### Schema Defines Output Fields

The `schema` field defines what the LLM **generates**:

```yaml
actions:
  - name: analyze_sentiment
    schema: {sentiment: string, score: number}
    observe: [user_id, session_id]
    drops: [temp_token_count]
```

**Data Flow:**
1. **Input**: Contains all fields from previous action
2. **LLM Prompt**: Excludes `observe` and `drops` fields
3. **LLM Output**: Only fields defined in `schema`
4. **Action Output**: `schema` fields + `observe` fields (passthrough)

#### Complete Example

```yaml
actions:
  - name: extract_entities
    intent: "Extract named entities from text"
    schema: entity_list
    drops: [page_metadata, processing_flags]
    observe: [document_id, created_at, source_type]
    prompt: |
      Extract all named entities from the following text.
      Return a structured list of entities with their types.

  - name: classify_entities
    intent: "Classify extracted entities by category"
    schema: entity_classification
    observe: [document_id, created_at]  # Still available from previous action
    drops: [source_type]  # No longer needed
    prompt: |
      Classify the following entities into categories.
      Entities: {entity_list}
      # document_id, created_at not visible here
      # but will be in output
```

**Key Benefits:**
- ✅ **Reduce prompt size** by excluding unnecessary fields
- ✅ **Preserve context** for downstream actions with `observe`
- ✅ **Clean up** temporary data with `drops`
- ✅ **Explicit control** over what LLM sees vs what propagates

#### Using Defaults for Common Fields

Both `drops` and `observe` can be defined in workflow `defaults` to apply across all actions:

```yaml
defaults:
  vendor: openai
  model: gpt-4o-mini
  drops: [internal_id, temp_metadata]     # Applied to all actions
  observe: [user_id, request_id, timestamp]  # Applied to all actions

actions:
  - name: action1
    schema: {output: string}
    # Inherits: drops=[internal_id, temp_metadata]
    #           observe=[user_id, request_id, timestamp]
    prompt: "Process data"

  - name: action2
    schema: {output: string}
    drops: [different_field]              # Overrides defaults
    observe: [correlation_id]             # Overrides defaults
    prompt: "Process more data"
```

**Inheritance Rules:**
- Actions **inherit** `drops` and `observe` from defaults
- Action-level values **completely override** defaults (no merging)
- Same pattern as other default fields (`vendor`, `model`, `json_mode`, etc.)

:::info Migration Note
**Deprecated: `reads` and `writes` fields**

Previous versions included `reads` and `writes` fields in action configuration. These are now **deprecated** and should be removed:

- ❌ **`reads`**: No longer needed - all input fields are automatically available
- ❌ **`writes`**: Replaced by `schema` - which defines LLM output fields

**Before (Deprecated):**
```yaml
actions:
  - name: analyze
    reads: [text, metadata]
    writes: [sentiment, score]
    drops: [temp_data]
```

**After (Current):**
```yaml
actions:
  - name: analyze
    schema: {sentiment: string, score: number}
    drops: [temp_data]
```

The `schema` field now fully replaces `writes` by defining what the LLM generates, while all input fields are implicitly available unless excluded via `drops` or `observe`.
:::

## Execution Control

### Parallel Optimization

Agent Actions automatically parallelizes independent agents:

```yaml
# These will run in parallel (no interdependencies)
agents:
  - name: "sentiment_analyzer"
    depends_on: ["input_processor"]
  - name: "entity_extractor"
    depends_on: ["input_processor"]
  - name: "topic_classifier"
    depends_on: ["input_processor"]
  - name: "style_analyzer"
    depends_on: ["input_processor"]
```

### Dependency Resolution

Execution order is automatically determined:

```yaml
# Execution order: preprocessor → [analyzer_a, analyzer_b] → combiner
agents:
  - name: "combiner"
    depends_on: ["analyzer_a", "analyzer_b"]
  - name: "analyzer_a"
    depends_on: ["preprocessor"]
  - name: "preprocessor"
    depends_on: []
  - name: "analyzer_b"
    depends_on: ["preprocessor"]

# Agent Actions resolves to: preprocessor, then analyzer_a + analyzer_b in parallel, then combiner
```

### Error Propagation

When an agent fails, dependent agents are skipped:

```yaml
agents:
  - name: "step_1"
    depends_on: []          # ✅ Executes
  - name: "step_2"
    depends_on: ["step_1"]  # ❌ Fails (schema validation error)
  - name: "step_3"
    depends_on: ["step_2"]  # ⏭️ Skipped (dependency failed)
  - name: "step_4"
    depends_on: ["step_1"]  # ✅ Executes (independent path)
```

## Advanced Patterns

### Conditional Processing

Implement branching logic through agent design:

```yaml
agents:
  - name: "content_classifier"
    output_schema: "classification"
    prompt: |
      Classify content type: {input_content}
      Return: {"type": "news|blog|academic|social", "confidence": 0.0-1.0}
    depends_on: []

  - name: "news_processor"
    prompt: |
      {% if content_classifier.type == "news" %}
      Process as news article: {input_content}
      {% else %}
      Skip processing - not news content
      {% endif %}
    depends_on: ["content_classifier"]

  - name: "blog_processor"
    prompt: |
      {% if content_classifier.type == "blog" %}
      Process as blog post: {input_content}
      {% else %}
      Skip processing - not blog content
      {% endif %}
    depends_on: ["content_classifier"]
```

### Quality Assurance Chains

Implement validation and refinement loops:

```yaml
agents:
  - name: "initial_generator"
    output_schema: "generated_content"
    depends_on: []

  - name: "quality_checker"
    output_schema: "quality_assessment"
    prompt: |
      Assess quality of: {initial_generator.output}
      Check grammar, factual accuracy, completeness.
    depends_on: ["initial_generator"]

  - name: "content_refiner"
    output_schema: "refined_content"
    prompt: |
      Refine content based on quality assessment:
      Original: {initial_generator.output}
      Issues Found: {quality_checker.issues}
      Suggestions: {quality_checker.suggestions}
    depends_on: ["initial_generator", "quality_checker"]
```

### Multi-Modal Processing

Handle different content types in parallel:

```yaml
agents:
  - name: "content_splitter"
    output_schema: "content_parts"
    prompt: "Identify and separate text, images, tables from: {multimodal_input}"
    depends_on: []

  - name: "text_processor"
    output_schema: "text_analysis"
    prompt: "Analyze text content: {content_splitter.text_parts}"
    depends_on: ["content_splitter"]

  - name: "image_processor"
    output_schema: "image_analysis"
    prompt: "Analyze images: {content_splitter.image_parts}"
    depends_on: ["content_splitter"]

  - name: "table_processor"
    output_schema: "table_analysis"
    prompt: "Analyze tables: {content_splitter.table_parts}"
    depends_on: ["content_splitter"]

  - name: "multimodal_synthesizer"
    output_schema: "comprehensive_analysis"
    prompt: |
      Synthesize multi-modal analysis:
      Text: {text_processor.output}
      Images: {image_processor.output}
      Tables: {table_processor.output}
    depends_on: ["text_processor", "image_processor", "table_processor"]
```

## Workflow Testing

### Unit Testing Agents

Test individual agents with mock inputs:

```yaml
# Test configuration
test_workflow:
  test_cases:
    - agent: "sentiment_analyzer"
      input_data:
        text: "I love this product!"
      expected_output:
        sentiment: "positive"
        confidence: 0.95
```

### Integration Testing

Test complete workflow paths:

```yaml
# Integration test
integration_test:
  workflow: "document_analysis"
  test_data: "./test_data/sample_document.txt"
  assertions:
    - path: "extractor.entities"
      contains: ["person", "organization"]
    - path: "analyzer.sentiment"
      equals: "positive"
```

## Performance Optimization

### Minimize Dependencies

Reduce unnecessary dependencies for better parallelization:

```yaml
# Poor - unnecessary sequential processing
agents:
  - name: "step_1"
    depends_on: []
  - name: "step_2"
    depends_on: ["step_1"]  # Not actually needed
  - name: "step_3"
    depends_on: ["step_2"]  # Not actually needed

# Better - parallel processing
agents:
  - name: "step_1"
    depends_on: []
  - name: "step_2"
    depends_on: []  # Can run in parallel
  - name: "step_3"
    depends_on: []  # Can run in parallel
```

### Efficient Data Passing

Pass only necessary data between agents:

```yaml
agents:
  - name: "large_processor"
    output_schema: "large_dataset"
    depends_on: []

  - name: "summary_generator"
    prompt: |
      Generate summary from key points:
      Key Points: {large_processor.key_points}
      # Don't pass entire large dataset
    depends_on: ["large_processor"]
```

## Best Practices

### 1. Design for Clarity
Make workflows easy to understand:

```yaml
# Clear workflow structure
workflow_name: "customer_feedback_analysis"
description: "Analyze customer feedback through sentiment, topic, and trend analysis"

agents:
  - name: "feedback_preprocessor"
  - name: "sentiment_analyzer"
  - name: "topic_extractor"
  - name: "trend_analyzer"
  - name: "insight_generator"
```

### 2. Minimize Coupling
Keep agents loosely coupled:

```yaml
# Good - agents have clear interfaces
- name: "data_validator"
  output_schema: "validation_result"

- name: "data_processor"
  prompt: "Process data if valid: {data_validator.is_valid}"
  depends_on: ["data_validator"]
```

### 3. Handle Errors Gracefully
Design workflows to handle failures:

```yaml
- name: "error_handler"
  prompt: |
    {% if previous_agent.status == "failed" %}
    Handle error: {previous_agent.error}
    {% else %}
    Process normal result: {previous_agent.output}
    {% endif %}
```

### 4. Document Dependencies
Make dependencies explicit and well-documented:

```yaml
- name: "report_generator"
  description: "Generates final report combining all analysis results"
  depends_on: [
    "sentiment_analyzer",    # Provides emotional context
    "entity_extractor",      # Provides key entities
    "trend_analyzer"         # Provides trend insights
  ]
```

## Next Steps

- **[Schema Validation](./schemas.md)** - Design robust JSON schemas
- **Examples** (coming soon) - Real-world workflow patterns
- **Performance Guide** (coming soon) - Optimize workflow execution