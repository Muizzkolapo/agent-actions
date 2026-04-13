# Skills Manifest

## Overview

Bundled skills for the Agent Actions CLI are stored under standardized directories
per provider (Claude/Codex). This package ships the `agent-actions-workflow` skill.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agent-actions-workflow](agent-actions-workflow/scripts/_MANIFEST.md) | Scripts that help analyze field flow, generate TypedDicts, and initialize workflows. |

## Project Surface

This is a content-only module (no Python runtime code). The templates and references scaffold the following project paths when a user initializes a new workflow:

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `workflow.yml.template` | `agent_config/{workflow}.yml` | Writes | `name`, `defaults`, `actions[]` |
| `udf_tool.py.template` | `tools/{workflow}/*.py` | Writes | — |
| `SKILL.md` (project structure) | `agent_actions.yml` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/staging/` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/target/{action}/` | Reads | — |
| `SKILL.md` (project structure) | `prompt_store/{workflow}.md` | Reads | — |
| `SKILL.md` (project structure) | `schema/{workflow}/{action}.yml` | Reads | — |
| `SKILL.md` (project structure) | `seed_data/*.json` | Reads | — |
| `references/yaml-schema.md` | `agent_config/{workflow}.yml` | Reads | `actions[].guard`, `actions[].context_scope`, `actions[].versions` |
| `references/prompt-patterns.md` | `prompt_store/{workflow}.md` | Reads | — |
| `references/udf-reference.md` | `tools/{workflow}/*.py` | Reads | — |

**Internal only**: reference documents (`action-anatomy.md`, `cli-reference.md`, `framework-contracts.md`, `context-scope-guide.md`, `data-flow-patterns.md`, `debugging-guide.md`, `dynamic-content-injection.md`, `udf-reference.md`, `workflow-patterns.md`, `reprompt-patterns.md`, `schema-design-guide.md`, `aggregation-patterns.md`, `hitl-patterns.md`, `cross-workflow-patterns.md`) — no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Templates generate YAML consumed by ConfigManager |
| `workflow` | outbound | Scaffolded workflows are executed by AgentWorkflow |
| `cli` | outbound | Reference docs document `agac` CLI commands |
