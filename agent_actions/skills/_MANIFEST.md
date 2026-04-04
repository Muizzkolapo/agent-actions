# Skills Manifest

## Overview

Bundled skills for the Agent Actions CLI are stored under standardized directories
per provider (Claude/Codex). This package ships the `agent-actions-workflow` skill.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agent-actions-workflow](agent-actions-workflow/scripts/_MANIFEST.md) | Scripts that help analyze field flow, generate TypedDicts, and initialize workflows. |

## Project Surface

> How this module interacts with the user's project files. The skills package is a **content-only** module (no Python source) that ships templates, reference docs, and a SKILL.md descriptor. It produces user project files via template instantiation; it does not read or validate them at runtime.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `workflow.yml.template` | `agent_config/{workflow}.yml` | Writes (scaffolds) | `name`, `defaults`, `actions` |
| `udf_tool.py.template` | `tools/{workflow}/{tool_name}.py` | Writes (scaffolds) | — |
| `SKILL.md` | `agent_config/{workflow}.yml` | Reads (instructs AI to read workflow before editing) | — |
| `SKILL.md` | `agent_io/target/{action}/` | Reads (instructs AI to inspect action output) | — |
| `SKILL.md` | `prompt_store/{workflow}.md` | Writes (instructs AI to create prompt templates) | — |
| `SKILL.md` | `schema/` | Writes (instructs AI to create schema files) | — |

**Internal only**: `references/*.md` — reference documentation for AI consumption; no direct file I/O.

**Examples** — see this module in action:
- [`examples/incident_triage/.../incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) — production workflow following the structure defined by `workflow.yml.template`
- [`examples/incident_triage/tools/incident_triage/aggregate_severity_votes.py`](../../examples/incident_triage/tools/incident_triage/aggregate_severity_votes.py) — UDF tool following the `@udf_tool()` pattern from `udf_tool.py.template`
- [`examples/incident_triage/prompt_store/incident_triage.md`](../../examples/incident_triage/prompt_store/incident_triage.md) — prompt store following the `{prompt Name}...{end_prompt}` pattern described in SKILL.md
- [`examples/contract_reviewer/tools/contract_reviewer/split_contract_by_clause.py`](../../examples/contract_reviewer/tools/contract_reviewer/split_contract_by_clause.py) — map-step UDF showing the content-wrapper + list-return pattern from the template
- [`examples/review_analyzer/.../review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — multi-vendor workflow demonstrating advanced patterns (versions, guards, seed_data) covered in SKILL.md references
