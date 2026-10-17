# Prompt Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

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
| `deferred_values.py` | Module | `LoadRender` is one load of a workflow file. It wraps every `prompt:` value of the file and of `templates/`, and every other value that names a version variable, in a tag that sees exactly what Jinja has bound where the load reaches it, in block or flow style, on its key's line or the lines below it. A value whose names are all bound renders at load as before. A prompt reading a name a record supplies (`source`, an action of the workflow, a version variable) is left whole for the per-record render: its top-level `{{ }}` tags that read load-time names and nothing else render into it, and the load-time data its other tags read is set at its top (`{% set name = ... +%}`); a macro, function or include it would need per record fails the load. A `LoadedPrompt` (the text `load_prompt` returns) that a prompt's `{{ }}` tag outputs as it is, in either case, goes into the YAML as a token replaced by the text once the YAML is parsed (`fill_loaded`, or within the per-record text), so its lines are never read as YAML. A value reading a version variable renders per version (`render_version`) or, outside a versioned action, without one (`fill_values`). The environment is `StrictUndefined` except while a `templates/` file's top level is imported, and records every name it looks up and misses; `check` fails the load on one a record or a version supplies. A name a prompt reads that the render finds undefined is taken for an action the file names by a tag (`name: {{ n }}`) and the file rendered again; `check` fails the load with the first error when no parsed action has that name. An `{% include ... without context %}` is compiled so its text reaches a macro, set block, call body or filter block that collects output, where Jinja's own code makes a generator of it. | `prompt_generation` |
| `formatter.py` | Module | Template helpers for prompt formatting and escaping. | `prompt_generation` |
| `handler.py` | Module | `PromptLoader` and prompt builder utilities. `PromptLoader.load_prompt` accepts `project_root: Path \| None`; `PromptLoader.load_prompt_expanded` also replaces each `{{ load_prompt("...") }}` tag in the prompt by that prompt, recursively, refusing a cycle or a call it cannot expand (the `$` reference, the load-time `load_prompt` global and `PromptFormatter` use it). | `logging`, `cli` |
| `prompt_utils.py` | Module | Misc utilities (token counting, template expansion). | `prompt_generation`, `logging` |
| `render_workflow.py` | Module | Renders workflows into final YAML via templates. `render_pipeline_with_templates` accepts `project_root: Path \| None`. The load renders through `deferred_values.LoadRender`: an action's prompt that reads what only a record supplies is left whole for the per-record render, a versioned action's other values that read a version variable render per version at expansion, and a name nothing defines fails the load. Its `load_prompt` global returns a `deferred_values.LoadedPrompt`, which a prompt's tag puts in as written, whatever its lines and the prompt's YAML style. The `templates/` folder loads in file-name order, each file's top level run once and after any file whose name it reads; the files' modules share the globals, so a file reads any other's macros and variables whatever the files are called, and of two files defining a name the one that ran later is the global. | `cli`, `prompt_generation` |
| `renderer.py` | Module | `JinjaTemplateRenderer` for Jinja rendering, `ConfigRenderingService` for config loading. | `cli`, `validation` |
| `message_builder.py` | Module | `MessageBuilder` — unified message assembly for all LLM providers. `LLMMessageEnvelope`, `ProviderMessageConfig`, `PROVIDER_MESSAGE_CONFIGS` registry. An Ollama context dict is encoded with `deep_json`, at any depth. | `llm`, `prompt_generation` |
| `service.py` | Module | `PromptPreparationService`: applies context scope and renders the per-record prompt. A render that runs past the recursion limit (`{{ value }}` prints a dict or list with `str()`) fails that record with `RecordContextError`, naming the deepest field, its depth and the limit, and pointing to `\| tojson`; a recursion no field half the limit deep explains (a recursive macro) fails as any other render error. A template reading a field of a null dependency namespace fails with `TemplateVariableError` whose `null_namespace_hints` say what the record shows about why (`null_namespace.diagnose`); a guard is named only when the record shows that action's guard skipping it. A field a present namespace (or a mapping inside it) lacks is reported as `ns.field` with "'ns' has no field 'field' (it has: ...)", not as a namespace nothing supplies. | `logging`, `prompt_generation` |
| `jinja_env.py` | Module | `DictKeyFirstEnvironment`: a mapping's key wins over a same-named attribute on dot access, and `tojson` encodes with `deep_json`, so it renders a value at any depth with the text Jinja's own gives. Given `place_of`, a key a mapping lacks raises `MissingFieldError` naming the mapping's place and the field, once the undefined is used. | `prompt_generation` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `PromptLoader.load_prompt()` | `prompt_store/{workflow}.md` | Reads | `actions[].prompt` |
| `PromptLoader.discover_prompt_files()` | `prompt_store/{workflow}.md` | Reads | — |
| `PromptFormatter.get_raw_prompt()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt` |
| `PromptPreparationService.prepare_prompt_with_context()` | `agent_config/{workflow}.yml` | Reads | `actions[].context_scope` |
| `PromptPreparationService._load_seed_data()` | `seed_data/*.json` | Reads | `actions[].context_scope.seed` |
| `PromptUtils.inject_function_outputs_into_prompt()` | `tools/{workflow}/*.py` | Reads | `actions[].prompt` |
| `render_pipeline_with_templates()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt`, `actions[].schema_name` |
| `render_pipeline_with_templates()` | `agent_config/{workflow}.yml` | Validates | `actions[].versions` via `validate_version_block` — the block is expanded away here, so nothing downstream sees it; `ActionExpander`'s own expansion calls the same validator |
| `render_pipeline_with_templates()` | `schema/{workflow}/{action}.yml` | Reads | `actions[].schema_name`, `actions[].schema` |
| `render_pipeline_with_templates()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt` that reads a per-record name is kept whole for the per-record render; `actions[].versions` renders the action's other values that read a version variable per version |
| `LoadRender` | `templates/*.jinja2`, `templates/*.j2` | Reads | each file's `prompt:` values and version-variable values, wrapped as the workflow's are |
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
