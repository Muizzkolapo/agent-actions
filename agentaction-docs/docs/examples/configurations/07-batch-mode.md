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

| Vendor | Batch API | Cost Savings | Max Items/Batch | Use Case |
|--------|-----------|--------------|-----------------|----------|
| OpenAI | ✅ Yes | 50% | 50,000 | Production, cost optimization |
| Anthropic | ✅ Yes | 50% | 10,000 | Production, cost optimization |
| Gemini | ✅ Yes | TBD | TBD | Production (Google Cloud) |
| Ollama | ✅ Yes (Local) | 100% (Free) | Unlimited | Local testing, development |
| Groq | ❌ No | - | - | - |
| DeepSeek | ❌ No | - | - | - |
| Perplexity | ❌ No | - | - | - |

## Local Testing with Ollama

### What is Ollama Batch Mode?

Ollama provides a **local, zero-cost batch processing mode** for testing and development. Unlike cloud batch APIs (OpenAI, Anthropic) that process asynchronously, Ollama batch mode processes synchronously on your local machine.

### Benefits of Ollama Batch Mode

✅ **Zero cost** - Completely free, runs locally
✅ **Fast iteration** - Test batch workflows in minutes, not hours
✅ **Offline capability** - No internet connection required
✅ **CI/CD friendly** - Run batch tests in continuous integration
✅ **Same interface** - Drop-in replacement for cloud providers
✅ **Privacy** - Your data never leaves your machine

### Use Cases

**Development & Testing**
- Test batch workflow logic before using expensive cloud APIs
- Validate retry logic, DLQ handling, and manifest generation
- Develop batch features offline

**CI/CD Pipelines**
- Run batch workflow tests in GitHub Actions, GitLab CI, etc.
- Validate batch processing without API costs
- Test at scale locally before production deployment

**Cost Optimization**
- Test with large datasets locally (10 iterations × $10 = $100 saved)
- Prototype and debug with real batch sizes
- Validate results before submitting to paid APIs

### Ollama Batch Configuration

#### Basic Setup

```yaml
# workflows/local-batch-test.yml
model_vendor: ollama          # Use Ollama local provider
model_name: llama3.2          # Any Ollama model
base_url: http://localhost:11434  # Optional, defaults to this

actions:
  - name: process_items
    batch_mode: true           # Enable batch processing

    reads:
      - text

    writes:
      - summary

    prompt: |
      Summarize: {{ text }}

    schema:
      summary: string
```

#### Prerequisites

Make sure Ollama is installed and running:

```bash
# Install Ollama (if not already installed)
# Visit: https://ollama.com/download

# Start Ollama server
ollama serve

# Pull a model (in another terminal)
ollama pull llama3.2

# Verify it's running
curl http://localhost:11434/api/tags
```

#### Running Ollama Batch Job

```bash
# Submit batch job (processes immediately)
agent-actions run local-batch-test --input test-data.jsonl

# Output:
# ✅ Batch processing complete (synchronous)
# Processed: 100 items in 45 seconds
# Results saved to: outputs/batch_20240115_143000/
```

### Example: Testing Batch Workflow Locally

Before running an expensive OpenAI batch job with 10,000 items, test locally with Ollama:

```yaml
# workflows/test-batch-workflow.yml

# STEP 1: Test locally with Ollama
model_vendor: ollama
model_name: llama3.2
# base_url: http://localhost:11434  # Optional

actions:
  - name: extract_data
    batch_mode: true
    batch_size: 100

    reads:
      - article_text

    writes:
      - extracted_facts
      - key_themes

    prompt: |
      Extract key facts and themes from:
      {{ article_text }}

    schema:
      extracted_facts:
        type: array
        items: string
        minItems: 3
      key_themes:
        type: array
        items: string
        minItems: 2
```

Test with sample data:

```bash
# Test with 100 items locally (takes ~2 minutes)
agent-actions run test-batch-workflow --input sample-100.jsonl

# Verify:
# ✅ Batch files created correctly
# ✅ Retry logic works
# ✅ DLQ handling works
# ✅ Output format is correct

# STEP 2: Switch to production API (just change one line!)
# model_vendor: openai  # Change this line
# model_name: gpt-4o-mini

# Now run with full dataset (10,000 items)
agent-actions run test-batch-workflow --input full-dataset.jsonl
```

### Ollama vs Cloud Batch APIs

| Feature | Ollama | OpenAI/Anthropic |
|---------|--------|------------------|
| **Processing** | Synchronous (immediate) | Asynchronous (24h window) |
| **Cost** | Free | 50% off standard rates |
| **Speed** | Depends on your hardware | 2-12 hours typical |
| **Internet** | Not required | Required |
| **Scale** | Limited by your machine | Millions of items |
| **Use Case** | Testing, development | Production, cost optimization |

### Important Differences

#### 1. Synchronous Processing

Ollama processes all items **immediately** and **sequentially**:

```yaml
# Ollama batch workflow
actions:
  - name: process
    batch_mode: true
    # Runs synchronously - waits until all items complete
```

**Behavior**:
- `submit_batch()` processes all items before returning
- `check_status()` always returns "completed"
- `retrieve_results()` immediately returns results

#### 2. No Parallelization

Ollama processes one item at a time:

```bash
# With 100 items, Ollama processes:
# Item 1 → Item 2 → Item 3 → ... → Item 100

# Cloud APIs process:
# Items 1-100 in parallel (faster for large batches)
```

**Performance Consideration**:
- Small batches (< 1000): Ollama is fine for testing
- Large batches (> 10,000): Cloud APIs are much faster

#### 3. Local Resource Limits

Ollama uses your machine's resources:

```yaml
# Your batch size is limited by:
# - Available RAM
# - CPU/GPU capacity
# - Storage space

# Recommended for testing:
batch_size: 100-500   # Good for local testing
```

### Limitations

⚠️ **Not for production scale**
- Sequential processing (not parallel)
- Limited by local hardware
- No distributed processing

⚠️ **Model quality differences**
- Llama, Mistral, etc. may produce different outputs than GPT-4
- Use for workflow testing, not output quality validation

⚠️ **No async status tracking**
- Status is always "completed" (synchronous)
- No progress tracking mid-batch

### Best Practices

#### 1. Use Ollama for Workflow Testing

```yaml
# Test these batch features locally with Ollama:
# ✅ Batch file generation (JSONL format)
# ✅ Retry logic (force failures to test)
# ✅ DLQ handling (max_retries exceeded)
# ✅ Manifest generation
# ✅ WHERE clause filtering
# ✅ Multi-step batch workflows
```

#### 2. Switch to Cloud for Production

```yaml
# Development/Testing:
model_vendor: ollama
model_name: llama3.2

# Production (just change 2 lines):
model_vendor: openai
model_name: gpt-4o-mini
```

#### 3. Validate Logic, Not Outputs

```yaml
# Use Ollama to test:
# ✅ Workflow logic
# ✅ Error handling
# ✅ Retry mechanisms
# ✅ File formats

# Use cloud APIs to test:
# ✅ Output quality
# ✅ Schema compliance
# ✅ Final results
```

### Complete Ollama Batch Example

```yaml
# workflows/ollama-batch-development.yml

# Local batch testing configuration
model_vendor: ollama
model_name: llama3.2
base_url: http://localhost:11434  # Optional
temperature: 0.7

actions:
  - name: analyze_feedback
    batch_mode: true
    batch_size: 50           # Small batch for local testing

    reads:
      - customer_feedback
      - feedback_id

    writes:
      - sentiment
      - key_issues
      - priority

    prompt: |
      Analyze this customer feedback:
      {{ customer_feedback }}

      Determine:
      1. Sentiment (positive/negative/neutral)
      2. Key issues mentioned
      3. Priority level (low/medium/high)

    schema:
      sentiment:
        type: string
        enum: [positive, negative, neutral]
      key_issues:
        type: array
        items: string
        minItems: 1
        maxItems: 5
      priority:
        type: string
        enum: [low, medium, high]
```

Run it:

```bash
# Test with sample data
agent-actions run ollama-batch-development --input feedback-sample-50.jsonl

# Output (immediate):
# 🔄 Processing batch with Ollama...
# ✅ Processed 50 items in 23 seconds
# 📁 Results: outputs/batch_20240115_143000/batch_results.jsonl
# 📊 Summary: 50 success, 0 failed

# Once validated, switch to production:
# 1. Change model_vendor to "openai"
# 2. Run with full dataset
agent-actions run ollama-batch-development --input feedback-full-5000.jsonl
```

## When to Use Batch Mode

✅ **Use batch mode when:**
- Processing thousands+ items
- Cost is more important than speed
- You can wait hours/days for results (cloud APIs)
- Data is ready upfront (not streaming)
- Using OpenAI, Anthropic, Gemini, or Ollama
- Testing batch workflows locally (use Ollama)
- Running in CI/CD without API costs (use Ollama)

❌ **Don't use batch mode when:**
- Need real-time results (unless testing with Ollama)
- Processing small datasets (less than 100 items, unless testing)
- Using unsupported vendors (Groq, DeepSeek, Perplexity)
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
