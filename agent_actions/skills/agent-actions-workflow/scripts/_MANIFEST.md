# Workflow Script Manifest

## Overview

Auxiliary scripts that support the bundled `agent-actions` workflow skill (field
flow analysis, TypedDict generation, workflow scaffolding).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `analyze_field_flow.py` | Module | CLI helper that examines workflow/action dependencies for documentation. | `tooling.docs`, `prompt_generation` |
| `generate_typeddict.py` | Module | Generates TypedDict definitions from workflow schemas/prompts. | `validation`, `prompt_generation` |
| `init_workflow.py` | Module | Bootstraps a sample workflow as part of the skill. | `cli`, `configuration` |
