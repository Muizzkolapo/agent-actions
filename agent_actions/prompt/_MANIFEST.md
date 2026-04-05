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

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `PromptLoader.load_prompt()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` |
| `PromptLoader.discover_prompt_files()` | `prompt_store/{workflow}.md` | Reads | — |
| `PromptFormatter.get_raw_prompt()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt` |
| `PromptPreparationService.prepare_prompt_with_context()` | `agent_config/{workflow}.yml` | Reads | `actions[].context_scope` |
| `PromptPreparationService._load_seed_data()` | `seed_data/*.json` | Reads | `actions[].context_scope.seed_path` |
| `PromptUtils.inject_function_outputs_into_prompt()` | `tools/{workflow}/*.py` | Reads | `actions[].prompt` |
| `render_pipeline_with_templates()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt`, `actions[].schema_name` |
| `render_pipeline_with_templates()` | `schema/{workflow}/{action}.yml` | Reads | `actions[].schema_name`, `actions[].schema` |
| `ConfigRenderingService.render_and_load_config()` | `agent_config/{workflow}.yml` | Validates | `actions[]` |
| `MessageBuilder.build()` | `.env` | Reads | — |

**Internal only**: `PromptStyle`, `SchemaInjection`, `MessageRole`, `LLMMessage`, `LLMMessageEnvelope`, `ProviderMessageConfig`, `PROVIDER_MESSAGE_CONFIGS`, `PromptPreparationRequest`, `PromptPreparationResult`, `TemplateRenderer`, `JinjaTemplateRenderer`, `StaticDataLoader` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `workflow` | inbound | Calls PromptPreparationService during action execution |
| `processing` | inbound | TaskPreparer delegates prompt rendering to PromptPreparationService |
| `llm` | inbound | Provider clients use MessageBuilder for prompt assembly |
| `validation` | inbound | Prompt validator checks prompt file references |
| `config` | outbound | Reads prompt paths and project root from config utilities |
| `output` | outbound | Uses SchemaLoader to inline named schemas during rendering |
| `input` | outbound | Uses StringProcessor for dispatch_task() call resolution |
