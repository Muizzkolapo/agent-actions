# Example 9: Sequential Loops

This example demonstrates how to use sequential loop execution for iterative refinement, progressive enhancement, and multi-pass processing workflows.

## What are Sequential Loops?

Sequential loops enable **iterative workflows** where each iteration builds on the output of the previous iteration. Unlike parallel loops where all iterations run independently, sequential loops create a dependency chain where iteration N+1 waits for iteration N to complete.

### Benefits

✅ **Iterative Refinement**: Each pass improves on the previous pass
✅ **Progressive Enhancement**: Build complex outputs through sequential steps
✅ **Multi-Pass Processing**: Apply different processing stages in order
✅ **Access Previous Outputs**: Use `${param-1}` to reference previous iteration

### Trade-offs

⚠️ **Slower Execution**: Iterations run one at a time (no parallelization)
⚠️ **Linear Time**: Total time = sum of all iteration times
⚠️ **Error Propagation**: If iteration N fails, N+1 won't run

## Loop Modes Comparison

### Parallel Mode (Default)

```yaml
loop:
  param: i
  range: [1, 5]
  mode: parallel  # or omit - parallel is default
```

**Execution**: All 5 iterations run concurrently
```
parent → [iter_1, iter_2, iter_3, iter_4, iter_5] → next_agent
```

**Use when**: Iterations are independent of each other

### Sequential Mode

```yaml
loop:
  param: i
  range: [1, 5]
  mode: sequential
```

**Execution**: Iterations run in order
```
parent → iter_1 → iter_2 → iter_3 → iter_4 → iter_5 → next_agent
```

**Use when**: Each iteration needs output from the previous iteration

## Example 1: Basic Sequential Refinement

Simple 3-stage refinement where each stage improves on the previous.

### Configuration

```yaml
# workflows/sequential-refinement.yml
name: data_refinement
description: Iteratively refine extracted data through 3 stages
version: 1.0.0

defaults:
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}

actions:
  - name: extract_initial
    intent: Extract initial structured data
    prompt: |
      Extract structured data from the following text:
      {{ input_text }}

      Focus on accuracy and completeness.

    schema:
      entities: array
      facts: array
      confidence: number

  - name: refine
    intent: Iteratively refine the extracted data
    loop:
      param: stage
      range: [1, 3]
      mode: sequential  # Each stage builds on previous

    prompt: |
      Stage ${stage}: Refine the extracted data.

      {% if stage == 1 %}
      Original extraction: {{ extract_initial.output }}
      Task: Validate completeness and identify missing information
      {% else %}
      Previous refinement: {{ refined_stage_${stage-1} }}
      Task: Improve accuracy and add missing details
      {% endif %}

    observe:
      - refined_stage_${stage}

    schema:
      entities: array
      facts: array
      improvements: string
      confidence: number

  - name: validate
    intent: Final validation of refined data
    prompt: |
      Validate the final refined data:
      {{ refine.output }}

      Confirm all information is accurate and complete.

    schema:
      is_valid: boolean
      quality_score: number
      notes: string

plan:
  - extract_initial
  - refine <- extract_initial
  - validate <- refine
```

### Usage

```bash
# Run the refinement workflow
agent-actions run sequential-refinement --input data.jsonl

# Execution flow:
# 1. extract_initial runs
# 2. refine_1 runs (validates extraction)
# 3. refine_2 runs (improves on refine_1)
# 4. refine_3 runs (improves on refine_2)
# 5. validate runs (checks final output)
```

### Output Structure

```json
{
  "extract_initial": {
    "entities": [...],
    "facts": [...],
    "confidence": 0.75
  },
  "refined_stage_1": {
    "entities": [...],
    "facts": [...],
    "improvements": "Added missing entities, validated facts",
    "confidence": 0.85
  },
  "refined_stage_2": {
    "entities": [...],
    "facts": [...],
    "improvements": "Corrected 3 entities, added context",
    "confidence": 0.92
  },
  "refined_stage_3": {
    "entities": [...],
    "facts": [...],
    "improvements": "Final polish, verified all facts",
    "confidence": 0.97
  },
  "validate": {
    "is_valid": true,
    "quality_score": 0.95,
    "notes": "High quality output after 3 refinement stages"
  }
}
```

## Example 2: Progressive Content Enhancement

Build complex content through sequential enhancement stages.

### Configuration

```yaml
# workflows/content-builder.yml
name: progressive_content_builder
description: Build high-quality content through 5 progressive stages
version: 1.0.0

defaults:
  model_vendor: openai
  model_name: gpt-4o
  api_key: ${OPENAI_API_KEY}
  temperature: 0.7

actions:
  - name: build_content
    intent: Progressively build and enhance content
    loop:
      param: stage
      range: [1, 5]
      mode: sequential

    prompt: |
      Stage ${stage} of content development for topic: {{ topic }}

      {% if stage == 1 %}
      Create a detailed outline with main sections and key points.
      {% elif stage == 2 %}
      Previous outline: {{ content_stage_1 }}
      Expand each section with detailed explanations.
      {% elif stage == 3 %}
      Previous content: {{ content_stage_2 }}
      Add concrete examples and illustrations for each point.
      {% elif stage == 4 %}
      Previous content: {{ content_stage_3 }}
      Polish the language, improve flow, and enhance clarity.
      {% else %}
      Previous content: {{ content_stage_4 }}
      Final review: Check for completeness, accuracy, and quality.
      Make final improvements.
      {% endif %}

    observe:
      - content_stage_${stage}

    schema:
      stage_number: integer
      content: string
      word_count: integer
      quality_notes: string

plan:
  - build_content
```

### Usage

```bash
# Run content builder
agent-actions run content-builder \
  --input '{"topic": "Introduction to Machine Learning"}' \
  --output final-content.json

# Stages:
# Stage 1: Creates outline (~200 words)
# Stage 2: Adds details (~800 words)
# Stage 3: Adds examples (~1500 words)
# Stage 4: Polishes language (~1500 words, refined)
# Stage 5: Final review (~1500 words, production-ready)
```

## Example 3: Multi-Pass Data Processing

Extract → Analyze → Synthesize pipeline with template variables.

### Configuration

```yaml
# workflows/multi-pass-processor.yml
name: multi_pass_processor
description: Process data through extraction, analysis, and synthesis
version: 1.0.0

defaults:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}

actions:
  - name: process
    intent: Multi-pass processing with progressive enhancement
    loop:
      param: pass
      range: [1, 3]
      mode: sequential

    prompt: |
      Pass ${pass}: {{ pass_descriptions[pass] }}

      {% if pass == 1 %}
      Input data: {{ raw_data }}
      Task: Extract key information and structure it.
      {% elif pass == 2 %}
      Extracted data: {{ processing_pass_1 }}
      Task: Analyze patterns, relationships, and insights.
      {% else %}
      Analyzed data: {{ processing_pass_2 }}
      Task: Synthesize findings into actionable recommendations.
      {% endif %}

    observe:
      - processing_pass_${pass}
      - metadata_pass_${pass}

    drops:
      - intermediate_data_${pass}  # Drop temporary data

    schema:
      pass_number: integer
      pass_name: string
      output_data: object
      insights_${pass}: array
      next_steps_${pass}: string

plan:
  - process
```

### Template Variables in Action

```yaml
# During expansion, these template variables are replaced:

# Pass 1:
# - ${pass} → "1"
# - ${pass-1} → "" (empty string on first iteration)
# - observe: ["processing_pass_1", "metadata_pass_1"]
# - drops: ["intermediate_data_1"]

# Pass 2:
# - ${pass} → "2"
# - ${pass-1} → "1"
# - observe: ["processing_pass_2", "metadata_pass_2"]
# - drops: ["intermediate_data_2"]

# Pass 3:
# - ${pass} → "3"
# - ${pass-1} → "2"
# - observe: ["processing_pass_3", "metadata_pass_3"]
# - drops: ["intermediate_data_3"]
```

## Example 4: Sequential vs Parallel Comparison

Same task implemented in both modes to show the difference.

### Parallel Implementation (Fast, Independent)

```yaml
name: parallel_analysis
description: Analyze 5 documents in parallel

actions:
  - name: analyze_docs
    loop:
      param: doc_id
      range: [1, 5]
      mode: parallel  # All run concurrently

    prompt: "Analyze document ${doc_id}: {{ documents[doc_id] }}"

    schema:
      doc_id: integer
      summary: string
      key_points: array

plan:
  - analyze_docs
```

**Execution time**: Max(time_1, time_2, time_3, time_4, time_5) ≈ ~30 seconds

**Dependency graph**:
```
input → [doc_1, doc_2, doc_3, doc_4, doc_5] → output
```

### Sequential Implementation (Slow, Iterative)

```yaml
name: sequential_refinement
description: Refine analysis through 5 progressive stages

actions:
  - name: refine_analysis
    loop:
      param: stage
      range: [1, 5]
      mode: sequential  # Each builds on previous

    prompt: |
      Stage ${stage}: Refine the analysis.
      {% if stage > 1 %}
      Previous analysis: {{ analysis_stage_${stage-1} }}
      {% endif %}

    observe:
      - analysis_stage_${stage}

    schema:
      stage: integer
      analysis: string
      improvements: string

plan:
  - refine_analysis
```

**Execution time**: Sum(time_1 + time_2 + time_3 + time_4 + time_5) ≈ ~150 seconds

**Dependency graph**:
```
input → stage_1 → stage_2 → stage_3 → stage_4 → stage_5 → output
```

### When to Use Each Mode

| Use Case | Best Mode | Reason |
|----------|-----------|--------|
| Batch processing 1000 documents | `parallel` | Independent tasks, maximize throughput |
| Refining a single document 5 times | `sequential` | Each pass builds on previous |
| Extract features from 10 images | `parallel` | Independent extraction |
| Progressive content enhancement | `sequential` | Iterative improvement |
| Multi-aspect analysis (sentiment, entities, topics) | `parallel` | Different independent analyses |
| Multi-pass validation (completeness → accuracy → quality) | `sequential` | Each pass validates different aspect |

## Advanced Patterns

### Explicit Range Values

Use explicit lists instead of `[start, end]`:

```yaml
loop:
  param: priority_level
  range: [10, 20, 30, 50, 100]  # Explicit values
  mode: sequential

prompt: |
  Process priority level ${priority_level}
  {% if priority_level > 10 %}
  Compare with previous level ${priority_level-1}
  {% endif %}
```

**Creates**: `action_10`, `action_20`, `action_30`, `action_50`, `action_100`

### Mixed Sequential and Parallel

Combine both modes in one workflow:

```yaml
actions:
  # Parallel extraction (fast)
  - name: extract_features
    loop:
      param: feature_type
      range: [1, 10]
      mode: parallel
    prompt: "Extract feature type ${feature_type}"

  # Sequential refinement (quality)
  - name: refine_features
    loop:
      param: stage
      range: [1, 3]
      mode: sequential
    prompt: "Refine all features - stage ${stage}"

  # Parallel export (fast)
  - name: export_formats
    loop:
      param: format_id
      range: [1, 5]
      mode: parallel
    prompt: "Export to format ${format_id}"

plan:
  - extract_features
  - refine_features <- extract_features
  - export_formats <- refine_features
```

**Execution flow**:
```
[extract_1...extract_10] → refine_1 → refine_2 → refine_3 → [export_1...export_5]
   (parallel)              (sequential)                         (parallel)
```

### Template Variables in Nested Structures

Template variables work in complex nested structures:

```yaml
loop:
  param: iteration
  range: [1, 4]
  mode: sequential

schema:
  metadata:
    iteration_number: ${iteration}
    previous_iteration: ${iteration-1}
    nested_data:
      current: iteration_${iteration}
      previous: iteration_${iteration-1}

  processing:
    input_source: stage_${iteration-1}_output
    output_destination: stage_${iteration}_output

  validation:
    compare_with:
      - stage_${iteration-1}
      - stage_${iteration-2}

observe:
  - stage_${iteration}_output
  - stage_${iteration}_metadata
  - comparison_${iteration}_vs_${iteration-1}
```

### Error Handling

Sequential loops automatically handle errors through dependency chains:

```yaml
# If refine_2 fails:
# - refine_1: completed ✓
# - refine_2: failed ✗
# - refine_3: skipped (dependency failed) ⏭
# - refine_4: skipped (dependency failed) ⏭
# - refine_5: skipped (dependency failed) ⏭
```

**Best practice**: Add validation to catch errors early:

```yaml
actions:
  - name: refine
    loop:
      param: stage
      range: [1, 5]
      mode: sequential

    prompt: |
      Stage ${stage}: Refine the data.
      {% if stage > 1 %}
      Previous: {{ refined_stage_${stage-1} }}
      {% endif %}

    schema:
      data: object
      is_valid: boolean  # Validate each stage
      quality_score: number

    # Stop if quality is low
    validation:
      quality_score:
        minimum: 0.7
```

## Performance Considerations

### Sequential Mode Characteristics

**Execution Time**: Linear
```
total_time = time_iter_1 + time_iter_2 + ... + time_iter_N
```

**Example**: 5 iterations × 30 seconds each = 150 seconds total

**Parallelization**: None - iterations are sequential by design

**When to Use**:
- Each iteration improves on previous output
- Quality matters more than speed
- Iterative refinement workflows
- Progressive enhancement
- Multi-stage validation

### Parallel Mode Characteristics

**Execution Time**: Constant (with sufficient concurrency)
```
total_time ≈ max(time_iter_1, time_iter_2, ..., time_iter_N)
```

**Example**: 5 iterations × 30 seconds each = ~30 seconds total (with 5 concurrent workers)

**Parallelization**: Full - all iterations run simultaneously

**When to Use**:
- Iterations are independent
- Speed matters more than inter-iteration dependencies
- Batch processing
- Fan-out patterns
- Independent analyses

### Hybrid Strategy

Optimize for both speed and quality:

```yaml
# Fast parallel extraction
- name: extract_data
  loop: {param: i, range: [1, 100], mode: parallel}

# Quality-focused sequential refinement
- name: refine_aggregated
  loop: {param: stage, range: [1, 3], mode: sequential}

# Fast parallel export
- name: export_results
  loop: {param: format, range: [1, 10], mode: parallel}
```

**Total time**:
- Parallel extraction: ~30s (100 items)
- Sequential refinement: ~60s (3 stages × 20s)
- Parallel export: ~15s (10 formats)
- **Total**: ~105s instead of 100×30 + 3×20 + 10×15 = 3,210s

## Best Practices

### 1. Choose the Right Mode

✅ **Use Sequential for**:
- Iterative refinement (each pass improves previous)
- Progressive enhancement (build complexity gradually)
- Multi-stage validation (completeness → accuracy → quality)
- Dependent processing stages

✅ **Use Parallel for**:
- Batch processing independent items
- Multi-aspect analysis (sentiment + entities + topics)
- Fan-out patterns
- Independent transformations

### 2. Design Effective Prompts

**Sequential loops benefit from context**:
```yaml
prompt: |
  Stage ${stage}: Refine the output.

  {% if stage == 1 %}
  Original input: {{ input_data }}
  Focus: Initial structure and completeness
  {% else %}
  Previous stage output: {{ output_stage_${stage-1} }}
  Focus: Improve based on stage ${stage-1} results
  {% endif %}

  Quality target: > {{ 0.5 + (stage * 0.1) }}
```

### 3. Use Template Variables Effectively

```yaml
# Current iteration
observe: [output_${stage}]

# Previous iteration (for comparison)
observe: [output_${stage}, previous_${stage-1}]

# Multiple previous references
observe: [
  current_${stage},
  previous_${stage-1},
  baseline_1  # Always reference first iteration
]
```

### 4. Handle Edge Cases

**First iteration** (`${param-1}` is empty):
```yaml
prompt: |
  {% if stage == 1 %}
  Process initial input: {{ input_data }}
  {% else %}
  Refine previous output: {{ output_${stage-1} }}
  {% endif %}
```

**Last iteration** (finalization):
```yaml
prompt: |
  {% if stage == max_stage %}
  Final polish and validation.
  {% else %}
  Prepare for stage ${stage + 1}.
  {% endif %}
```

### 5. Monitor Quality Across Iterations

```yaml
schema:
  stage_number: integer
  output_data: object
  quality_metrics:
    completeness: number
    accuracy: number
    improvement_over_previous: number

observe:
  - quality_metrics_${stage}
```

## Common Patterns

### Pattern 1: Extract → Validate → Correct → Enrich

```yaml
actions:
  - name: data_pipeline
    loop: {param: pass, range: [1, 4], mode: sequential}
    prompt: |
      Pass ${pass}:
      1: Extract data
      2: Validate extraction
      3: Correct errors
      4: Enrich with additional info
```

### Pattern 2: Outline → Detail → Examples → Polish

```yaml
actions:
  - name: content_dev
    loop: {param: stage, range: [1, 4], mode: sequential}
    prompt: |
      Stage ${stage}:
      1: Create outline
      2: Add detailed explanations
      3: Add examples
      4: Polish language
```

### Pattern 3: Classify → Sub-classify → Specific Topic

```yaml
actions:
  - name: hierarchical_classification
    loop: {param: level, range: [1, 3], mode: sequential}
    prompt: |
      Level ${level}:
      1: High-level category
      2: Subcategory within level 1
      3: Specific topic within level 2
```

## Common Issues & YAML Syntax Tips

### ✅ Use Block Sequences for Template Variables

**Recommended** (block sequence):
```yaml
reads:
  - input_data
  - previous_result_${stage-1}
writes:
  - result_${stage}
```

**Avoid** (flow sequence - may cause parsing errors):
```yaml
reads: [input_data, previous_result_${stage-1}]  # Can fail with some YAML parsers
writes: [result_${stage}]
```

**Why**: Template variables with special characters like `${stage-1}` can confuse YAML parsers in flow sequences.

### ✅ Quote Schema Keys with Template Variables

**Recommended**:
```yaml
schema:
  "distractor_${stage}": string
  "explanation_${stage}": string
  "result_${stage-1}": string
```

**Avoid**:
```yaml
schema:
  distractor_${stage}: string  # May cause YAML parsing errors
  result_${stage-1}: string
```

**Why**: YAML parsers may misinterpret unquoted keys containing `$`, `{`, `}`, or `-`.

### ✅ Avoid Inline Comments on Template Variable Lines

**Recommended**:
```yaml
# Access previous iteration output
reads:
  - previous_result_${stage-1}
```

**Avoid**:
```yaml
reads:
  - previous_result_${stage-1}  # Access previous iteration
```

**Why**: Inline comments on lines with template variables can cause "flow sequence parsing" errors.

## Next Steps

- See [Configuration Reference](/reference/configuration-fields#loop) for complete loop configuration options
- See [Workflows Guide](/core-concepts/workflows#sequential-loop-execution) for more patterns
- See [Loop Correlation](/advanced/loop-correlation) for consuming loop outputs
