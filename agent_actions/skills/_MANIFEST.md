# Skills Manifest

**[> Architecture deep-dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

## Overview

Bundled skills for the Agent Actions CLI are stored under standardized directories
per provider (Claude/Codex). This package ships four skills.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [agac-agent-skills](agac-agent-skills/SKILL.md) | Build, run, inspect, and debug agent-actions workflows, and test them offline with `agac run --sandbox`. |
| [agac-operations](agac-operations/SKILL.md) | Run large workflows safely: batch or online, resume, `--rerun`, `retry --all`, exit codes, usage, scale limits, an offline rehearsal with faults, and a health check of the output counts. |
| [agac-expectations](agac-expectations/SKILL.md) | Declare output-quality rules with `expect:` blocks, and calibrate a rule before it may block records. |
| [agac-blind-verification](agac-blind-verification/SKILL.md) | Check outputs with independent verifiers that never see the reference, with display ids and a vote rule. |

## Project Surface

This is a content-only module (no Python runtime code). The bundled documentation describes the following project paths; the helper scripts touch state under `agent_workflow/{workflow}/agent_io/`, and `--full` additionally reaches `.agac/` at the project root:

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `SKILL.md` (project structure) | `agent_actions.yml` | Reads | — |
| `SKILL.md` (project structure) | `agent_config/{workflow}.yml` | Reads | `name`, `defaults`, `actions[]`, `outputs[]` |
| `SKILL.md` (project structure) | `prompt_store/{workflow}.md` | Reads | — |
| `SKILL.md` (project structure) | `schema/{workflow}/{action}.yml` | Reads | — |
| `SKILL.md` (project structure) | `tools/{workflow}/*.py` | Reads | — |
| `SKILL.md` (project structure) | `seed_data/*.json` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/staging/` | Reads | — |
| `SKILL.md` (project structure) | `agent_io/target/{action}/` | Reads | — |
| `references/workflow-patterns.md` | `agent_config/{workflow}.yml` | Reads | `actions[].dependencies`, `actions[].versions`, `actions[].version_consumption`, `actions[].guard`, `actions[].context_scope` |
| `references/loop-patterns.md` | `agent_config/{workflow}.yml` | Reads | `actions[].dependencies`, `actions[].versions`, `actions[].version_consumption`, `actions[].guard`, `actions[].context_scope` |
| `references/pooling-approach.md` | `agent_config/{workflow}.yml` | Reads | `actions[].dependencies`, `actions[].versions`, `actions[].version_consumption`, `actions[].context_scope` |
| `references/context-scoping.md` | `agent_config/{workflow}.yml` | Reads | `actions[].context_scope` |
| `references/prompt-engineering.md` | `prompt_store/{workflow}.md` | Reads | — |
| `references/database-io.md` | `agent_actions.yml` | Reads | `connections` |
| `references/database-io.md` | `agent_config/{workflow}.yml` | Reads | `defaults.data_source`, `outputs[]` |
| `references/sandbox-testing.md` | `sandbox.yml`, `sandbox.<workflow>.yml` | Reads | `seed`, `defaults`, `actions.<name>` (`errors`, `break_rules`, `pin`, `judge`, `latency_ms`, `stub`), `records[]`, `batch` |
| `references/sandbox-testing.md` | `agent_workflow/{workflow}/agent_io/sandbox/` | Reads (via `agac ... --sandbox`) | — |
| `scripts/reset_workflow.py` | `agent_workflow/{workflow}/agent_io/.agent_status.json` | Writes (deletes) | — |
| `scripts/reset_workflow.py` | `agent_workflow/{workflow}/agent_io/{store,target,sandbox}/` | Writes (`--full` wipes) | — |
| `scripts/reset_workflow.py` | `.agac/batch_state/` | Writes (`--full` reclaims) | — |
| `scripts/inspect_action.py` | `agent_config/{workflow}.yml` | Reads (via `agac inspect`) | — |
| `agac-operations/scripts/run_health.py` | `agent_workflow/{workflow}/agent_io/.agent_status.json` | Reads | — |
| `agac-operations/scripts/run_health.py` | `agent_workflow/{workflow}/agent_io/sandbox/.agent_status.json` | Reads (`--sandbox`) | — |
| `agac-operations/scripts/run_health.py` | `agac dispositions -w {workflow} --json` | Reads (runs the command, with `--sandbox` when given) | — |
| `agac-operations/references/recovery.md`, `agac-expectations/SKILL.md` | `sandbox.yml`, `sandbox.<workflow>.yml` | Reads | `actions.<name>.errors`, `break_rules`, `judge`, `batch` |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Templates generate YAML consumed by ConfigManager |
| `workflow` | outbound | Scaffolded workflows are executed by AgentWorkflow |
| `cli` | outbound | Reference docs document `agac` CLI commands |
