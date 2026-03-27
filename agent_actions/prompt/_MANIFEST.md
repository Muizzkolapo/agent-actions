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
