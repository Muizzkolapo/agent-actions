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
  model_vendor: openai
  model_name: gpt-4o-mini
  drops: [internal_id, temp_metadata]     # Applied to all actions
  observe: [user_id, request_id, timestamp]  # Applied to all actions

actions:
  - name: action1
    schema: {output: string}
    # Uses defaults: drops=[internal_id, temp_metadata]
    #                observe=[user_id, request_id, timestamp]
    prompt: "Process data"

  - name: action2
    schema: {output: string}
    drops: [different_field]              # Extends defaults
    observe: [correlation_id]             # Extends defaults
    prompt: "Process more data"
    # Final result: drops=[internal_id, temp_metadata, different_field]
    #               observe=[user_id, request_id, timestamp, correlation_id]

  - name: action3
    schema: {output: string}
    drops: [internal_id, special_field]   # Extends with deduplication
    observe: [user_id, session_id]        # Extends with deduplication
    prompt: "Process final data"
    # Final result: drops=[internal_id, temp_metadata, special_field]
    #               observe=[user_id, request_id, timestamp, session_id]
```

**Inheritance Rules:**
- Actions **inherit** `drops` and `observe` from defaults
- Action-level values are **additive** - they extend defaults rather than replace them
- Duplicate fields are automatically removed (first occurrence preserved)
- Order is preserved: defaults first, then unique action-level additions
- Other default fields (`vendor`, `model`, `json_mode`, etc.) still follow replacement behavior

#### Benefits of Additive Behavior

The additive approach for `drops` and `observe` provides significant advantages:

**🎯 Composability**: Build workflows by incrementally adding field controls
```yaml
defaults:
  observe: [id, url, platform_name, exam_name]  # Core tracking fields
  drops: [temp_metadata, processing_flags]      # Common noise

actions:
  - name: extract_facts
    observe: [page_content, bloom_details]      # Add domain-specific context
    drops: [topic]                              # Add action-specific exclusion
    # Result: observe=[id, url, platform_name, exam_name, page_content, bloom_details]
    #         drops=[temp_metadata, processing_flags, topic]
```

**📝 Maintainability**: Define common patterns once, extend only where needed
```yaml
# Educational content workflow
defaults:
  observe: [document_id, source_platform, exam_type]
  drops: [raw_html, debug_info]

actions:
  - name: extract_questions    # Uses defaults + specific additions
    observe: [question_metadata]

  - name: generate_answers     # Uses defaults + different additions
    observe: [answer_context]

  - name: validate_quality     # Uses only defaults
    # No additional drops/observe needed
```

**🔄 Migration Friendly**: Easy to refactor existing workflows
```yaml
# Before: Each action had full field lists
actions:
  - name: action1
    drops: [temp_data, debug_info, action1_specific]
    observe: [id, url, platform, action1_metadata]

  - name: action2
    drops: [temp_data, debug_info, action2_specific]
    observe: [id, url, platform, action2_metadata]

# After: Extract common patterns to defaults
defaults:
  drops: [temp_data, debug_info]
  observe: [id, url, platform]

actions:
  - name: action1
    drops: [action1_specific]     # Only unique additions
    observe: [action1_metadata]

  - name: action2
    drops: [action2_specific]     # Only unique additions
    observe: [action2_metadata]
```

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

### Parallel Execution

Agent Actions automatically detects and parallelizes independent agents based on their dependency levels. Agents at the same dependency level execute concurrently, significantly improving workflow performance.

#### How Parallel Execution Works

**Level-Based Execution:**
1. Workflow computes execution levels using BFS (Breadth-First Search)
2. Each level represents agents that can run in parallel
3. Levels execute sequentially, but agents within each level run concurrently
4. Execution proceeds to the next level only after all agents in the current level complete

**Example:**
```yaml
# These will run in parallel (same dependency level)
agents:
  - name: "sentiment_analyzer"
    depends_on: ["input_processor"]
  - name: "entity_extractor"
    depends_on: ["input_processor"]
  - name: "topic_classifier"
    depends_on: ["input_processor"]
  - name: "style_analyzer"
    depends_on: ["input_processor"]

# Execution:
# Level 0: input_processor
# Level 1: [sentiment_analyzer, entity_extractor, topic_classifier, style_analyzer] (parallel)
```

#### Auto-Detection

Parallel execution is automatically enabled when:
- Multiple agents share identical dependencies
- No batch agents are present in the workflow
- Loop agents have no sequential dependencies

```bash
# Auto-detection enabled by default
agent-actions run my-workflow.yaml
```

#### Manual Control

Override auto-detection with CLI flags:

```bash
# Force parallel execution
agent-actions run my-workflow.yaml --parallel

# Force sequential execution (backward compatible)
agent-actions run my-workflow.yaml --no-parallel

# Limit concurrent agents (default: 5, range: 1-50)
agent-actions run my-workflow.yaml --parallel --concurrency-limit 10
```

#### Concurrency Limiting

Control the maximum number of agents running simultaneously:

- **Default**: 5 concurrent agents per level
- **Range**: 1-50 concurrent agents
- **Use Cases**:
  - Reduce API rate limiting issues (lower limit)
  - Maximize throughput with high quotas (higher limit)
  - Control memory usage for resource-intensive agents

```bash
# Conservative approach (sequential-like)
agent-actions run my-workflow.yaml --concurrency-limit 1

# Aggressive parallelization
agent-actions run my-workflow.yaml --concurrency-limit 20
```

#### Performance Benefits

Parallel execution dramatically reduces workflow duration:

**Sequential Execution:**
```
Total Time = Sum of all agent execution times
Example: 10 agents × 30s each = 300s (5 minutes)
```

**Parallel Execution:**
```
Total Time = Sum of level execution times
Example:
  Level 0: 1 agent × 30s = 30s
  Level 1: 8 agents × 30s = 30s (parallel)
  Level 2: 1 agent × 30s = 30s
Total: 90s (1.5 minutes) - 70% faster!
```

#### Breaking Changes

**`previous_agent_type` Behavior:**

In parallel execution, the `previous_agent_type` variable is **undefined** for agents running at the same dependency level. This prevents race conditions where multiple agents might set this value simultaneously.

**Recommendation:** Use explicit dependencies instead:
```yaml
# ❌ Avoid relying on previous_agent_type in parallel workflows
- name: "my_agent"
  prompt: "Process data from {previous_agent_type}"

# ✅ Use explicit dependencies
- name: "my_agent"
  prompt: "Process data from {dependency_agent.output}"
  depends_on: ["dependency_agent"]
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

# Agent Actions resolves to:
# Level 0: preprocessor
# Level 1: analyzer_a + analyzer_b (parallel)
# Level 2: combiner
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

### Sequential Loop Execution

Sequential loops enable iterative refinement workflows where each iteration builds on the output of the previous iteration. This pattern is essential for multi-pass processing, progressive enhancement, and iterative improvement.

#### Parallel vs Sequential Modes

Loops in Agent Actions support two execution modes:

**Parallel Mode (Default)**
- All loop iterations run independently
- Iterations execute concurrently
- Best for independent processing tasks
- Faster execution with parallelization

**Sequential Mode**
- Iterations run in order: iteration 2 waits for iteration 1
- Each iteration can access previous iteration's output
- Best for refinement and enhancement workflows
- Slower but enables iteration-dependent logic

#### Configuration

```yaml
actions:
  # Parallel processing (default)
  - name: process_batch
    loop:
      param: i
      range: [1, 5]
      mode: parallel  # Optional - this is the default
    prompt: "Process batch ${i}"

  # Sequential refinement
  - name: refine_data
    loop:
      param: stage
      range: [1, 3]
      mode: sequential  # Iterations run in order
    prompt: "Refine stage ${stage}: improve output from stage ${stage-1}"
    observe:
      - refined_output_${stage}
```

#### Template Variables

Sequential loops support special template variables for referencing iterations:

- **`${param}`**: Current iteration value
- **`${param-1}`**: Previous iteration value (empty string on first iteration)

These variables work in all configuration fields: `prompt`, `observe`, `drops`, `schema`, etc.

```yaml
actions:
  - name: enhance_content
    loop:
      param: pass
      range: [1, 4]
      mode: sequential

    # Template variables in prompt
    prompt: |
      Pass ${pass}: Enhance the content.
      {% if pass > 1 %}
      Build on previous pass output: {enhanced_content_${pass-1}}
      {% endif %}

    # Template variables in observe
    observe:
      - enhanced_content_${pass}
      - previous_pass_${pass-1}

    # Template variables in schema
    schema:
      pass_number: integer
      current_version: enhanced_content_${pass}
      previous_version: enhanced_content_${pass-1}
```

#### Dependency Chains

Sequential loops automatically create dependency chains:

```yaml
# Configuration with sequential loop
actions:
  - name: extract_data
    prompt: "Extract data from input"

  - name: refine
    loop:
      param: stage
      range: [1, 3]
      mode: sequential
    prompt: "Refine stage ${stage}"

plan:
  - extract_data
  - refine <- extract_data
```

**Creates execution structure:**
```
extract_data → refine_1 → refine_2 → refine_3
```

Each iteration depends only on the previous:
- `refine_1` depends on `extract_data`
- `refine_2` depends on `refine_1`
- `refine_3` depends on `refine_2`

#### Use Cases

**Iterative Data Refinement**
```yaml
actions:
  - name: initial_extraction
    prompt: "Extract structured data from text"

  - name: quality_pass
    loop:
      param: pass
      range: [1, 4]
      mode: sequential
    prompt: |
      Pass ${pass}: Review and improve data from pass ${pass-1}
      Focus areas:
      - Pass 1: Validate completeness
      - Pass 2: Correct errors
      - Pass 3: Enrich data
      - Pass 4: Final quality check
    observe:
      - quality_output_${pass}
```

**Progressive Content Enhancement**
```yaml
actions:
  - name: content_builder
    loop:
      param: stage
      range: [1, 5]
      mode: sequential
    prompt: |
      Stage ${stage}: Build on content from stage ${stage-1}
      - Stage 1: Generate outline
      - Stage 2: Add detailed explanations
      - Stage 3: Add examples
      - Stage 4: Polish language
      - Stage 5: Final review
    observe:
      - content_${stage}
```

**Multi-Level Classification**
```yaml
actions:
  - name: classify
    loop:
      param: level
      range: [1, 3]
      mode: sequential
    prompt: |
      Level ${level}: Classify based on level ${level-1} category
      - Level 1: High-level category
      - Level 2: Subcategory
      - Level 3: Specific topic
    observe:
      - category_${level}
```

#### Performance Considerations

**Sequential Mode:**
- **Execution Time**: Sum of all iteration times (linear)
- **Parallelization**: None - iterations run one at a time
- **When to Use**: When iteration N+1 **must** depend on iteration N output

**Parallel Mode:**
- **Execution Time**: Max of iteration times (constant with concurrency)
- **Parallelization**: Full - all iterations run concurrently
- **When to Use**: When iterations are independent of each other

**Hybrid Approach:**
Mix both modes in the same workflow:
```yaml
actions:
  # Parallel extraction (fast)
  - name: extract_features
    loop:
      param: feature
      range: [1, 10]
      mode: parallel

  # Sequential refinement (quality)
  - name: refine_features
    loop:
      param: stage
      range: [1, 3]
      mode: sequential

  # Parallel export (fast)
  - name: export_results
    loop:
      param: format
      range: [1, 5]
      mode: parallel
```

#### Error Handling

If an iteration fails in sequential mode, subsequent iterations are automatically skipped:

```yaml
# If refine_2 fails:
# - refine_1: completed ✓
# - refine_2: failed ✗
# - refine_3: skipped (dependency failed)
# - refine_4: skipped (dependency failed)
```

The dependency chain ensures that failed iterations block dependent iterations, preventing incorrect results from propagating.

#### Backward Compatibility

Sequential loops are fully backward compatible:
- Existing loops without `mode` default to `parallel`
- No changes required to existing workflows
- Explicit `mode: parallel` has same behavior as omitting the field

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