# Support Resolution

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that transforms GitHub issues and support tickets into a complete resolution bundle — customer-facing response, internal engineering task, and an optional draft PR.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a support_resolution
```

Input tickets are read from `agent_io/staging/issues.json`. The final resolution bundle is written to `agent_io/target/format_output/`.

## What It Does

- Analyzes and classifies each incoming issue to extract key information — issue type, affected components, severity, and whether a code change is likely needed.
- Researches the issue from three independent angles in parallel (codebase, documentation, and similar past issues), with each researcher drawing on seed data including a codebase index, response templates, and team routing rules.
- Merges and deduplicates the three research findings with a deterministic tool, then uses the synthesized findings to determine the resolution approach.
- Generates a customer-facing response, an internal engineering task, and — guarded by a `requires_code_change` condition — a draft PR with suggested changes, all running in parallel from the resolution decision.
- Packages the customer response, internal task, and PR draft into a final resolution bundle via a formatting tool.
