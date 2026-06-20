# Skills Manifest

**[> Architecture deep-dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

## Overview

Bundled skills for the Agent Actions CLI are stored under standardized directories
per provider (Claude/Codex). This package ships the `agac` skill.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agac-agent-skills](agac-agent-skills/SKILL.md) | Build, run, inspect, and debug agent-actions workflows. |

## Project Surface

This is a content-only module (no Python runtime code). The bundled documentation describes the following project paths and the helper scripts touch state under `agent_workflow/{workflow}/agent_io/`:

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `SKILL.md` (project structure) | `agent_actions.yml` | Reads | — |
| `SKILL.md` (project structure) | `agent_config/{workflow}.yml` | Reads | `name`, `defaults`, `actions[]` |
| `SKILL.md` (project structure) | `prompt_store/{workflow}.md` | Reads | — |
| `SKILL.md` (project structure) | `schema/{workflow}/{action}.yml` | Reads | — |
| `SKILL.md` (project structure) | `tools/{workflow}/*.py` | Reads | — |
| `SKILL.md` (project structure) | `seed_data/*.json` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/staging/` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/target/{action}/` | Reads | — |
| `references/workflow-patterns.md` | `agent_config/{workflow}.yml` | Reads | `actions[].versions`, `actions[].version_consumption`, `actions[].guard` |
| `references/context-scoping.md` | `agent_config/{workflow}.yml` | Reads | `actions[].context_scope` |
| `references/prompt-engineering.md` | `prompt_store/{workflow}.md` | Reads | — |
| `scripts/reset_workflow.py` | `agent_workflow/{workflow}/agent_io/.agent_status.json` | Writes (deletes) | — |
| `scripts/reset_workflow.py` | `agent_workflow/{workflow}/agent_io/{source,store,target}/` | Writes (`--full` wipes) | — |
| `scripts/inspect_action.py` | `agent_config/{workflow}.yml` | Reads (via `agac inspect`) | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Templates generate YAML consumed by ConfigManager |
| `workflow` | outbound | Scaffolded workflows are executed by AgentWorkflow |
| `cli` | outbound | Reference docs document `agac` CLI commands |
