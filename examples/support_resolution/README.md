# Support Resolution — Field-by-Field Construction

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that triages support tickets using **non-JSON mode** and **field-by-field construction** — works with any model including Ollama and local LLMs.

## Why This Pattern Matters

Small and local models often can't produce valid JSON reliably. This workflow asks each action for **one answer at a time**. By the end of the pipeline, all fields are assembled into a complete triage record — no JSON mode required.

```
Ticket → [classify] → [severity] → [area] → [team] → [summary] → [response] → Triage Record
           issue_type    severity    product_area  assigned_team  summary   suggested_response
```

Each box adds ONE field via `output_field`. No schema needed — the model just produces plain text, and the framework maps it to the named field.

## Key Features Demonstrated

| Feature | How It's Used |
|---|---|
| `json_mode: false` | Every action returns plain text, no JSON parsing |
| `output_field` | Each action names its output field — no schema files needed |
| Guard as cost control | `draft_response` is skipped for low-severity tickets |
| Progressive context | Later steps see upstream fields, not raw ticket body |
| Seed data | `routing_rules.json` used by `assign_team` without JSON mode |
| Per-action model override | `draft_response` can use a stronger model (commented out) |
| Ollama-compatible | Default vendor is `ollama` with `llama3` |

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file
cp .env.example .env

# With Ollama (default — no API key needed):
ollama pull llama3
agac run -a support_resolution

# Or override to use OpenAI:
agac run -a support_resolution --model-vendor openai --model-name gpt-4o-mini
```

Input tickets: `agent_io/staging/issues.json` (4 sample tickets with varying severity)
Output: `agent_io/target/format_output/`

## What It Does

1. **Classifies** the ticket type (bug, feature request, question, etc.)
2. **Assesses severity** based on impact — drops reporter labels to avoid anchoring bias
3. **Identifies product area** from the description
4. **Assigns team** using seed data routing rules
5. **Summarizes** the issue in one line for a triage dashboard
6. **Drafts a response** — guarded: skipped for low-severity tickets to save tokens
7. **Packages** all fields into a final triage record via a tool

## File Structure

```
support_resolution/
├── agent_actions.yml                          # Project config
├── .env.example                               # API key template
├── agent_workflow/support_resolution/
│   ├── agent_config/support_resolution.yml    # Workflow definition
│   ├── agent_io/staging/issues.json           # Sample tickets
│   └── seed_data/routing_rules.json           # Team routing rules
├── prompt_store/support_resolution.md         # 6 single-answer prompts
└── tools/support_resolution/
    └── package_triage_result.py               # Final assembly tool
```
