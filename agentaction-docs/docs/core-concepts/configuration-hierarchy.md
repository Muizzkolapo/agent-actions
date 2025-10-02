# Configuration Hierarchy

Agent-actions uses a powerful 3-level configuration hierarchy that allows you to set defaults at different scopes, making your workflows more maintainable and reducing duplication.

## Overview

The configuration system has three levels, each with increasing specificity:

```
┌─────────────────────────────────────────────────┐
│  1. Project Level (agent_actions.yml)          │
│     └─ Org-wide defaults for all workflows     │
│                                                 │
│  2. Workflow Level (defaults section)          │
│     └─ Workflow-specific settings              │
│                                                 │
│  3. Action Level (individual action config)    │
│     └─ Action-specific overrides               │
└─────────────────────────────────────────────────┘
```

### Precedence Order

When the same configuration field is specified at multiple levels:

**Action > Workflow > Project**

This means:
- Action-level settings override everything
- Workflow-level settings override project-level
- Project-level provides the base defaults

## The Three Levels Explained

### Level 1: Project Configuration

**File**: `agent_actions.yml` (at your project root)

**Purpose**: Organization-wide defaults that apply to ALL workflows in your project.

**Use when**: You want consistent settings across multiple workflows (e.g., same model, API keys, chunking settings).

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
  chunk_config:
    chunk_size: 500
    chunk_overlap: 50
  json_mode: true
```

### Level 2: Workflow Configuration

**File**: Your workflow YAML file (e.g., `workflows/data_extraction.yml`)

**Purpose**: Settings specific to this workflow that override project defaults.

**Use when**: A particular workflow needs different settings than the project default.

```yaml
# workflows/data_extraction.yml
name: data_extraction
description: Extract structured data from documents

defaults:
  model_vendor: openai              # Override project vendor
  model_name: gpt-4o-mini          # Override project model
  granularity: file           # Workflow-specific setting

actions:
  - name: extract
    # ... action configuration
```

### Level 3: Action Configuration

**File**: Same workflow YAML file (individual action within the `actions` list)

**Purpose**: Settings for a specific action that override both workflow and project defaults.

**Use when**: One particular action needs different configuration than the rest of the workflow.

```yaml
actions:
  - name: extract_with_different_model
    model_vendor: anthropic          # This action uses different model
    model_name: claude-3-5-sonnet-20241022
    few_shot: 5                # Action-specific setting
    prompt: "Extract key information..."
```

## Field Name Consistency

All configuration levels now use the same explicit field names:

- `model_vendor` - The LLM provider (openai, anthropic, etc.)
- `model_name` - The specific model to use (gpt-4, claude-3-sonnet, etc.)

This consistency ensures clarity across project, workflow, and action levels.


### Why Different Names?

This is due to historical reasons and backward compatibility:

- **Project-level** (`agent_actions.yml`) was added later and uses more explicit names (`model_vendor`, `model_name`)
- **Workflow/Action-level** uses shorter, more convenient names (`vendor`, `model`)

### What Should You Use?

**Use the appropriate field name for each level:**

✅ **Correct**:
```yaml
# agent_actions.yml (project-level)
default_agent_config:
  model_vendor: anthropic    # ✓ Use model_vendor at project level
  model_name: claude-3-5-sonnet  # ✓ Use model_name at project level

# workflow.yml (workflow/action level)
defaults:
  model_vendor: anthropic          # ✓ Use vendor at workflow level
  model_name: claude-3-5-sonnet   # ✓ Use model at workflow level
```

**The system handles the translation automatically** - you don't need to worry about converting between them.

## Configuration Examples

### Example 1: Project Defaults Only

The simplest setup - all workflows use the same configuration from project level.

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
  json_mode: true
  chunk_config:
    chunk_size: 500
    chunk_overlap: 50
```

```yaml
# workflows/extract_data.yml
name: extract_data
description: Extract structured data

actions:
  - name: extract_fields
    prompt: "Extract the following fields..."
    schema: person_schema
    # ✓ Inherits ALL settings from project level:
    #   - model_vendor: anthropic (from model_vendor)
    #   - model_name: claude-3-5-sonnet-20241022 (from model_name)
    #   - api_key: ${ANTHROPIC_API_KEY}
    #   - json_mode: true
    #   - chunk_config with size 500, overlap 50
```

**Result**: The action uses Anthropic's Claude 3.5 Sonnet with all the project defaults.

---

### Example 2: Workflow Overrides Project

One workflow needs different settings than the project default.

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
  chunk_config:
    chunk_size: 500
```

```yaml
# workflows/budget_analysis.yml
name: budget_analysis
description: Analyze budget using cheaper model

defaults:
  model_vendor: openai           # ← Override: use OpenAI instead
  model_name: gpt-4o-mini       # ← Override: use cheaper model
  api_key: ${OPENAI_API_KEY}  # ← Override: different API key

actions:
  - name: analyze_budget
    prompt: "Analyze the budget data..."
    # ✓ Uses workflow defaults:
    #   - model_vendor: openai (overridden at workflow level)
    #   - model_name: gpt-4o-mini (overridden at workflow level)
    #   - api_key: ${OPENAI_API_KEY} (overridden at workflow level)
    #   - chunk_config: size 500 (inherited from project)

  - name: summarize_findings
    prompt: "Summarize the budget analysis..."
    # ✓ Also uses workflow defaults (openai/gpt-4o-mini)
```

**Result**: All actions in this workflow use OpenAI's GPT-4o-mini, while other workflows still use Anthropic.

---

### Example 3: Action Overrides Everything

One action in a workflow needs completely different configuration.

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-haiku-20241022
  api_key: ${ANTHROPIC_API_KEY}
```

```yaml
# workflows/content_pipeline.yml
name: content_pipeline
description: Multi-step content processing

defaults:
  model_vendor: anthropic
  model_name: claude-3-5-haiku-20241022
  granularity: record

actions:
  - name: extract_content
    prompt: "Extract content from documents..."
    # ✓ Uses workflow/project defaults (claude-3-5-haiku)

  - name: deep_analysis
    model_vendor: anthropic         # ← Override at action level
    model_name: claude-3-5-sonnet-20241022  # ← Use more powerful model
    few_shot: 5               # ← Action-specific setting
    prompt: "Perform deep analysis..."
    # ✓ Uses action-level overrides:
    #   - model_vendor: anthropic (from action)
    #   - model_name: claude-3-5-sonnet (from action - more powerful!)
    #   - few_shot: 5 (from action)
    #   - api_key: ${ANTHROPIC_API_KEY} (inherited from project)

  - name: summarize
    prompt: "Summarize the analysis..."
    # ✓ Back to workflow defaults (claude-3-5-haiku)
```

**Result**: Most actions use Haiku, but the deep analysis step uses Sonnet for better quality.

---

### Example 4: Mixed Inheritance (Realistic)

A real-world scenario where different fields come from different levels.

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  api_key: ${ANTHROPIC_API_KEY}
  chunk_config:
    chunk_size: 500
    chunk_overlap: 50
  json_mode: true
  run_mode: online
```

```yaml
# workflows/document_processing.yml
name: document_processing
description: Process legal documents

defaults:
  model_name: claude-3-5-haiku-20241022  # ← Override model
  granularity: file                  # ← Workflow-specific
  few_shot: 2                        # ← Workflow-specific

actions:
  - name: extract_metadata
    few_shot: 0               # ← Override: no few-shot for this action
    prompt: "Extract document metadata..."
    # ✓ Final configuration is merged from all levels:
    #   - model_vendor: anthropic (from project model_vendor)
    #   - model_name: claude-3-5-haiku (from workflow)
    #   - api_key: ${ANTHROPIC_API_KEY} (from project)
    #   - chunk_config: 500/50 (from project)
    #   - json_mode: true (from project)
    #   - run_mode: online (from project)
    #   - granularity: file (from workflow)
    #   - few_shot: 0 (from action - overrides workflow's 2)

  - name: extract_clauses
    prompt: "Extract legal clauses..."
    # ✓ Uses workflow few_shot: 2 (not overridden)
```

**Result**: Each field comes from the most specific level where it's defined.

## Required Fields

After the configuration hierarchy is resolved (project → workflow → action merged), certain fields **must** be present:

| Field | Required | Notes |
|-------|----------|-------|
| `vendor` (or `model_vendor`) | ✅ Yes | Specifies the LLM provider (anthropic, openai, gemini, groq, etc.) |
| `model` (or `model_name`) | ✅ Yes | Specifies the model name (claude-3-5-sonnet-20241022, gpt-4, etc.) |
| `api_key` | ✅ Yes | API key for the vendor (can use `${ENV_VAR}` syntax) |

### What "After Hierarchy Resolution" Means

You don't need to specify these fields at **every** level - just somewhere in the hierarchy.

The system merges all three levels together, so as long as each required field appears at **at least one level**, you're good.

#### ✅ Valid Configurations

**All fields at project level:**
```yaml
# agent_actions.yml - all required fields here
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}

# workflows/my_workflow.yml - nothing required
actions:
  - name: extract
    prompt: "..."  # Inherits all required fields
```

**Split across levels:**
```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic        # Vendor from project
  api_key: ${ANTHROPIC_API_KEY}  # API key from project

# workflows/my_workflow.yml
defaults:
  model_name: claude-3-5-sonnet-20241022  # Model from workflow

actions:
  - name: extract
    # Has all required fields after merging!
```

**All at action level:**
```yaml
# No project or workflow defaults

# workflows/my_workflow.yml
actions:
  - name: extract
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    api_key: ${ANTHROPIC_API_KEY}
    prompt: "..."
```

#### ❌ Invalid Configurations

**Missing model_vendor: **
```yaml
# agent_actions.yml
default_agent_config:
  model_name: claude-3-5-sonnet-20241022  # ❌ No vendor!
  api_key: ${ANTHROPIC_API_KEY}

# workflows/my_workflow.yml
actions:
  - name: extract
    # ❌ Error: No vendor specified at any level
```

**Missing model_name: **
```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  api_key: ${ANTHROPIC_API_KEY}  # ❌ No model!

# workflows/my_workflow.yml
actions:
  - name: extract
    # ❌ Error: No model specified at any level
```

**Missing API key:**
```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022  # ❌ No api_key!

# workflows/my_workflow.yml
actions:
  - name: extract
    # ❌ Error: No api_key specified at any level
```

## Best Practices

### 1. Use Project-Level for Shared Defaults

Set common configuration at the project level to avoid repetition:

```yaml
# agent_actions.yml
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
  chunk_config:
    chunk_size: 500
    chunk_overlap: 50
```

Now all workflows automatically use these defaults unless overridden.

### 2. Override at Workflow Level for Special Cases

When a workflow needs different settings, override at workflow level:

```yaml
# workflows/cheap_processing.yml
defaults:
  model_vendor: anthropic
  model_name: claude-3-5-haiku-20241022  # Cheaper model for this workflow
```

### 3. Override at Action Level Sparingly

Only override at the action level when truly necessary:

```yaml
actions:
  - name: complex_analysis
    model_name: claude-3-5-sonnet-20241022  # Only this action needs powerful model
```

### 4. Use Environment Variables for API Keys

Always use environment variable interpolation for API keys:

```yaml
api_key: ${ANTHROPIC_API_KEY}  # ✅ Good
api_key: "sk-ant-..."          # ❌ Never hardcode!
```

### 5. Document Your Hierarchy

Add comments to explain why you're overriding defaults:

```yaml
defaults:
  # Use GPT-4 for this workflow because it requires strong reasoning
  model_vendor: openai
  model_name: gpt-4
```

## How Merging Works

Here's exactly how the system merges configurations:

```python
# Pseudocode showing the merge logic
final_config = {}

# Step 1: Start with project defaults
final_config.update(project_defaults)

# Step 2: Apply workflow defaults (overrides project)
final_config.update(workflow_defaults)

# Step 3: Apply action config (overrides everything)
final_config.update(action_config)

# Result: action > workflow > project
```

Each level completely overrides the previous level for any field it specifies.

## Common Questions

### Can I have workflows with no defaults section?

Yes! If you omit the `defaults` section, actions will inherit directly from project-level config.

### Can I mix vendor field names?

The system handles both `vendor`/`model_vendor` and `model`/`model_name` automatically. Just use the conventional name for each level (see [Field Name Differences](#field-name-differences)).

### What happens if I don't have an agent_actions.yml?

Workflows will work fine as long as all required fields are present at the workflow or action level.

### Can I override just one field?

Yes! You only need to specify the fields you want to override. All other fields will be inherited.

```yaml
actions:
  - name: my_action
    few_shot: 5  # Only override few_shot, inherit everything else
```

## Related Documentation

- [Workflows](./workflows.md) - Learn about workflow structure
- [Agents](./agents.md) - Understand agent configuration
- [Schemas](./schemas.md) - Define output schemas for your actions

---

**Next Steps**: Now that you understand the configuration hierarchy, you can start building workflows that leverage this powerful inheritance system.
