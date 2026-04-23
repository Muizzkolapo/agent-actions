# Tooling Manifest

## Overview

Agent Actions tooling bundles helper packages that power documentation generation
and the language-server experience for workflows, prompts, tools, and schemas.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [docs](docs/_MANIFEST.md) | CLI tooling and servers for generating the docs artefact, catalog, scanner, and static site. |
| [lsp](lsp/_MANIFEST.md) | Language Server Protocol components (indexer, resolver, navigation) for IDE integration. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `scan_workflows()` | `agent_config/{workflow}.yml` | Reads | — |
| `scan_workflows()` | `agent_io/target/` | Reads | — |
| `scan_readmes()` | `agent_config/{workflow}.yml` | Reads | — |
| `scan_prompts()` | `prompt_store/{workflow}.md` | Reads | — |
| `scan_schemas()` | `schema/{workflow}/{action}.yml` | Reads | — |
| `scan_tool_functions()` | `tools/{workflow}/*.py` | Reads | `tool_path` |
| `scan_workflow_data()` | `agent_io/target/{action}/` | Reads | — |
| `scan_runs()` | `agent_io/target/` | Reads | — |
| `scan_logs()` | `agent_io/target/` | Reads | — |
| `scan_examples()` | `agent_actions.yml` | Reads | `description` |
| `generate_docs()` | `agent_actions.yml` | Reads | `tool_path` |
| `CatalogGenerator.generate()` | `agent_config/{workflow}.yml` | Reads | `actions`, `defaults` |
| `WorkflowParser.parse_workflow()` | `agent_config/{workflow}.yml` | Reads | `actions`, `dependencies`, `context_scope` |
| `RunTracker.record_run()` | `agent_io/target/` | Writes | — |
| `RunTracker.start_workflow_run()` | `agent_io/target/` | Writes | — |
| `serve_docs()` | `agent_io/target/` | Reads | — |
| `build_index()` | `agent_config/{workflow}.yml` | Reads | `actions` |
| `build_index()` | `prompt_store/{workflow}.md` | Reads | — |
| `build_index()` | `tools/{workflow}/*.py` | Reads | `tool_path` |
| `build_index()` | `schema/{workflow}/{action}.yml` | Reads | — |
| `find_project_root()` | `agent_actions.yml` | Reads | — |
| `find_all_project_roots()` | `agent_actions.yml` | Reads | — |
| `resolve_reference()` | `seed_data/*.json` | Reads | `seed_data_path` |
| `render_card_markdown(*, action_name=)` | `agent_io/target/{action}/` | Transforms | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Path resolution, project root detection, and tool directory config |
| `utils` | outbound | Path utilities, constants, file loading, and project root detection |
| `prompt` | outbound | Prompt file discovery and template pattern matching |
| `output` | outbound | Schema file discovery and loading |
| `models` | outbound | ActionSchema and FieldInfo for catalog enrichment |
| `workflow` | outbound | WorkflowSchemaService for field-level lineage |
| `errors` | outbound | Error types for validation and config errors |
| `input` | outbound | UDF tool file discovery filter |
| `cli` | inbound | CLI docs/run commands invoke generator and server |
| `validation` | inbound | Static analyzer uses code_scanner for schema extraction |
| `llm` | inbound | HITL provider uses data_card rendering constants |
