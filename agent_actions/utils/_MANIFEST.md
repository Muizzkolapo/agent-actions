# Utils Manifest

## Overview

Shared helpers for IDs, field management, metadata, lineage, UDF tooling, path
handling, formatting, and transformation utilities used by both CLI and runtime
pathways.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [correlation](correlation/_MANIFEST.md) | Version correlation ID generation for deterministic versioned-agent workflows. |
| [field_management](field_management/_MANIFEST.md) | Ensures processed items always expose the required metadata/IDs. |
| [id_generation](id_generation/_MANIFEST.md) | UUID/ deterministic ID helpers for target/node/source GUIDs. |
| [lineage](lineage/_MANIFEST.md) | Lineage tracking helpers (chain building, ancestry chain propagation). |
| [metadata](metadata/_MANIFEST.md) | Unified metadata extraction/ dataclasses for LLM responses. |
| [transformation](transformation/_MANIFEST.md) | Passthrough transformer + strategy helpers for context_scope.passthrough data. |
| [udf_management](udf_management/_MANIFEST.md) | UDF discovery, registry, and dynamic execution helpers. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `constants.py` | Module | Shared configuration key constants and reserved names used across CLI/workflows. | `configuration`, `validation` |
| `dict.py` | Module | `get_nested_value` helper for safely reading dot-separated fields from nested dicts. | `filtering`, `preprocessing` |
| `graph_utils.py` | Module | Graph algorithms for dependency resolution (`topological_sort`). | `errors` |
| `module_loader.py` | Module | Thread-safe module loading and UDF discovery (`load_module_from_path`, `load_module_from_directory`, `discover_and_load_udfs`). No `sys.path` mutation. | `logging`, `errors`, `utils.udf_management` |
| `passthrough_builder.py` | Module | `PassthroughItemBuilder` that creates normalized passthrough objects with metadata and lineage for batch/online modes. | `preprocessing`, `lineage`, `id_generation` |
| `path_utils.py` | Module | Convenience path helpers (ensure dirs, mirror target-to-source, resolve absolute paths, find project root) backed by `PathManager`. Thread-safe global singleton with double-checked locking. `set_path_manager()` allows explicit DI of a scoped instance. `derive_workflow_root()` safely finds the workflow root from a path inside a workflow (agent_io fast-path + agent_config walk-up + safe fallback). | `config.paths`, `file_io` |
| `safe_format.py` | Module | Robust exception formatting (safe formatting, root cause extraction, chain formatting). | `logging`, `errors` |
| `tools_resolver.py` | Module | Normalizes the various `tools`/`tool_path` syntaxes in agent configs. | `configuration`, `validation` |
| `error_handler.py` | Module | Error handling utilities for configuration and validation errors. | `errors`, `logging` |
| `error_wrap.py` | Module | Decorator for wrapping validation errors with additional context. | `errors`, `validation` |
| `file_handler.py` | Module | `FileHandler` static utility for recursive file/folder discovery (stdlib only: logging, os, pathlib). Moved from `output/`. | `file_io` |
| `project_root.py` | Module | Project root detection utilities (`find_project_root`, `ensure_in_project`). Moved from `cli/`. | `errors` |
| `file_utils.py` | Module | `load_structured_file` helper for loading JSON/YAML files by extension. | `file_io` |
| `schema_utils.py` | Module | Schema format detection (`is_compiled_schema`, `is_inline_schema_shorthand`). | `validation` |
| `path_security.py` | Module | Path traversal prevention and sandbox validation utilities. | `errors`, `security` |

## Project Surface

> How this module interacts with the user's project files.

### Project Root & Path Resolution

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `project_root.find_project_root()` | `agent_actions.yml` | Reads | — |
| `project_root.ensure_in_project()` | `agent_actions.yml` | Validates | — |
| `path_utils.find_project_root()` | `agent_actions.yml` | Reads | — |
| `path_utils.derive_workflow_root()` | `agent_io/`, `agent_config/` | Reads | — |
| `path_utils.create_mirror_source_path()` | `agent_io/target/`, `agent_io/source/` | Transforms | — |
| `path_utils.ensure_directory_exists()` | `agent_io/`, `artefact/` | Writes | — |
| `path_utils.create_agent_directory_structure()` | `agent_workflow/{name}/` | Writes | — |

### Module Loading & UDF Discovery

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `module_loader.load_module_from_path()` | `tools/**/*.py` | Reads | `tool_path` |
| `module_loader.discover_and_load_udfs()` | `tools/*.py` | Reads | `tool_path` |
| `module_loader.discover_and_load_udfs_recursive()` | `tools/**/*.py` | Reads | `tool_path` |
| `udf_management.registry.udf_tool` | `tools/**/*.py` | Reads | `tool_path` |
| `udf_management.tooling.load_user_defined_function()` | `tools/**/*.py` | Reads | `tool_path` |
| `udf_management.tooling.execute_user_defined_function()` | `tools/**/*.py` | Reads | `tool_path` |

### Configuration Resolution

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `tools_resolver.resolve_tools_path()` | `agent_actions.yml` | Reads | `tool_path`, `tools` |
| `constants.RESERVED_AGENT_NAMES` | `agent_workflow/{name}/agent_config/*.yml` | Validates | — |
| `constants.SPECIAL_NAMESPACES` | `agent_workflow/{name}/agent_config/*.yml` | Validates | — |
| `constants.DANGEROUS_PATTERNS` | `agent_workflow/{name}/agent_config/*.yml` | Validates | `guard.condition` |

### Data Processing Helpers

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `file_handler.FileHandler.get_agent_paths()` | `agent_workflow/{name}/agent_config/`, `agent_io/` | Reads | — |
| `file_handler.FileHandler.find_file_in_directory()` | `agent_workflow/` | Reads | — |
| `file_handler.FileHandler.get_all_agent_paths()` | `agent_workflow/{name}/agent_config/*.yml` | Reads | — |
| `file_utils.load_structured_file()` | `schema/{workflow}/*.yml`, `*.json` | Reads | — |
| `dict.get_nested_value()` | `agent_io/target/` | Transforms | — |
| `graph_utils.topological_sort()` | `agent_workflow/{name}/agent_config/*.yml` | Transforms | — |

### Lineage, IDs & Metadata

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `id_generation.IDGenerator` | `agent_io/target/` | Transforms | — |
| `lineage.LineageBuilder` | `agent_io/target/` | Transforms | — |
| `field_management.FieldManager` | `agent_io/target/` | Transforms | — |
| `metadata.MetadataExtractor` | `agent_io/target/` | Transforms | — |
| `correlation.VersionIdGenerator` | `agent_io/target/` | Transforms | — |
| `passthrough_builder.PassthroughItemBuilder` | `agent_io/target/` | Transforms | — |
| `transformation.PassthroughTransformer` | `agent_io/target/` | Transforms | `context_scope.passthrough` |

**Internal only**: `safe_format.safe_format_error()`, `error_handler.*`, `error_wrap.*`, `schema_utils.*`, `path_security.*` — no direct project surface (consumed by other framework modules).

**Examples** — see this module in action:
- [`examples/contract_reviewer/tools/contract_reviewer/split_contract_by_clause.py`](../../examples/contract_reviewer/tools/contract_reviewer/split_contract_by_clause.py) — UDF tool using `@udf_tool` decorator from `udf_management.registry`, discovered by `module_loader`
- [`examples/contract_reviewer/tools/contract_reviewer/aggregate_clause_analyses.py`](../../examples/contract_reviewer/tools/contract_reviewer/aggregate_clause_analyses.py) — FILE-granularity UDF exercising `FileUDFResult` from `udf_management.registry`
- [`examples/contract_reviewer/agent_actions.yml`](../../examples/contract_reviewer/agent_actions.yml) — `tool_path` and `schema_path` keys resolved by `tools_resolver` and `path_utils`
- [`examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — workflow with `context_scope.passthrough` processed by `transformation.PassthroughTransformer`, dependencies sorted by `graph_utils.topological_sort()`
- [`examples/product_listing_enrichment/tools/product_listing_enrichment/fetch_competitor_prices.py`](../../examples/product_listing_enrichment/tools/product_listing_enrichment/fetch_competitor_prices.py) — UDF in a nested tool directory discovered by `discover_and_load_udfs_recursive()`
- [`examples/review_analyzer/agent_workflow/review_analyzer/agent_io/staging/reviews.json`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_io/staging/reviews.json) — source data in `agent_io/staging/` located by `path_utils.derive_workflow_root()`
