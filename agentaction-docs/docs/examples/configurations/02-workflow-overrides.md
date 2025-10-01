# Example 2: Workflow-Level Overrides

This example demonstrates using workflow-level configuration to customize settings for different workflows while maintaining project-level defaults.

## Use Case

Best for projects where:
- Different workflows have different requirements
- Some workflows need better models, others can use cheaper ones
- You want to test different vendors for different tasks
- Cost optimization is important

## Project Structure

```
my-project/
├── agent_actions.yml          # Base defaults
└── workflows/
    ├── quick-classify.yml     # Uses project defaults (cheap, fast)
    ├── deep-analysis.yml      # Overrides to better model
    └── creative-writing.yml   # Overrides to high temperature
```

## Configuration Files

### agent_actions.yml

```yaml
# Project-level defaults
# Cost-effective baseline for most tasks
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7
max_tokens: 1500
```

### workflows/quick-classify.yml

```yaml
# Uses project defaults - no overrides needed
# Fast and cheap classification
actions:
  - name: classify

    reads:
      - text

    writes:
      - category

    prompt: |
      Classify this text: {{ text }}

      Categories: tech, business, science, politics, entertainment

    schema:
      category: string

# Configuration: Inherits from project
# - model_vendor: openai
# - model_name: gpt-4o-mini
# - api_key: ${OPENAI_API_KEY}
# - temperature: 0.7
# - max_tokens: 1500
```

### workflows/deep-analysis.yml

```yaml
# Override to use better model for complex analysis
# Worth the extra cost for quality

# Workflow-level overrides
model_name: gpt-4o              # Upgrade from gpt-4o-mini
temperature: 0.6                # Slightly lower for analysis
max_tokens: 4000                # More tokens for detailed output

actions:
  - name: analyze

    reads:
      - document

    writes:
      - analysis
      - insights
      - recommendations

    prompt: |
      Perform a comprehensive analysis of this document:

      {{ document }}

      Provide:
      1. Detailed thematic analysis
      2. Key insights and patterns
      3. Actionable recommendations

    schema:
      analysis: string
      insights:
        type: array
        items: string
      recommendations:
        type: array
        items: string

# Configuration: Merges workflow overrides with project defaults
# - model_vendor: openai          (from project)
# - model_name: gpt-4o            (OVERRIDDEN)
# - api_key: ${OPENAI_API_KEY}    (from project)
# - temperature: 0.6              (OVERRIDDEN)
# - max_tokens: 4000              (OVERRIDDEN)
```

### workflows/creative-writing.yml

```yaml
# Override temperature for creative tasks
# Keep same model but adjust creativity

# Workflow-level overrides
temperature: 1.0                # High creativity
max_tokens: 3000                # Space for creative output

actions:
  - name: generate_story

    reads:
      - prompt
      - style

    writes:
      - story

    prompt: |
      Write a creative story based on this prompt:

      {{ prompt }}

      Style: {{ style }}

    schema:
      story: string

  - name: enhance_narrative

    reads:
      - story

    writes:
      - enhanced_story

    prompt: |
      Enhance this story with more vivid descriptions and dialogue:

      {{ story }}

    schema:
      enhanced_story: string

# Configuration: All actions in this workflow use
# - model_vendor: openai          (from project)
# - model_name: gpt-4o-mini       (from project)
# - api_key: ${OPENAI_API_KEY}    (from project)
# - temperature: 1.0              (OVERRIDDEN)
# - max_tokens: 3000              (OVERRIDDEN)
```

## Configuration Resolution Examples

### quick-classify workflow

```yaml
# Final configuration (fully inherited from project)
model_vendor: openai           # From project
model_name: gpt-4o-mini        # From project
api_key: ${OPENAI_API_KEY}     # From project
temperature: 0.7               # From project
max_tokens: 1500               # From project
```

### deep-analysis workflow

```yaml
# Final configuration (project + workflow overrides)
model_vendor: openai           # From project (inherited)
model_name: gpt-4o             # From workflow (OVERRIDDEN)
api_key: ${OPENAI_API_KEY}     # From project (inherited)
temperature: 0.6               # From workflow (OVERRIDDEN)
max_tokens: 4000               # From workflow (OVERRIDDEN)
```

### creative-writing workflow

```yaml
# Final configuration (project + workflow overrides)
model_vendor: openai           # From project (inherited)
model_name: gpt-4o-mini        # From project (inherited)
api_key: ${OPENAI_API_KEY}     # From project (inherited)
temperature: 1.0               # From workflow (OVERRIDDEN)
max_tokens: 3000               # From workflow (OVERRIDDEN)
```

## Running the Workflows

```bash
# Fast, cheap classification
agent-actions run quick-classify --input posts.jsonl

# High-quality analysis (costs more)
agent-actions run deep-analysis --input reports.jsonl

# Creative generation
agent-actions run creative-writing --input prompts.jsonl
```

## Cost Comparison

Assuming 1000 input tokens, 500 output tokens per item:

**quick-classify** (gpt-4o-mini):
- Input: 1000 tokens × $0.00015 = $0.00015
- Output: 500 tokens × $0.00060 = $0.00030
- **Total: $0.00045 per item**

**deep-analysis** (gpt-4o):
- Input: 1000 tokens × $0.0025 = $0.0025
- Output: 500 tokens × $0.0100 = $0.0050
- **Total: $0.0075 per item** (16.7x more expensive)

**creative-writing** (gpt-4o-mini):
- Input: 1000 tokens × $0.00015 = $0.00015
- Output: 500 tokens × $0.00060 = $0.00030
- **Total: $0.00045 per item**

> **Strategy**: Use cheap models where quality difference is minimal, expensive models only where justified.

## Testing Different Vendors Per Workflow

You can test different vendors for different workflows:

```yaml
# workflows/anthropic-test.yml
model_vendor: anthropic
model_name: claude-3-5-sonnet-20241022
api_key: ${ANTHROPIC_API_KEY}
temperature: 0.7

actions:
  - name: test_claude
    # ... action definition
```

```yaml
# workflows/gemini-test.yml
model_vendor: gemini
model_name: gemini-1.5-pro
api_key: ${GEMINI_API_KEY}
temperature: 0.7

actions:
  - name: test_gemini
    # ... action definition
```

Now you can run the same data through different vendors and compare results.

## Advantages

✅ **Optimization**: Use expensive models only where needed
✅ **Flexibility**: Each workflow can have different settings
✅ **Cost control**: Balance quality and cost per workflow
✅ **Easy comparison**: Test vendors without changing project config
✅ **Maintainability**: Common settings still in project file

## Limitations

❌ **Multiple configs**: Need to maintain workflow-level settings
❌ **Less granular**: All actions in workflow share same overrides
❌ **Can't mix vendors**: All actions in workflow use same vendor

## Best Practices

### 1. Override Strategically

Only override what's necessary:

```yaml
# Good: Override just what you need
model_name: gpt-4o
temperature: 0.6

# Avoid: Re-declaring everything
# model_vendor: openai          # Don't repeat if unchanged
# api_key: ${OPENAI_API_KEY}    # Don't repeat if unchanged
# model_name: gpt-4o            # Only include changes
```

### 2. Document Why You Override

```yaml
# workflows/legal-review.yml

# Use GPT-4o for legal accuracy (critical task)
model_name: gpt-4o
temperature: 0.3    # Low temperature for consistency

actions:
  - name: review_contract
    # ...
```

### 3. Group Similar Workflows

```
workflows/
├── cheap/
│   ├── classify.yml          # All use project defaults
│   ├── tag.yml
│   └── extract.yml
├── expensive/
│   ├── analyze.yml           # All override to gpt-4o
│   ├── research.yml
│   └── legal.yml
└── creative/
    ├── write.yml             # All use high temperature
    └── brainstorm.yml
```

## When to Use This Pattern

✅ Use workflow-level overrides when:
- Different workflows have different quality requirements
- Optimizing costs across workflows
- Testing different vendors for specific use cases
- Workflows have distinct temperature/parameter needs

## Next Steps

For even more control, explore:
- [Example 3: Action-Level Overrides](./03-action-overrides.md) - Different models per action
- [Example 4: Mixed Hierarchy](./04-mixed-hierarchy.md) - Combining all levels
- [Example 1: Project-Only](./01-project-only.md) - Simpler alternative

## Complete Example

**agent_actions.yml**:
```yaml
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7
```

**workflows/premium-analysis.yml**:
```yaml
model_name: gpt-4o      # Override for quality
temperature: 0.5        # Override for consistency

actions:
  - name: analyze
    reads: [text]
    writes: [analysis]
    prompt: "Analyze: {{ text }}"
    schema:
      analysis: string
```

**Result**: `analyze` action uses:
- `gpt-4o` (from workflow override)
- Temperature 0.5 (from workflow override)
- `openai` vendor (inherited from project)
- `${OPENAI_API_KEY}` (inherited from project)
