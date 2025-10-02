# Example 3: Action-Level Overrides

This example demonstrates using action-level configuration to customize settings for individual actions within a workflow, providing maximum flexibility for optimization.

## Use Case

Best for workflows where:
- Actions within a single workflow have different complexity levels
- You want fine-grained cost optimization
- Different actions benefit from different vendors
- Mixing structured extraction with creative tasks

## Project Structure

```
my-project/
├── agent_actions.yml          # Base defaults
└── workflows/
    └── content-pipeline.yml   # Multiple actions with different configs
```

## Configuration Files

### agent_actions.yml

```yaml
# Project-level defaults (cost-effective baseline)
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7
max_tokens: 2000
```

### workflows/content-pipeline.yml

```yaml
# Workflow uses project defaults unless action overrides
# This workflow has 5 actions, each optimized differently

actions:
  # ACTION 1: Simple extraction - use project defaults
  - name: extract_metadata

    reads:
      - raw_text

    writes:
      - title
      - author
      - date

    prompt: |
      Extract metadata from this text:
      {{ raw_text }}

    schema:
      title: string
      author: string
      date: string

    # No overrides - uses project defaults:
    # - model_vendor: openai (gpt-4o-mini is fine for this)
    # - temperature: 0.7
    # - max_tokens: 2000

  # ACTION 2: Structured extraction - lower temperature
  - name: extract_entities

    reads:
      - raw_text

    writes:
      - entities
      - relationships

    prompt: |
      Extract entities and relationships from:
      {{ raw_text }}

    schema:
      entities:
        type: array
        items:
          type: object
          properties:
            name: string
            type: string
      relationships:
        type: array
        items: string

    # Override temperature only (structured task needs consistency)
    temperature: 0.2

    # Uses from project:
    # - model_vendor: openai
    # - model_name: gpt-4o-mini (cheap model is fine)
    # - api_key: ${OPENAI_API_KEY}
    # - max_tokens: 2000

  # ACTION 3: Deep analysis - upgrade to better model
  - name: analyze_content

    reads:
      - raw_text
      - entities
      - relationships

    writes:
      - analysis
      - insights

    prompt: |
      Analyze this content comprehensively:

      Text: {{ raw_text }}
      Entities: {{ entities }}
      Relationships: {{ relationships }}

      Provide deep thematic analysis and insights.

    schema:
      analysis: string
      insights:
        type: array
        items: string

    # Override to better model for complex reasoning
    model_name: gpt-4o
    temperature: 0.6
    max_tokens: 4000

    # Uses from project:
    # - model_vendor: openai
    # - api_key: ${OPENAI_API_KEY}

  # ACTION 4: Creative summary - different vendor + high temp
  - name: create_summary

    reads:
      - raw_text
      - analysis
      - insights

    writes:
      - creative_summary

    prompt: |
      Create an engaging summary of this content:

      Text: {{ raw_text }}
      Analysis: {{ analysis }}
      Key Insights: {{ insights | join(', ') }}

      Make it compelling and reader-friendly.

    schema:
      creative_summary: string

    # Switch to Anthropic for creative writing
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    api_key: ${ANTHROPIC_API_KEY}
    temperature: 0.9
    max_tokens: 3000

    # No fields inherited from project (complete override)

  # ACTION 5: Fast classification - use Groq for speed
  - name: classify_content

    reads:
      - raw_text
      - creative_summary

    writes:
      - category
      - tags
      - priority

    prompt: |
      Classify this content quickly:

      Text: {{ raw_text }}
      Summary: {{ creative_summary }}

    schema:
      category: string
      tags:
        type: array
        items: string
      priority:
        type: string
        enum: [high, medium, low]

    # Use Groq for fast inference
    model_vendor: groq
    model_name: llama-3.1-70b-versatile
    api_key: ${GROQ_API_KEY}
    temperature: 0.3

    # Inherits max_tokens: 2000 from project
```

## Configuration Resolution

Each action gets its unique final configuration:

### Action 1: extract_metadata
```yaml
model_vendor: openai           # From project
model_name: gpt-4o-mini        # From project
api_key: ${OPENAI_API_KEY}     # From project
temperature: 0.7               # From project
max_tokens: 2000               # From project
```

### Action 2: extract_entities
```yaml
model_vendor: openai           # From project
model_name: gpt-4o-mini        # From project
api_key: ${OPENAI_API_KEY}     # From project
temperature: 0.2               # OVERRIDDEN by action
max_tokens: 2000               # From project
```

### Action 3: analyze_content
```yaml
model_vendor: openai           # From project
model_name: gpt-4o             # OVERRIDDEN by action
api_key: ${OPENAI_API_KEY}     # From project
temperature: 0.6               # OVERRIDDEN by action
max_tokens: 4000               # OVERRIDDEN by action
```

### Action 4: create_summary
```yaml
model_vendor: anthropic        # OVERRIDDEN by action
model_name: claude-3-5-sonnet-20241022  # OVERRIDDEN by action
api_key: ${ANTHROPIC_API_KEY}  # OVERRIDDEN by action
temperature: 0.9               # OVERRIDDEN by action
max_tokens: 3000               # OVERRIDDEN by action
```

### Action 5: classify_content
```yaml
model_vendor: groq             # OVERRIDDEN by action
model_name: llama-3.1-70b-versatile  # OVERRIDDEN by action
api_key: ${GROQ_API_KEY}       # OVERRIDDEN by action
temperature: 0.3               # OVERRIDDEN by action
max_tokens: 2000               # From project (inherited)
```

## Data Flow

```
Input: { raw_text: "Article content..." }
   ↓
[extract_metadata] (gpt-4o-mini, temp=0.7)
   Adds: title, author, date
   ↓
[extract_entities] (gpt-4o-mini, temp=0.2)
   Adds: entities, relationships
   ↓
[analyze_content] (gpt-4o, temp=0.6)
   Adds: analysis, insights
   ↓
[create_summary] (claude-3.5-sonnet, temp=0.9)
   Adds: creative_summary
   ↓
[classify_content] (groq llama-3.1, temp=0.3)
   Adds: category, tags, priority
   ↓
Output: { all accumulated fields }
```

## Cost Analysis Per Item

Assuming 2000 input tokens per action:

| Action | Model | Input Cost | Output Cost | Total |
|--------|-------|------------|-------------|-------|
| extract_metadata | gpt-4o-mini | $0.0003 | $0.0006 | $0.0009 |
| extract_entities | gpt-4o-mini | $0.0003 | $0.0006 | $0.0009 |
| analyze_content | gpt-4o | $0.0050 | $0.0200 | $0.0250 |
| create_summary | claude-3.5 | $0.0060 | $0.0375 | $0.0435 |
| classify_content | groq llama | $0.0005 | $0.0020 | $0.0025 |
| **Total per item** | | | | **$0.0728** |

Compare to using gpt-4o for everything: ~$0.25 per item (3.4x more expensive)

## Running the Workflow

```bash
agent-actions run content-pipeline --input articles.jsonl --output processed.jsonl
```

Each action will use its optimized configuration automatically.

## Advantages

✅ **Maximum optimization**: Each action uses optimal model/settings
✅ **Cost efficiency**: Use expensive models only where needed
✅ **Multi-vendor**: Leverage strengths of different vendors
✅ **Fine-grained control**: Customize every parameter per action
✅ **Performance**: Fast models for simple tasks, powerful for complex

## Limitations

❌ **Complexity**: Need to understand each action's requirements
❌ **Maintenance**: More configurations to manage
❌ **Testing**: Harder to test with so many configurations
❌ **Debugging**: More variables when troubleshooting

## Best Practices

### 1. Start Simple, Optimize Later

Begin with project defaults, profile to find bottlenecks:

```yaml
# First iteration: all use defaults
actions:
  - name: extract
    # ... (uses project defaults)

  - name: analyze
    # ... (uses project defaults)

  - name: summarize
    # ... (uses project defaults)
```

After profiling, optimize selectively:

```yaml
# Second iteration: optimize the expensive action
actions:
  - name: extract
    # ... (still uses defaults - cheap task)

  - name: analyze
    model_name: gpt-4o    # Upgrade - this is the bottleneck
    # ...

  - name: summarize
    # ... (still uses defaults - cheap task)
```

### 2. Document Your Decisions

```yaml
actions:
  - name: legal_review
    # Use GPT-4o for legal accuracy (critical, worth the cost)
    model_name: gpt-4o
    temperature: 0.2      # Low temp for consistency
    # ...

  - name: tag_content
    # Use Groq for speed (latency-sensitive)
    model_vendor: groq
    model_name: llama-3.1-70b-versatile
    # ...
```

### 3. Group Similar Actions

If multiple actions need the same overrides, use workflow-level config:

```yaml
# BAD: Repeating same overrides
actions:
  - name: action1
    model_name: gpt-4o
    temperature: 0.5
    # ...

  - name: action2
    model_name: gpt-4o
    temperature: 0.5
    # ...

# GOOD: Use workflow-level override
model_name: gpt-4o
temperature: 0.5

actions:
  - name: action1
    # Inherits workflow config

  - name: action2
    # Inherits workflow config
```

### 4. Temperature Guidelines

```yaml
# Structured extraction: 0.0-0.3
temperature: 0.2

# Analysis: 0.4-0.6
temperature: 0.5

# General tasks: 0.7-0.8
temperature: 0.7

# Creative writing: 0.9-1.2
temperature: 1.0
```

### 5. Model Selection Strategy

```yaml
# Simple tasks: gpt-4o-mini
model_name: gpt-4o-mini

# Complex reasoning: gpt-4o or claude-3.5-sonnet
model_name: gpt-4o

# Speed-critical: groq
model_vendor: groq

# Research/current info: perplexity
model_vendor: perplexity

# Cost-sensitive: deepseek
model_vendor: deepseek
```

## When to Use This Pattern

✅ Use action-level overrides when:
- Actions within a workflow have very different requirements
- Cost optimization is critical
- You want to leverage multiple vendors' strengths
- Prototyping and A/B testing different models per action

## Combining with Workflow Overrides

You can combine workflow and action overrides:

```yaml
# workflows/mixed-optimization.yml

# Workflow-level: Set baseline different from project
model_vendor: anthropic
model_name: claude-3-5-sonnet-20241022
api_key: ${ANTHROPIC_API_KEY}
temperature: 0.7

actions:
  # Action 1: Uses workflow baseline
  - name: default_action
    # Uses claude-3.5-sonnet

  # Action 2: Partial override
  - name: creative_action
    temperature: 1.0      # Override just temperature
    # Still uses claude-3.5-sonnet

  # Action 3: Complete override
  - name: cheap_action
    model_vendor: openai  # Switch vendor completely
    model_name: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    temperature: 0.5
```

## Next Steps

- [Example 4: Mixed Hierarchy](./04-mixed-hierarchy.md) - Complex real-world example
- [Example 5: Environment Variables](./05-environment-variables.md) - Managing API keys
- [Example 2: Workflow Overrides](./02-workflow-overrides.md) - Simpler alternative

## Complete Working Example

**Input** (article.jsonl):
```json
{"raw_text": "The quantum computing breakthrough announced today..."}
```

**Run**:
```bash
agent-actions run content-pipeline --input article.jsonl --output result.jsonl
```

**Output** (result.jsonl):
```json
{
  "raw_text": "The quantum computing breakthrough...",
  "title": "Quantum Computing Breakthrough",
  "author": "Unknown",
  "date": "2024-01-15",
  "entities": [...],
  "relationships": [...],
  "analysis": "This article discusses a significant advancement...",
  "insights": ["Insight 1", "Insight 2", "Insight 3"],
  "creative_summary": "In a groundbreaking development...",
  "category": "Technology",
  "tags": ["quantum", "computing", "science"],
  "priority": "high"
}
```

Each field was generated by a different action with optimized configuration.
