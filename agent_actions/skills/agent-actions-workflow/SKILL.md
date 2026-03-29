---
name: agent-actions-workflow
description: Build and debug agent-actions LLM workflows. Use when creating workflows, writing UDFs, configuring guards, setting up parallel/versioned actions, or debugging filtered pipelines with empty outputs. CRITICAL - Before creating or modifying ANY action, ALWAYS read the workflow first, understand the action anatomy, check parent outputs, and verify child inputs. Never make changes without understanding the full context. ALWAYS ask clarifying questions about goals, inputs, outputs, and edge cases before writing any code.
---

# Agent Actions Workflow Builder

Build production-ready agent-actions workflows with YAML configs, UDF tools, and proper context scoping.

## MANDATORY: Pre-Flight Checklist

**BEFORE creating or modifying ANY action, ALWAYS complete this checklist:**

### 0. Ask Clarifying Questions First

**NEVER assume. ALWAYS ask.** Before writing any code, gather information:

**Questions about the ACTION:**
- What is the goal of this action? What problem does it solve?
- Is this an LLM action or a UDF tool action?
- What fields does it need to produce?
- Are there any conditions for when it should run/skip?

**Questions about INPUTS (Parents):**
- Which actions provide input to this one?
- What fields are available from those actions?
- What is the data structure? (Check `sample.json` if unsure)
- Could any upstream guards filter out records?

**Questions about OUTPUTS (Children):**
- What actions will consume this output?
- What fields do they expect?
- Will adding this action break any existing dependencies?

**Questions about VALIDATION:**
- Should this action validate its input?
- Should downstream actions filter based on this action's output?
- What happens if validation fails? Filter or skip?

**Questions about EDGE CASES:**
- What if the input is empty?
- What if a required field is missing?
- What if all records get filtered?

**Example dialogue before creating a validation action:**
```
Q: What should this validation check?
Q: What fields from the parent action do we need to validate?
Q: What should happen when validation fails - filter the record or skip the action?
Q: What downstream actions need the validation result?
Q: What threshold should we use (e.g., score >= 8)?
Q: Should we use a stronger model (gpt-4o) for critical validation?
```

### 1. Read the Workflow Context
```bash
# Read the full workflow config first
cat agent_workflow/<workflow>/agent_config/<workflow>.yml
```

### 2. Understand Action Anatomy
Every action needs these pieces working together:

| Component | Question to Answer |
|-----------|-------------------|
| **name** | What is this action called? |
| **dependencies** | What actions must run BEFORE this one? |
| **context_scope.observe** | What fields does this action NEED to access? |
| **schema** (LLM) | What fields does this action PRODUCE? |
| **impl** (UDF) | What function processes this data? |
| **guard** | What conditions must be true to run? |
| **prompt** | What instructions drive the LLM? |

### 3. Map Parent Actions (Upstream)
Before creating an action, examine its dependencies:

```yaml
# For each action in dependencies, answer:
# - What fields does it produce?
# - What is the data structure?
# - Are there guards that might filter records?
```

**Check parent output:**
```bash
cat agent_io/target/<parent_action>/sample.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data:
    print('Fields available:', list(data[0].get('content', data[0]).keys()))
    print('Record count:', len(data))
"
```

### 4. Map Child Actions (Downstream)
Understand what consumes this action's output:

```yaml
# For each action that depends on THIS action:
# - What fields does it expect from us?
# - What context_scope.observe does it use?
# - Will our output satisfy its needs?
```

### 5. Holistic View Checklist

Before making changes, confirm:

- [ ] **I asked clarifying questions** - I don't have unresolved assumptions
- [ ] **I read the full workflow YAML** - I understand the pipeline
- [ ] **I know what data flows IN** - From dependencies via context_scope
- [ ] **I know what data flows OUT** - Schema (LLM) or return value (UDF)
- [ ] **I checked parent outputs** - Verified field names and structure
- [ ] **I checked child inputs** - My output will satisfy downstream needs
- [ ] **I understand any guards** - Both on this action and downstream
- [ ] **If UDF: I handle content wrapper** - `content = data.get('content', data)`
- [ ] **If UDF: I return a list** - `return [result]`

### Example: Adding a Validation Action

**WRONG approach:** Jump in and write the action.

**RIGHT approach:**

1. **Read workflow** → Understand where validation fits in pipeline
2. **Check parent** → `merge_alternatives` produces `optimal_code`, `alternative_1`, etc.
3. **Check child** → `generate_explanation` needs `validation_status` field
4. **Design action:**
   ```yaml
   - name: validate_code_quality
     dependencies: [merge_alternatives]      # Parent provides code
     schema:
       validation_status: string             # Child needs this!
       validation_reasoning: string
     context_scope:
       observe:
         - merge_alternatives.*              # Access parent fields
         - generate_optimal_code.optimal_code
   ```
5. **Update child** → Add guard: `condition: 'validation_status == "PASS"'`

---

## Critical Lessons Learned

### 1. Schema Files Must Have Proper Structure

**WRONG** (causes "empty schema name" error):
```yaml
title: string
description: string
```

**CORRECT:**
```yaml
name: extract_incident_details
description: Schema for extracting incident information
fields:
  - id: title
    type: string
    description: "Brief incident title"
  - id: description
    type: string
    description: "Detailed description"
required:
  - title
  - description
additionalProperties: false
```

### 2. Versions Keyword (NOT Loop)

**WRONG:**
```yaml
loop:                    # ← NOT a valid keyword
  param: classifier_id
  range: [1, 2, 3]
loop_consumption:        # ← NOT a valid keyword
  source: classify
  pattern: merge
```

**CORRECT:**
```yaml
versions:                # ← Correct keyword
  range: [1, 3]          # ← Inclusive range [start, end]
  mode: parallel
version_consumption:     # ← Correct keyword
  source: classify
  pattern: merge
```

### 3. Version Template Variables

**Template variables (`{{ i }}`, `{{ version.length }}`) work with both inline prompts AND prompt store references.**

**Works (inline prompt):**
```yaml
- name: classify
  versions:
    range: [1, 3]
  prompt: |
    You are classifier {{ i }} of {{ version.length }}.
```

**Also works (prompt store reference):**
```yaml
- name: classify
  versions:
    range: [1, 3]
  prompt: $workflow.Classify_Prompt  # ← {{ i }} works here too!
```

**Available version variables:**
| Variable | Description |
|----------|-------------|
| `{{ i }}` | Current iteration value (1, 2, 3...) |
| `{{ idx }}` | Zero-based index (0, 1, 2...) |
| `{{ version.length }}` | Total iterations |
| `{{ version.first }}` | True on first iteration |
| `{{ version.last }}` | True on last iteration |

**Note:** Both YAML config and templates use `version.*` namespace for consistency.

### 4. Prompts Must Reference Available Fields

**ALWAYS check what fields are actually available in context before writing prompts.**

```bash
# Check what fields an action outputs
cat agent_io/target/<action_name>/incidents.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data:
    print('Fields:', list(data[0].get('content', data[0]).keys()))
"
```

**Common mistake:** Referencing fields that don't exist or are named differently.

```yaml
# WRONG - field doesn't exist
{{ assign_response_team.system_impact_level }}

# CORRECT - check actual output first
{{ assign_response_team.affected_systems }}
```

### 5. Passthrough Merges Fields Into Action Namespace

When using `passthrough`, upstream fields become available under the current action's namespace:

```yaml
- name: assign_team
  context_scope:
    passthrough:
      - aggregate_severity.*        # These fields...
      - assess_customer_impact.*    # ...become available as...
```

Access in downstream prompts as `{{ assign_team.final_severity }}` (not `{{ aggregate_severity.final_severity }}`).

### 6. Check Actual Data Flow

When debugging "undefined variable" errors:

1. **Check the action's context_scope** - What does it observe/passthrough?
2. **Check the parent action's actual output** - What fields does it really produce?
3. **Check the schema** - Does it match what the prompt expects?

```bash
# Debug command: see all fields at each stage
for dir in agent_io/target/*/; do
  echo "=== $dir ==="
  cat "$dir"/*.json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data:
    print('Fields:', sorted(data[0].get('content', data[0]).keys()))
" 2>/dev/null || echo "No data"
done
```

---

## Quick Reference

```bash
agac run -a my_workflow              # Run workflow
agac run -a my_workflow --upstream   # With upstream deps
```

## Project Structure

```
project/
├── agent_actions.yml                  # Project configuration
├── agent_workflow/
│   └── my_workflow/                   # Directory name must match workflow name!
│       ├── agent_config/
│       │   └── my_workflow.yml        # YAML filename must match workflow name!
│       ├── agent_io/
│       │   ├── staging/               # Input data (place files here)
│       │   ├── source/                # Auto-generated with metadata
│       │   └── target/                # Output per action
│       └── seed_data/                 # Reference data (optional)
├── prompt_store/                      # Prompt templates
├── schema/                            # Output schemas (root only!)
└── tools/
    └── my_workflow/                   # Tools organized by workflow
```

**CRITICAL Naming Convention:**
- Directory name = YAML filename = `name:` field in YAML (use underscores, not hyphens)
- Example: `agent_workflow/incident_triage/agent_config/incident_triage.yml` with `name: incident_triage`

## Core Concepts

### Dependencies vs Context Scope

**CRITICAL DISTINCTION:**
- **`dependencies`** → Controls WHEN action runs (execution order)
- **`context_scope`** → Controls WHAT data action accesses (via lineage)

```yaml
- name: generate_answer
  dependencies: [validate_data]           # Run AFTER validate_data
  context_scope:
    observe:
      - validate_data.*                   # Access validate_data output
      - source.page_content               # Access original source via lineage
```

### Action Types

**LLM Action:**
```yaml
- name: generate_explanation
  dependencies: [previous_action]
  model_vendor: openai
  model_name: gpt-4o-mini
  schema: { explanation: string }         # Only LLM-computed fields!
  prompt: $workflow.Prompt_Name
  context_scope:
    observe:
      - previous_action.*
```

**Tool Action (UDF):**
```yaml
- name: process_data
  dependencies: [previous_action]
  kind: tool
  impl: function_name                     # Must match @udf_tool function
  granularity: Record                     # Record (default) | File (rare)
  context_scope:
    observe:
      - previous_action.*
```

### Guards (Conditional Filtering)

```yaml
guard:
  condition: 'validation_status == "PASS" and score >= 8'
  on_false: "filter"    # filter | skip
```

**⚠️ Guards check INPUT, not OUTPUT.** Place guard on the NEXT action:

```yaml
- name: validate_data
  # No guard - this produces validation_status

- name: use_validated
  dependencies: [validate_data]
  guard:
    condition: 'validation_status == "PASS"'  # Checks validate_data OUTPUT
```

### Versioned Parallel Actions

```yaml
- name: generate_alternatives
  versions:
    param: alt_num
    range: [1, 2, 3]
    mode: parallel
  schema:
    alternative_${alt_num}: string

- name: merge_alternatives
  dependencies: [generate_alternatives]
  version_consumption:
    source: generate_alternatives
    pattern: merge
  context_scope:
    observe:
      - generate_alternatives.*           # Wildcard captures ALL versions
```

### Cross-Workflow Dependencies

```yaml
dependencies:
  - workflow: upstream_workflow
    action: final_action                  # Use ACTION name, not impl name!
context_scope:
  observe:
    - final_action.*
```

## UDF Essential Pattern

**CRITICAL: Always handle content wrapper and return a list.**

```python
from typing import Any
from agent_actions import udf_tool

@udf_tool()
def my_function(data: dict[str, Any]) -> list[dict[str, Any]]:
    # STEP 1: Handle content wrapper (REQUIRED)
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # STEP 2: Forward fields + add computed
    result = content.copy()
    result['computed_field'] = some_calculation(content)

    # STEP 3: Return as LIST (REQUIRED)
    return [result]
```

## Quick Debugging

### Check Where Records Were Filtered

```bash
cd agent_workflow/my_workflow/agent_io/target
for dir in */; do
  count=$(cat "$dir/sample.json" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  echo "$count records - $dir"
done
```

**If you see:**
```
5 records - validate_quality/
0 records - generate_output/    ← Guard filtered all!
```

**Fix options:**
1. Check why validation failed (see validation output)
2. Lower threshold or allow more statuses
3. Temporarily disable guard for testing

## Dynamic Content Injection

**Problem:** You need randomized or computed content in LLM prompts (e.g., different scenario openers per question type).

**Solution:** Use a **tool action** between upstream and LLM actions:

```yaml
# Step 1: Inject action adds dynamic content
- name: inject_opener
  dependencies: [get_authoring_prompt]
  kind: tool
  impl: inject_random_opener
  context_scope:
    observe:
      - get_authoring_prompt.quiz_type_used
    passthrough:
      - get_authoring_prompt.*    # Forward all upstream fields

# Step 2: LLM action uses injected content
- name: write_question
  dependencies: [inject_opener]   # Depends on injector, not upstream
  context_scope:
    observe:
      - inject_opener.*           # Access injected fields
```

```python
# UDF for randomization
import random
from agent_actions import udf_tool

@udf_tool()
def inject_random_opener(data: dict) -> dict:
    content = data.get('content', data)
    quiz_type = content.get('quiz_type_used', 'general').lower()

    openers = {
        'debugging': ["During monitoring, you notice", "Your team observes"],
        'design_review': ["During a design review", "A colleague suggests"],
    }

    opener = random.choice(openers.get(quiz_type, openers['design_review']))
    return {"suggested_opener": opener, "quiz_type": quiz_type.upper()}
```

**In prompt template:**
```markdown
**Your opener**: {{ inject_opener.suggested_opener }}
```

**Why not dispatch_task() in prompts?** It's unreliable - LLMs often output the literal text instead of the function result.

See: **[Dynamic Content Injection](references/dynamic-content-injection.md)**

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Guard on wrong action | Place on NEXT action (guard checks INPUT) |
| UDF forgot content wrapper | Always: `content = data.get('content', data)` |
| UDF returns dict | Must return list: `return [result]` (unless using passthrough) |
| Dependency not in context_scope | Add `action.*` to observe |
| Cross-workflow uses impl name | Use action name, not impl |
| Schema in subdirectory | Must be in root `schema/` |
| dispatch_task() in prompts | Use tool action injection instead |
| Missing passthrough | Add `passthrough: [upstream.*]` to forward fields |
| Using `loop:` keyword | Use `versions:` (not `loop:`) |
| Using `loop_consumption:` | Use `version_consumption:` |
| Schema without `name` field | Add `name:`, `description:`, `fields:` structure |
| `seed_data.` in observe/prompts | Config key is `seed_data:`, reference prefix is `seed.` |
| Schema with folder prefix | Use `schema: name` not `schema: workflow_name/name` |
| Depend on base versioned name | Use `version_consumption` or list all expanded variants |
| Referencing non-existent fields | Check actual output with `cat agent_io/target/<action>/*.json` |
| Wrong field namespace after passthrough | Fields become `current_action.field`, not `original_action.field` |

## Detailed Reference Files

For comprehensive documentation, see:

- **[Action Anatomy](references/action-anatomy.md)** - Complete guide to action structure, components, and data flow
- **[Workflow Patterns](references/workflow-patterns.md)** - Diamond, ensemble, conditional merge patterns
- **[UDF Patterns](references/udf-patterns.md)** - Field forwarding, validation aggregation, version consumption
- **[UDF Decorator](references/udf-decorator.md)** - @udf_tool() API, granularity options, input/output contracts
- **[Context Scope Guide](references/context-scope-guide.md)** - observe, drop, passthrough, seed_path directives
- **[Dynamic Content Injection](references/dynamic-content-injection.md)** - Randomized prompts, computed values, tool action injection
- **[Data Flow Patterns](references/data-flow-patterns.md)** - Directory structure, metadata fields, content wrapper format
- **[Prompt Patterns](references/prompt-patterns.md)** - Prompt store syntax, Jinja2 templates, field references
- **[YAML Schema](references/yaml-schema.md)** - Complete YAML configuration reference
- **[CLI Reference](references/cli-reference.md)** - agac commands, flags, and usage
- **[Debugging Guide](references/debugging-guide.md)** - Error messages, filtered pipeline debugging, known limitations
- **[Common Pitfalls](references/common-pitfalls.md)** - Detailed explanations and fixes for frequent mistakes

## Prompt Templates

Define in `prompt_store/workflow_name.md`:

```markdown
{prompt Extract_Facts}
Extract from: {{ source.page_content }}
Previous result: {{ previous_action.field }}
{end_prompt}
```

Reference: `prompt: $workflow_name.Extract_Facts`

## Output Grounding with Source Quotes

**Problem:** LLM outputs need to be backed by source material for credibility and verification.

**Solution:** Add explicit `source_quote` fields to schema and prompt instructions.

**Step 1: Add to schema**
```yaml
schema: {
  answer: string,
  explanation: string,
  source_quote: string    # Add explicit field
}
```

**Step 2: Add to prompt template**
```markdown
## GROUNDING REQUIREMENTS

1. Include a **verbatim quote** from the source that supports your answer
2. The quote must be 15-30 words of continuous text
3. NO paraphrasing - copy exact text from the documentation

## OUTPUT FORMAT

```json
{
  "answer": "...",
  "explanation": "...",
  "source_quote": "Exact verbatim quote from source that backs up the answer"
}
```

## SOURCE QUOTE REQUIREMENT

The `source_quote` field must contain:
- A **verbatim quote** from {{ source.page_content }}
- The quote that **directly supports** the answer
- NO paraphrasing - copy exact text
```

**Why this matters:**
- Forces LLM to ground outputs in source material
- Enables downstream validation
- Provides audit trail for generated content

## Configuration Hierarchy

```
agent_actions.yml (Project) → workflow.yml defaults → action fields
```

Higher specificity wins.

## Retry & Reprompt

```yaml
defaults:
  retry:
    max_attempts: 3
    on_exhausted: return_last  # return_last | raise

  reprompt:
    max_attempts: 4
    on_exhausted: return_last  # return_last | raise
```
