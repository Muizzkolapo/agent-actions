# Example 4: Mixed Hierarchy Configuration

This example demonstrates a complex real-world project using all three configuration levels (project, workflow, action) to create a flexible, cost-optimized setup.

## Use Case

Real-world production system with:
- Multiple workflows with different requirements
- Cost optimization across simple and complex tasks
- Multiple LLM vendors based on task needs
- Mix of online and batch processing
- Different temperature requirements per task type

## Project Structure

```
my-project/
├── agent_actions.yml                    # Project defaults
└── workflows/
    ├── simple/
    │   ├── classify.yml                 # Uses project defaults
    │   └── tag.yml                      # Uses project defaults
    ├── analysis/
    │   ├── basic-analysis.yml           # Workflow override
    │   └── deep-analysis.yml            # Workflow + action overrides
    └── creative/
        ├── content-generation.yml       # Different vendor per action
        └── story-pipeline.yml           # Multi-vendor workflow
```

## Configuration Files

### agent_actions.yml

```yaml
# ============================================================================
# PROJECT-LEVEL DEFAULTS
# ============================================================================
# Cost-effective baseline for routine tasks
# Most workflows (70%) use these defaults

# Default vendor: OpenAI (widely supported, reliable)
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

# Moderate settings for general use
temperature: 0.7
max_tokens: 2000
top_p: 1.0
```

### workflows/simple/classify.yml

```yaml
# ============================================================================
# SIMPLE WORKFLOW: Uses 100% Project Defaults
# ============================================================================
# No overrides needed - project config is perfect for this task

actions:
  - name: classify_text

    reads:
      - text

    writes:
      - category
      - confidence

    prompt: |
      Classify this text into one of: tech, business, science, politics

      {{ text }}

    schema:
      category:
        type: string
        enum: [tech, business, science, politics]
      confidence:
        type: number
        minimum: 0.0
        maximum: 1.0

# Final config (all inherited):
#   model_vendor: openai
#   model_name: gpt-4o-mini
#   api_key: ${OPENAI_API_KEY}
#   temperature: 0.7
#   max_tokens: 2000
```

### workflows/analysis/basic-analysis.yml

```yaml
# ============================================================================
# WORKFLOW-LEVEL OVERRIDE: Better Model for All Actions
# ============================================================================
# All actions in this workflow need better reasoning

# Override model for entire workflow
model_name: gpt-4o              # Upgrade from gpt-4o-mini
temperature: 0.6                # Lower for analytical work

actions:
  - name: identify_themes

    reads:
      - document

    writes:
      - themes

    prompt: |
      Identify main themes in: {{ document }}

    schema:
      themes:
        type: array
        items: string

  - name: extract_insights

    reads:
      - document
      - themes

    writes:
      - insights

    prompt: |
      Based on themes {{ themes | join(', ') }}, extract insights from:
      {{ document }}

    schema:
      insights:
        type: array
        items: string

# Both actions use:
#   model_vendor: openai          (from project)
#   model_name: gpt-4o            (from workflow)
#   api_key: ${OPENAI_API_KEY}    (from project)
#   temperature: 0.6              (from workflow)
#   max_tokens: 2000              (from project)
```

### workflows/analysis/deep-analysis.yml

```yaml
# ============================================================================
# WORKFLOW + ACTION OVERRIDES: Mixed Optimization
# ============================================================================
# Workflow baseline + per-action customization

# Workflow-level: Upgrade model for all actions
model_name: gpt-4o
max_tokens: 4000

actions:
  # Action 1: Uses workflow config (no action overrides)
  - name: extract_data

    reads:
      - document

    writes:
      - extracted_data

    prompt: |
      Extract structured data from: {{ document }}

    schema:
      extracted_data:
        type: object

    # Uses workflow config:
    # - model_vendor: openai (project)
    # - model_name: gpt-4o (workflow)
    # - temperature: 0.7 (project)

  # Action 2: Action override for structured extraction
  - name: parse_entities

    reads:
      - extracted_data

    writes:
      - entities

    prompt: |
      Parse entities from: {{ extracted_data }}

    schema:
      entities:
        type: array
        items:
          type: object

    # Override temperature for consistency
    temperature: 0.2

    # Uses:
    # - model_vendor: openai (project)
    # - model_name: gpt-4o (workflow)
    # - temperature: 0.2 (ACTION OVERRIDE)
    # - max_tokens: 4000 (workflow)

  # Action 3: Different vendor for reasoning
  - name: deep_reasoning

    reads:
      - document
      - entities

    writes:
      - analysis

    prompt: |
      Perform deep analysis on: {{ document }}
      Considering entities: {{ entities }}

    schema:
      analysis: string

    # Switch to Anthropic Claude for superior reasoning
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    api_key: ${ANTHROPIC_API_KEY}
    temperature: 0.7

    # Uses:
    # - model_vendor: anthropic (ACTION OVERRIDE)
    # - model_name: claude-3.5-sonnet (ACTION OVERRIDE)
    # - api_key: ${ANTHROPIC_API_KEY} (ACTION OVERRIDE)
    # - temperature: 0.7 (ACTION OVERRIDE)
    # - max_tokens: 4000 (workflow - inherited)
```

### workflows/creative/content-generation.yml

```yaml
# ============================================================================
# MULTI-VENDOR WORKFLOW: Different Vendor Per Action
# ============================================================================
# Each action uses the best vendor for its task

# Workflow-level: Set higher temperature baseline
temperature: 0.8
max_tokens: 3000

actions:
  # Action 1: OpenAI for outline (uses project + workflow)
  - name: create_outline

    reads:
      - topic

    writes:
      - outline

    prompt: |
      Create an outline for: {{ topic }}

    schema:
      outline:
        type: array
        items: string

    # Uses:
    # - model_vendor: openai (project)
    # - model_name: gpt-4o-mini (project)
    # - temperature: 0.8 (workflow)
    # - max_tokens: 3000 (workflow)

  # Action 2: Claude for creative writing
  - name: write_content

    reads:
      - topic
      - outline

    writes:
      - content

    prompt: |
      Write engaging content about {{ topic }}
      Following outline: {{ outline | join('\n') }}

    schema:
      content: string

    # Switch to Claude for creative tasks
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    api_key: ${ANTHROPIC_API_KEY}
    temperature: 0.9

    # Uses:
    # - model_vendor: anthropic (ACTION)
    # - model_name: claude-3.5-sonnet (ACTION)
    # - temperature: 0.9 (ACTION)
    # - max_tokens: 3000 (workflow)

  # Action 3: Gemini for enhancement
  - name: enhance_content

    reads:
      - content

    writes:
      - enhanced_content

    prompt: |
      Enhance this content with examples and details:
      {{ content }}

    schema:
      enhanced_content: string

    # Use Gemini for large context
    model_vendor: gemini
    model_name: gemini-1.5-pro
    api_key: ${GEMINI_API_KEY}

    # Uses:
    # - model_vendor: gemini (ACTION)
    # - model_name: gemini-1.5-pro (ACTION)
    # - temperature: 0.8 (workflow)
    # - max_tokens: 3000 (workflow)

  # Action 4: Groq for fast editing
  - name: quick_edit

    reads:
      - enhanced_content

    writes:
      - final_content

    prompt: |
      Quick edit for grammar and flow:
      {{ enhanced_content }}

    schema:
      final_content: string

    # Use Groq for speed
    model_vendor: groq
    model_name: llama-3.1-70b-versatile
    api_key: ${GROQ_API_KEY}
    temperature: 0.5

    # Uses:
    # - model_vendor: groq (ACTION)
    # - model_name: llama-3.1 (ACTION)
    # - temperature: 0.5 (ACTION)
    # - max_tokens: 3000 (workflow)
```

## Configuration Resolution Summary

| Workflow | Action | Vendor | Model | Temp | Max Tokens | Source |
|----------|--------|--------|-------|------|------------|--------|
| classify | classify_text | openai | gpt-4o-mini | 0.7 | 2000 | P/P/P/P |
| basic-analysis | identify_themes | openai | gpt-4o | 0.6 | 2000 | P/W/W/P |
| basic-analysis | extract_insights | openai | gpt-4o | 0.6 | 2000 | P/W/W/P |
| deep-analysis | extract_data | openai | gpt-4o | 0.7 | 4000 | P/W/P/W |
| deep-analysis | parse_entities | openai | gpt-4o | 0.2 | 4000 | P/W/A/W |
| deep-analysis | deep_reasoning | anthropic | claude-3.5 | 0.7 | 4000 | A/A/A/W |
| content-gen | create_outline | openai | gpt-4o-mini | 0.8 | 3000 | P/P/W/W |
| content-gen | write_content | anthropic | claude-3.5 | 0.9 | 3000 | A/A/A/W |
| content-gen | enhance_content | gemini | gemini-1.5 | 0.8 | 3000 | A/A/W/W |
| content-gen | quick_edit | groq | llama-3.1 | 0.5 | 3000 | A/A/A/W |

**Legend**: P=Project, W=Workflow, A=Action

## Cost Analysis

Estimated costs per item (2000 input + 1000 output tokens):

### classify workflow
- **Total**: $0.00075 (gpt-4o-mini)

### basic-analysis workflow (2 actions)
- identify_themes: $0.0125 (gpt-4o)
- extract_insights: $0.0125 (gpt-4o)
- **Total**: $0.025

### deep-analysis workflow (3 actions)
- extract_data: $0.0125 (gpt-4o)
- parse_entities: $0.0125 (gpt-4o)
- deep_reasoning: $0.0225 (claude-3.5)
- **Total**: $0.0475

### content-generation workflow (4 actions)
- create_outline: $0.00075 (gpt-4o-mini)
- write_content: $0.0225 (claude-3.5)
- enhance_content: $0.0188 (gemini-1.5)
- quick_edit: $0.0013 (groq)
- **Total**: $0.0434

**Project-wide average**: ~$0.030 per item

## Decision Rationale

### Why gpt-4o-mini as project default?
✅ Cost-effective for 70% of tasks
✅ Fast response times
✅ Good enough quality for simple tasks
✅ Can upgrade where needed

### Why workflow-level overrides?
✅ basic-analysis: All actions need same better model
✅ Easier than repeating action overrides
✅ Clear intent: "this whole workflow is premium"

### Why action-level overrides?
✅ deep-analysis: Mix of extraction (gpt-4o) + reasoning (claude)
✅ content-generation: Each step has different optimal vendor
✅ Fine-grained cost optimization
✅ Leverage vendor strengths

## Running the Workflows

```bash
# Simple classification (cheap, fast)
agent-actions run workflows/simple/classify.yml --input posts.jsonl

# Basic analysis (moderate cost)
agent-actions run workflows/analysis/basic-analysis.yml --input docs.jsonl

# Deep analysis (higher cost, best quality)
agent-actions run workflows/analysis/deep-analysis.yml --input reports.jsonl

# Content generation (multi-vendor pipeline)
agent-actions run workflows/creative/content-generation.yml --input topics.jsonl
```

## Best Practices Demonstrated

### 1. Sensible Project Defaults
Choose the model 70%+ of your tasks can use:
```yaml
# Good default: covers most use cases
model_name: gpt-4o-mini
```

### 2. Workflow Overrides for Consistency
When ALL actions need the same upgrade:
```yaml
# Workflow level
model_name: gpt-4o

actions:
  - name: action1    # Inherits gpt-4o
  - name: action2    # Inherits gpt-4o
```

### 3. Action Overrides for Optimization
When actions have different needs:
```yaml
actions:
  - name: simple_task
    # Uses project defaults (gpt-4o-mini)

  - name: complex_task
    model_name: gpt-4o    # Upgrade just this action
```

### 4. Vendor Selection per Strength
```yaml
actions:
  - name: reasoning
    model_vendor: anthropic    # Best reasoning

  - name: speed
    model_vendor: groq         # Fastest

  - name: search
    model_vendor: perplexity   # Web search

  - name: budget
    model_vendor: deepseek     # Cheapest
```

### 5. Temperature by Task Type
```yaml
# Structured extraction
temperature: 0.2

# Analysis
temperature: 0.6

# Creative writing
temperature: 0.9
```

## Common Patterns

### Pattern 1: "Mostly Cheap, Some Premium"
```yaml
# Project: cheap default
model_name: gpt-4o-mini

# Workflow: most use defaults
actions:
  - name: cheap1    # gpt-4o-mini
  - name: cheap2    # gpt-4o-mini
  - name: premium   # Override to gpt-4o
    model_name: gpt-4o
```

### Pattern 2: "Premium Workflow with One Fast Action"
```yaml
# Workflow: premium default
model_name: gpt-4o

actions:
  - name: premium1  # gpt-4o
  - name: premium2  # gpt-4o
  - name: fast      # Override to groq
    model_vendor: groq
```

### Pattern 3: "Multi-Vendor Pipeline"
```yaml
# Workflow: set common params
temperature: 0.7
max_tokens: 3000

actions:
  - name: openai_step
    model_vendor: openai
  - name: claude_step
    model_vendor: anthropic
  - name: gemini_step
    model_vendor: gemini
```

## When to Use This Pattern

✅ Use mixed hierarchy when:
- Production system with diverse workflows
- Cost optimization is critical
- Want to leverage multiple vendors
- Different workflows have different quality needs
- Balancing cost, quality, and performance

## Next Steps

- [Example 5: Environment Variables](./05-environment-variables.md) - Managing API keys
- [Example 6: Tool Actions](./06-tool-actions.md) - Non-LLM actions
- [Example 7: Batch Mode](./07-batch-mode.md) - High-volume processing

## Complete Example

Clone this structure for your project:

```bash
# Create project structure
mkdir -p my-project/workflows/{simple,analysis,creative}

# Copy agent_actions.yml
cp templates/agent_actions.yml.template my-project/agent_actions.yml

# Set environment variables
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...
export GROQ_API_KEY=...

# Run workflows
cd my-project
agent-actions run workflows/simple/classify.yml --input data.jsonl
```

This gives you a flexible, cost-optimized, multi-vendor setup ready for production.
