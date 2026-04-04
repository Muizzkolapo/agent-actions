# Prompt Manifest

## Overview

Prompt utilities cover generation, templating, formatting, context scope helpers,
and service wiring used by CLI commands and runtime agents.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context](context/_MANIFEST.md) | Builds rich context scopes and static prompt loaders. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `data_generator.py` | Module | `DataGenerator` that composes prompts with context for workflows. | `cli`, `workflow`, `llm` |
| `formatter.py` | Module | Template helpers for prompt formatting and escaping. | `prompt_generation` |
| `handler.py` | Module | `PromptLoader` and prompt builder utilities. `PromptLoader.load_prompt` accepts `project_root: Path \| None`. | `logging`, `cli` |
| `prompt_utils.py` | Module | Misc utilities (token counting, template expansion). | `prompt_generation`, `logging` |
| `render_workflow.py` | Module | Renders workflows into final YAML via templates. `render_pipeline_with_templates` accepts `project_root: Path \| None`. | `cli`, `prompt_generation` |
| `renderer.py` | Module | `JinjaTemplateRenderer` for Jinja rendering, `ConfigRenderingService` for config loading. | `cli`, `validation` |
| `message_builder.py` | Module | `MessageBuilder` — unified message assembly for all LLM providers. `LLMMessageEnvelope`, `ProviderMessageConfig`, `PROVIDER_MESSAGE_CONFIGS` registry. | `llm`, `prompt_generation` |
| `service.py` | Module | `PromptService` used by CLI/tests for retrieving prompt definitions. | `logging`, `prompt_generation` |

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `PromptLoader.discover_prompt_files()` | `prompt_store/{workflow}.md` | Reads | — |
| `PromptLoader.load_prompt()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` (`$file.block` syntax) |
| `PromptLoader.validate_prompt_blocks()` | `prompt_store/{workflow}.md` | Validates | — |
| `PromptLoader.validate_unique_prompts()` | `prompt_store/{workflow}.md` | Validates | — |
| `render_pipeline_with_templates()` | `agent_config/{workflow}.yml` | Reads | — |
| `render_pipeline_with_templates()` | `templates/*.j2` | Reads | — |
| `_resolve_prompt_fields()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` |
| `_compile_action_schemas()` | `schema/{workflow}/{action}.yml` | Reads | `actions[].schema`, `actions[].schema_name` |
| `_save_failed_render()` | `.agent-actions/cache/rendered_workflows/{workflow}_failed.yml` | Writes | — |
| `JinjaTemplateRenderer.render()` | `agent_config/{workflow}.yml` | Reads | — |
| `ConfigRenderingService.render_and_load_config()` | `agent_config/{workflow}.yml` | Reads | — |
| `ConfigRenderingService.render_and_load_config()` | `schema/{workflow}/` | Validates | `schema_path` |
| `PromptFormatter.get_raw_prompt()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` |
| `PromptPreparationService._load_seed_data()` | `seed_data/{file}.json` | Reads | `context_scope.seed_path` |
| `PromptPreparationService._render_prompt_template()` | `prompt_store/{workflow}.md` | Transforms | `actions[].prompt` |
| `PromptUtils.inject_function_outputs_into_prompt()` | `tools/{workflow}/{tool}.py` | Reads | `tool_path` |
| `StaticDataLoader.load_static_data()` | `seed_data/{file}.{json,yml,csv,md,txt}` | Reads | `context_scope.seed_path` |
| `MessageBuilder.build()` | — | Transforms | `actions[].model_vendor` |

**Internal only**: `_apply_version_template()`, `_expand_versioned_action()`, `_expand_workflow_versions()`, `_expand_inline_schema()`, `_is_inline_schema_dict()`, `PromptUtils.parse_field_references()`, `PromptUtils.resolve_field_reference()`, `PromptUtils.replace_field_references()`, `LLMContextBuilder`, `PromptPreparationRequest`, `PromptPreparationResult` — no direct project surface.

**Examples** — see this module in action:
- [`examples/review_analyzer/prompt_store/review_analyzer.md`](../../examples/review_analyzer/prompt_store/review_analyzer.md) — prompt template with multiple `{prompt}` / `{end_prompt}` blocks, Jinja2 variables (`{{ source.* }}`, `{{ seed.* }}`), and version-aware conditionals (`{{ version.first }}`)
- [`examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — workflow config using `$review_analyzer.Block` prompt references, `context_scope.seed_path`, `context_scope.observe/drop/passthrough`, and named schema references
- [`examples/review_analyzer/agent_workflow/review_analyzer/seed_data/evaluation_rubric.json`](../../examples/review_analyzer/agent_workflow/review_analyzer/seed_data/evaluation_rubric.json) — seed data file loaded by `StaticDataLoader` via `context_scope.seed_path`
- [`examples/review_analyzer/schema/review_analyzer/extract_claims.yml`](../../examples/review_analyzer/schema/review_analyzer/extract_claims.yml) — YAML schema compiled inline by `_compile_action_schemas()`
- [`examples/contract_reviewer/prompt_store/contract_reviewer.md`](../../examples/contract_reviewer/prompt_store/contract_reviewer.md) — prompt template for a map-reduce workflow pattern
- [`examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) — workflow with multiple `seed_path` entries and per-action prompt references
