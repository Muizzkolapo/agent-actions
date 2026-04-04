# Tooling Manifest

## Overview

Agent Actions tooling bundles helper packages that power documentation generation
and the language-server experience for workflows, prompts, tools, and schemas.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [docs](docs/_MANIFEST.md) | CLI tooling and servers for generating the docs artefact, catalog, scanner, and static site. |
| [lsp](lsp/_MANIFEST.md) | Language Server Protocol components (indexer, resolver, navigation) for IDE integration. |
| rendering | Data-card rendering helpers shared between LSP hover and HITL templates. |

## Project Surface

> How this module interacts with the user's project files.

### docs — Catalog Generation & Scanning

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `scanner.scan_workflows()` | `agent_workflow/{name}/agent_config/*.yml` | Reads | — |
| `scanner.scan_workflows()` | `artefact/rendered_workflows/*.yml` | Reads | — |
| `scanner.scan_readmes()` | `agent_workflow/{name}/README.md` | Reads | — |
| `scanner.scan_prompts()` | `prompt_store/*.md` | Reads | — |
| `scanner.scan_schemas()` | `schema/{workflow}/*.yml` | Reads | `schema_path` |
| `scanner.scan_tool_functions()` | `tools/**/*.py` | Reads | `tool_path` |
| `scanner.scan_runs()` | `agent_io/target/run_results.json` | Reads | — |
| `scanner.scan_runs()` | `agent_io/target/events.json` | Reads | — |
| `scanner.scan_runs()` | `agent_io/target/.manifest.json` | Reads | — |
| `scanner.scan_logs()` | `logs/events.json` | Reads | — |
| `scanner.scan_workflow_data()` | `agent_io/target/*.db` | Reads | — |
| `scanner.scan_examples()` | `agent_actions.yml` | Reads | — |
| `WorkflowParser.parse_workflow()` | `agent_workflow/{name}/agent_config/*.yml` | Reads | — |
| `generate_docs()` | `artefact/catalog.json` | Writes | — |
| `generate_docs()` | `artefact/runs.json` | Writes | — |
| `RunTracker.record_run()` | `artefact/runs.json` | Writes | — |
| `RunTracker.start_workflow_run()` | `artefact/runs.json` | Writes | — |
| `serve_docs()` | `artefact/catalog.json` | Reads | — |
| `serve_docs()` | `artefact/runs.json` | Reads | — |

### docs — Code Scanner (AST Introspection)

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `scan_tool_functions()` | `tools/**/*.py` | Reads | `tool_path` |
| `extract_function_details()` | `tools/**/*.py` | Reads | `tool_path` |
| `extract_typed_dicts()` | `tools/**/*.py` | Reads | `tool_path` |

### lsp — IDE Integration

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `build_index()` | `agent_workflow/{name}/agent_config/*.yml` | Reads | — |
| `_index_prompts()` | `prompt_store/*.md` | Reads | — |
| `_index_tools()` | `tools/**/*.py` | Reads | `tool_path` |
| `_index_schemas()` | `schema/{workflow}/*.yml` | Reads | `schema_path` |
| `find_project_root()` | `agent_actions.yml` | Reads | — |
| `find_all_project_roots()` | `agent_actions.yml` | Reads | — |
| `resolve_reference()` | `agent_workflow/`, `prompt_store/`, `tools/`, `schema/` | Reads | — |
| `collect_diagnostics()` | `agent_workflow/{name}/agent_config/*.yml` | Validates | — |

### rendering — Data Card Formatting

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `render_card_markdown()` | `agent_io/target/` | Transforms | — |

**Internal only**: `_empty_runs_data()`, `_guard_path()`, `_humanize_key()`, `_format_value()`, `_build_action_data_map()` — no direct project surface.

**Examples** — see this module in action:
- [`examples/contract_reviewer/agent_actions.yml`](../../examples/contract_reviewer/agent_actions.yml) — project config with `tool_path`, `schema_path`, and `seed_data_path` keys consumed by scanner and indexer
- [`examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — workflow YAML parsed by `WorkflowParser` and indexed by LSP
- [`examples/contract_reviewer/tools/contract_reviewer/`](../../examples/contract_reviewer/tools/contract_reviewer/) — UDF tool scripts scanned by `scan_tool_functions()` and indexed by `_index_tools()`
- [`examples/contract_reviewer/schema/contract_reviewer/`](../../examples/contract_reviewer/schema/contract_reviewer/) — schema YAML files scanned by `scan_schemas()` and indexed by `_index_schemas()`
- [`examples/contract_reviewer/prompt_store/contract_reviewer.md`](../../examples/contract_reviewer/prompt_store/contract_reviewer.md) — prompt file scanned by `scan_prompts()` and indexed by `_index_prompts()`
- [`examples/product_listing_enrichment/tools/product_listing_enrichment/`](../../examples/product_listing_enrichment/tools/product_listing_enrichment/) — additional UDF tools exercising `scan_tool_functions()` with nested tool directories
- [`examples/review_analyzer/schema/review_analyzer/`](../../examples/review_analyzer/schema/review_analyzer/) — schema files exercising `scan_schemas()` and `extract_fields_for_docs()`
