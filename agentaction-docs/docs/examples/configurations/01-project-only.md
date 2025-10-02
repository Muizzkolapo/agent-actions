# Example 1: Project-Level Configuration Only

This example demonstrates the simplest configuration approach: defining all settings at the project level in `agent_actions.yml`, with workflows containing only workflow-specific logic (actions, prompts, schemas).

## Use Case

Best for projects where:
- All workflows use the same LLM vendor and model
- Configuration is consistent across all tasks
- You want centralized control over model settings
- You're starting with Agent Actions and want simplicity

## Project Structure

```
my-project/
├── agent_actions.yml          # All configuration here
└── workflows/
    ├── summarize.yml          # Only workflow logic
    └── classify.yml           # Only workflow logic
```

## Configuration Files

### agent_actions.yml

```yaml
# Project-level configuration
# All workflows inherit these settings

# Model vendor and credentials
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

# Model parameters
temperature: 0.7
max_tokens: 2000
top_p: 1.0

# Optional: Additional settings that apply everywhere
# frequency_penalty: 0.0
# presence_penalty: 0.0
```

### workflows/summarize.yml

```yaml
# Simple workflow - no configuration, only logic
actions:
  - name: summarize

    reads:
      - article_text

    writes:
      - summary

    prompt: |
      Please provide a concise summary of the following article:

      {{ article_text }}

    schema:
      summary: string
```

### workflows/classify.yml

```yaml
# Another workflow - also inherits all settings from project
actions:
  - name: classify

    reads:
      - text

    writes:
      - category
      - confidence

    prompt: |
      Classify the following text into one of these categories:
      - Technology
      - Business
      - Science
      - Politics
      - Entertainment

      Text: {{ text }}

    schema:
      category:
        type: string
        enum: [Technology, Business, Science, Politics, Entertainment]
      confidence:
        type: number
        minimum: 0.0
        maximum: 1.0
```

## How Configuration Resolution Works

For **every action** in **every workflow**:

1. Start with project-level settings from `agent_actions.yml`
2. No workflow-level overrides (workflows don't specify model settings)
3. No action-level overrides (actions don't specify model settings)
4. **Result**: All actions use the same configuration from project level

**Final resolved configuration for ALL actions:**
```yaml
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7
max_tokens: 2000
top_p: 1.0
```

## Running the Workflows

```bash
# Both workflows use the same model configuration
agent-actions run summarize --input articles.jsonl
agent-actions run classify --input posts.jsonl
```

## Advantages

✅ **Simplicity**: One place to configure everything
✅ **Consistency**: All workflows behave the same way
✅ **Easy maintenance**: Change once, affects all workflows
✅ **Cost predictability**: Same model and settings everywhere
✅ **Quick setup**: Minimal configuration needed

## Limitations

❌ **No flexibility**: All actions must use the same vendor/model
❌ **Can't optimize per task**: Simple and complex tasks use same model
❌ **No vendor comparison**: Can't test different vendors easily
❌ **Potential waste**: Using expensive model for simple tasks

## When to Use This Pattern

✅ Use project-level configuration when:
- Starting a new project
- All tasks have similar complexity
- Budget allows using one good model everywhere
- Team prefers simplicity over optimization
- Prototyping and testing workflows

## Switching to Environment Variables

For better security, use environment variables:

```bash
# .env file (add to .gitignore!)
export OPENAI_API_KEY=sk-proj-...
```

```yaml
# agent_actions.yml
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}    # Reference env var
```

## Changing the Model for All Workflows

Simply update `agent_actions.yml`:

```yaml
# Switch to GPT-4o for better quality
model_vendor: openai
model_name: gpt-4o              # Changed from gpt-4o-mini
api_key: ${OPENAI_API_KEY}
temperature: 0.7
```

Now **all workflows** automatically use `gpt-4o` without any changes to workflow files.

## Testing Different Vendors

To test with Anthropic Claude:

```yaml
# agent_actions.yml
model_vendor: anthropic
model_name: claude-3-5-sonnet-20241022
api_key: ${ANTHROPIC_API_KEY}
temperature: 0.7
```

To test with Google Gemini:

```yaml
# agent_actions.yml
model_vendor: gemini
model_name: gemini-1.5-pro
api_key: ${GEMINI_API_KEY}
temperature: 0.7
```

All workflows will now use the new vendor - no workflow file changes needed.

## Next Steps

Once you need more flexibility, explore:
- [Example 2: Workflow-Level Overrides](./02-workflow-overrides.md) - Different settings per workflow
- [Example 3: Action-Level Overrides](./03-action-overrides.md) - Different settings per action
- [Example 4: Mixed Hierarchy](./04-mixed-hierarchy.md) - Combining all levels

## Complete Example

**Input data** (articles.jsonl):
```json
{"article_text": "The latest breakthrough in quantum computing..."}
{"article_text": "Market analysis shows significant growth..."}
```

**Run workflow**:
```bash
agent-actions run summarize --input articles.jsonl --output results.jsonl
```

**Output** (results.jsonl):
```json
{"article_text": "...", "summary": "Quantum computing breakthrough enables..."}
{"article_text": "...", "summary": "Market shows strong growth in..."}
```

All processing used the same configuration from `agent_actions.yml`:
- OpenAI GPT-4o-mini
- Temperature 0.7
- Max tokens 2000
