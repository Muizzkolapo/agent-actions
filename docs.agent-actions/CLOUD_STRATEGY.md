# Agent Actions Cloud — Product Strategy & Moat

**Internal document. Do not publish.**

---

## Core Moat: What We Do That Others Don't

### 1. Dynamic Prompt & Schema Variant Selection

Runtime selection of prompt and schema variants based on input characteristics. The workflow doesn't hardcode which prompt to use — it evaluates the record and picks the right one.

```yaml
- name: get_authoring_prompt
  kind: tool
  impl: select_prompt_variant    # Inspects record, returns prompt path
```

This is how we handle heterogeneous inputs without branching logic. One workflow serves many record types because the prompt adapts.

### 2. Input Signatures

Typed input contracts that define what a workflow expects before it runs. Signatures enable:
- Pre-flight validation of seed data and input files
- IDE-level autocomplete for workflow authors
- Cross-workflow composition (output signature of workflow A matches input signature of workflow B)

### 3. Prompt Optimizers (Premium)

Automated prompt improvement using model feedback loops. Feed the optimizer a prompt + evaluation criteria, and it iterates toward better performance. We already do this manually with Claude Code — the cloud product automates the loop.

How it works today (manual): We use Claude Code to analyze prompt performance against output quality metrics, then rewrite the prompt. The optimizer productizes this.

### 4. Workspace (Premium)

Collaborative environment for teams building workflows:
- Shared prompt store with role-based access
- Version history and diff view for prompts and schemas
- Team-level usage analytics and cost tracking
- Shared seed data libraries

### 5. Prompt Waste & Context Distractor Detection (Premium)

Static analysis that identifies:
- **Wasted tokens**: prompt sections that don't influence output quality
- **Context distractors**: fields in `observe` that hurt performance (irrelevant data confusing the model)
- **Redundant instructions**: prompt text that repeats what the schema already enforces

This is measurable — run the pipeline with and without each section, compare output quality. The cloud product automates the measurement.

### 6. Tool Nodes as Containers

Actions with `kind: tool` already run Python functions. The cloud extension: tool nodes that run containerized workloads. Any Docker image that accepts JSON stdin and produces JSON stdout becomes a pipeline step.

```yaml
- name: run_custom_analysis
  kind: container
  image: myteam/risk-scorer:latest
  input_schema: risk_input
  output_schema: risk_output
```

Use cases:
- Teams with proprietary models they can't share as Python
- Heavy compute steps (ML inference, data processing) that need their own resources
- Compliance requirements for isolated execution environments

### 7. Batch Polling (Premium)

Enhanced batch processing for premium users:
- Priority queue positioning
- Real-time progress tracking with per-record status
- Webhook callbacks on completion
- Automatic retry with exponential backoff
- Cost estimation before submission

### 8. Data Engineering Integration

Agent Actions workflows as steps in existing data engineering pipelines:
- Airflow operator: `AgentActionsOperator(workflow="contract_reviewer")`
- dbt integration: post-model hook that runs enrichment workflows
- Prefect/Dagster task wrappers
- Event-driven triggers (S3 upload, database change, webhook)

---

## Features We Already Do (Productize These)

### Prompt-to-Validation Generation

User writes a natural language rule ("no identifiers in explanations"). We have a prompt that reads this rule and generates a schema validation or guard condition automatically. The user describes what they want; the system creates the enforcement.

```
User input: "Explanations should not contain any AWS service identifiers"

Generated guard:
  condition: 'not any(id in explanation for id in service_identifiers)'
  on_false: "reprompt"
```

### Human-in-the-Loop Selection Types

Beyond binary approve/reject. HITL nodes that present the reviewer with:
- Multiple LLM-generated options to choose from
- Side-by-side comparison views
- Batch review with keyboard shortcuts
- Confidence-based routing (only show human when model is uncertain)

### Dynamic Interfaces (UI Components)

Reusable UI components that render based on workflow output schemas:
- Auto-generated review interfaces from schema definitions
- Configurable card/table/detail views
- Filter and search across pipeline outputs
- Export in multiple formats

### Dynamic Model Selection

Per-action model selection based on task characteristics, not just hardcoded config:

```yaml
- name: analyze_content
  model_selection:
    strategy: cost_optimized
    rules:
      - condition: 'token_count > 50000'
        model: claude-sonnet-4-20250514    # Long context needs strong model
      - condition: 'task_type == "classification"'
        model: qwen3:8b                    # Classification works fine with small model
      - default:
        model: gpt-4o-mini
```

---

## Pricing Tiers

| Feature | Open Source (Free) | Pro | Enterprise |
|---------|-------------------|-----|------------|
| Core framework | Yes | Yes | Yes |
| CLI + local execution | Yes | Yes | Yes |
| Batch API support | Yes | Yes | Yes |
| Multi-vendor support | Yes | Yes | Yes |
| Prompt optimizer | — | Yes | Yes |
| Workspace (team) | — | Yes | Yes |
| Context distractor detection | — | Yes | Yes |
| Batch polling + priority | — | Yes | Yes |
| Container tool nodes | — | — | Yes |
| Data engineering integrations | — | — | Yes |
| Dynamic model selection | — | — | Yes |
| SSO / audit log | — | — | Yes |

---

## Strategic Positioning

The open-source framework is the moat's foundation. It builds community, trust, and adoption. The cloud product sells what you can't get from the CLI alone: collaboration, optimization, and integration into production infrastructure.

The key insight: **the framework makes engineering skill the differentiator, not API budget. The cloud product makes that skill scalable across teams.**

---

## Research & Validation Needed

See `RESEARCH_PROMPT.md` for the prompt to give our researcher to validate whitepaper claims and gather supporting data for cloud positioning.
