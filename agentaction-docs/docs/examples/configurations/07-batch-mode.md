# Example 7: Batch Mode Configuration

This example demonstrates how to configure and use batch processing for high-volume, cost-effective LLM operations using vendor batch APIs.

## What is Batch Mode?

Batch mode allows you to process large datasets asynchronously using vendor batch APIs:

- **OpenAI**: Batch API (50% cost reduction)
- **Anthropic**: Message Batches API (50% cost reduction)
- Other vendors may have similar batch offerings

### Benefits

✅ **50% cost savings** on supported models
✅ **Large-scale processing** (thousands to millions of items)
✅ **Asynchronous execution** (submit job, check later)
✅ **No rate limit concerns** for batch requests

### Trade-offs

⚠️ **Slower**: 24-hour processing window (not real-time)
⚠️ **Async only**: Submit job, wait for completion
⚠️ **Limited debugging**: Harder to troubleshoot failures

## Basic Batch Configuration

### Minimal Batch Setup

```yaml
# workflows/batch-process.yml
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

actions:
  - name: process_items
    batch_mode: true          # Enable batch processing

    reads:
      - text

    writes:
      - summary

    prompt: |
      Summarize: {{ text }}

    schema:
      summary: string
```

### Running Batch Job

```bash
# Submit batch job
agent-actions run batch-process --input large-dataset.jsonl

# Output:
# Batch job submitted: batch_abc123xyz
# Check status: agent-actions batch status batch_abc123xyz
```

### Checking Status

```bash
# Check batch job status
agent-actions batch status batch_abc123xyz

# Output:
# Status: in_progress
# Progress: 2500/10000 items (25%)
# Estimated completion: 2024-01-15 14:30:00

# When complete:
# Status: completed
# Results saved to: outputs/batch_abc123xyz/
```

## Example 1: Cost-Optimized Batch Processing

### Use Case
Process 100,000 articles for analysis - cost matters more than speed.

### Configuration

```yaml
# workflows/large-scale-analysis.yml

# Use batch-optimized model
model_vendor: openai
model_name: gpt-4o-mini        # Cheaper model
api_key: ${OPENAI_API_KEY}
temperature: 0.7

actions:
  - name: analyze_article
    batch_mode: true           # 50% cost reduction
    batch_size: 1000          # Items per batch file

    reads:
      - article_text
      - article_id

    writes:
      - analysis
      - key_themes
      - sentiment

    prompt: |
      Analyze this article:
      {{ article_text }}

      Provide:
      1. Brief analysis
      2. Key themes (3-5)
      3. Overall sentiment

    schema:
      analysis: string
      key_themes:
        type: array
        items: string
        minItems: 3
        maxItems: 5
      sentiment:
        type: string
        enum: [positive, negative, neutral]
```

### Cost Calculation

**Without batch mode** (100,000 items × 2000 tokens):
- Input: 100k × 2000 × $0.00015 = $30
- Output: 100k × 500 × $0.00060 = $30
- **Total: $60**

**With batch mode** (50% discount):
- **Total: $30** (saves $30!)

### Running

```bash
# Submit job
agent-actions run large-scale-analysis --input articles.jsonl

# Batch job submitted: batch_20240115_143000
# Processing 100,000 items...
# Check status: agent-actions batch status batch_20240115_143000
```

## Example 2: Multi-Step Batch Pipeline

### Use Case
Multi-step processing where each step is batched independently.

### Configuration

```yaml
# workflows/batch-pipeline.yml

model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

actions:
  # STEP 1: Batch extraction
  - name: extract_entities
    batch_mode: true
    batch_size: 500

    reads:
      - raw_text

    writes:
      - entities
      - entity_count

    prompt: |
      Extract named entities from: {{ raw_text }}

    schema:
      entities:
        type: array
        items: string
      entity_count: integer

  # STEP 2: Batch classification
  - name: classify_content
    batch_mode: true
    batch_size: 500

    reads:
      - raw_text
      - entities

    writes:
      - category
      - confidence

    prompt: |
      Classify this content:
      Text: {{ raw_text }}
      Entities: {{ entities | join(', ') }}

    schema:
      category: string
      confidence:
        type: number
        minimum: 0.0
        maximum: 1.0

  # STEP 3: Batch summarization
  - name: create_summary
    batch_mode: true
    batch_size: 500

    reads:
      - raw_text
      - entities
      - category

    writes:
      - summary

    prompt: |
      Summarize this {{ category }} content:
      {{ raw_text }}

      Focus on these entities: {{ entities | join(', ') }}

    schema:
      summary: string
```

### Running Multi-Step Batch

```bash
# Submit pipeline
agent-actions run batch-pipeline --input data.jsonl

# Output:
# Step 1: Submitting batch for extract_entities...
#   Batch ID: batch_extract_xyz123
# Step 2: Waiting for extract_entities completion...
#   Status: in_progress (0%)
#   Status: in_progress (45%)
#   Status: completed (100%)
# Step 3: Submitting batch for classify_content...
#   Batch ID: batch_classify_abc456
# ...
```

Each step waits for the previous batch to complete before starting.

## Example 3: Conditional Batch Processing

### Use Case
Only batch process items that match certain criteria.

### Configuration

```yaml
# workflows/conditional-batch.yml

model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

actions:
  - name: process_important_items
    batch_mode: true

    # WHERE clause filters items before batching
    where_clause:
      clause: priority == "high"
      scope: item
      behavior: filter        # Filter out low-priority items

    reads:
      - content
      - priority

    writes:
      - detailed_analysis

    prompt: |
      Provide detailed analysis for this high-priority item:
      {{ content }}

    schema:
      detailed_analysis: string

  - name: quick_process_others
    batch_mode: true

    # Process items that weren't high priority
    where_clause:
      clause: priority != "high"
      scope: item
      behavior: skip          # Include but mark as skipped

    reads:
      - content
      - priority

    writes:
      - quick_summary

    prompt: |
      Quick summary: {{ content }}

    schema:
      quick_summary: string
```

## Example 4: Mixing Online and Batch Modes

### Use Case
Some actions need real-time results, others can be batched.

### Configuration

```yaml
# workflows/mixed-mode.yml

model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

actions:
  # ONLINE: Fast validation (need immediate results)
  - name: validate_input
    # batch_mode: false (default)

    reads:
      - raw_text

    writes:
      - is_valid
      - validation_reason

    prompt: |
      Is this text valid for processing? {{ raw_text }}

    schema:
      is_valid: boolean
      validation_reason: string

  # BATCH: Process valid items in batch (cost-optimized)
  - name: deep_analysis
    batch_mode: true
    batch_size: 1000

    reads:
      - raw_text
      - is_valid

    writes:
      - analysis

    prompt: |
      {% if is_valid %}
      Analyze: {{ raw_text }}
      {% else %}
      Skip - invalid input
      {% endif %}

    schema:
      analysis: string

  # ONLINE: Generate urgent report (need immediate results)
  - name: create_urgent_report
    # batch_mode: false (default)

    reads:
      - analysis

    writes:
      - urgent_report

    prompt: |
      Create urgent report from: {{ analysis }}

    schema:
      urgent_report: string
```

## Batch Configuration Options

### batch_mode (boolean)

```yaml
batch_mode: true     # Enable batch processing
batch_mode: false    # Online processing (default)
```

### batch_size (integer)

Number of items per batch file (vendor-specific limits apply):

```yaml
batch_size: 100      # Small batches (faster turnaround)
batch_size: 1000     # Medium batches (balanced)
batch_size: 10000    # Large batches (max throughput)
```

**Vendor Limits**:
- OpenAI: Max 50,000 requests per batch
- Anthropic: Max 10,000 requests per batch

### Batch Directory Structure

```
outputs/
└── batch_20240115_143000/
    ├── batch_metadata.json       # Job info
    ├── batch_input_001.jsonl     # Batch input file 1
    ├── batch_input_002.jsonl     # Batch input file 2
    ├── batch_results_001.jsonl   # Results from batch 1
    ├── batch_results_002.jsonl   # Results from batch 2
    └── final_output.jsonl        # Merged results
```

## Best Practices

### 1. Choose Appropriate Batch Size

```yaml
# Small datasets (<1000 items): smaller batches for faster turnaround
batch_size: 100

# Medium datasets (1k-10k items): balanced
batch_size: 1000

# Large datasets (>10k items): maximize throughput
batch_size: 10000
```

### 2. Monitor Batch Jobs

```bash
# List all batch jobs
agent-actions batch list

# Check specific job
agent-actions batch status batch_abc123

# Cancel if needed
agent-actions batch cancel batch_abc123
```

### 3. Handle Failures

```yaml
# Batch processing automatically retries failed items
# Configure retry behavior:
actions:
  - name: process_with_retries
    batch_mode: true
    max_retries: 3          # Retry failed items up to 3 times
    retry_delay: 300        # Wait 5 minutes between retries
```

### 4. Estimate Processing Time

**OpenAI Batch API**:
- Processing window: 24 hours
- Typical: 2-12 hours depending on load
- Priority: First-in-first-out

**Anthropic Message Batches**:
- Processing window: 24 hours
- Typical: 1-6 hours

### 5. Cost Optimization Strategy

```yaml
# For large volumes: Use batch mode with cheapest model
model_name: gpt-4o-mini
batch_mode: true
# Cost: ~50% off (already cheap model + batch discount)

# For quality: Use batch mode with better model
model_name: gpt-4o
batch_mode: true
# Cost: ~50% off expensive model (may still be cheaper than mini online)
```

## Limitations

### What Works in Batch Mode

✅ Standard LLM actions
✅ Structured output schemas
✅ Multi-step workflows (sequential batching)
✅ WHERE clause filtering
✅ Conditional logic in prompts

### What Doesn't Work in Batch Mode

❌ **Tool actions** (always online only)
❌ **Streaming responses** (batch is async)
❌ **Real-time requirements** (24-hour window)
❌ **Interactive workflows** (no mid-flight changes)
❌ **Function calling** (not supported in batch APIs)

### Tool Actions Cannot Use Batch Mode

```yaml
# ❌ INVALID: Tool actions cannot use batch_mode
actions:
  - name: my_tool
    kind: tool
    impl: my_module.function
    batch_mode: true        # ERROR: tools run online only
```

Tool actions always run in online mode, even in batch workflows:

```yaml
# ✅ VALID: Mixed online tools + batch LLM
actions:
  - name: validate          # Tool action (online)
    kind: tool
    impl: validators.check

  - name: analyze           # LLM action (batch)
    batch_mode: true
    # ...
```

## Vendor Support

| Vendor | Batch API | Cost Savings | Max Items/Batch |
|--------|-----------|--------------|-----------------|
| OpenAI | ✅ Yes | 50% | 50,000 |
| Anthropic | ✅ Yes | 50% | 10,000 |
| Gemini | ⏳ Coming | TBD | TBD |
| Groq | ❌ No | - | - |
| DeepSeek | ❌ No | - | - |
| Perplexity | ❌ No | - | - |

## When to Use Batch Mode

✅ **Use batch mode when:**
- Processing thousands+ items
- Cost is more important than speed
- You can wait hours/days for results
- Data is ready upfront (not streaming)
- Using OpenAI or Anthropic

❌ **Don't use batch mode when:**
- Need real-time results
- Processing small datasets (less than 100 items)
- Using unsupported vendors (Groq, Gemini, etc.)
- Workflow includes tool actions
- Need interactive feedback

## Next Steps

- [Core Concepts: Workflows](../../core-concepts/workflows.md) - Workflow design
- [Core Concepts: Schemas](../../core-concepts/schemas.md) - Output schemas
- [Example 1: Project-Only Config](./01-project-only.md) - Start simple

## Complete Example

```yaml
# workflows/production-batch.yml

# Cost-optimized batch processing for production
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7

actions:
  - name: process_documents
    batch_mode: true
    batch_size: 5000         # 5k items per batch file

    reads:
      - document_text
      - document_id

    writes:
      - summary
      - key_points
      - category

    prompt: |
      Process this document:
      {{ document_text }}

      Extract:
      1. Summary (3 sentences)
      2. Key points (5 bullet points)
      3. Category

    schema:
      summary: string
      key_points:
        type: array
        items: string
        minItems: 5
        maxItems: 5
      category: string

# Run:
# agent-actions run production-batch --input documents.jsonl
#
# With 50,000 documents:
# - Creates 10 batch files (5k each)
# - Submits to OpenAI Batch API
# - Saves ~50% on costs
# - Completes in 4-12 hours
