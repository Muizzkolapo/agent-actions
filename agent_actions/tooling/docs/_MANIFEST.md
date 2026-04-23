# Docs Tooling Manifest

## Overview

Documentation tooling is responsible for scanning workflows, enriching them with
prompt/schema metadata, generating `catalog.json`, tracking runs, and serving the
static docs site via `docs_site/`. Extended to also scan vendors, error types,
event types, example projects, data loaders, and processing states.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `generator.py` | Module | `CatalogGenerator` that builds catalog entries, enriches actions with input/output metadata, and merges runs/logs/prompts. `_copy_readme_images()` copies referenced images to `artefact/images/` and rewrites paths in README content. Uses `_empty_runs_data` from `run_tracker` to initialize runs.json. `catalog.json` is written atomically via `tempfile.mkstemp` + `os.replace`. | `prompt_generation`, `output.response.loader`, `run_tracker`, `scanner.ReadmeData` |
| `parser.py` | Module | `WorkflowParser` plus helpers (`extract_fields_for_docs`) to parse rendered workflows, infer dependencies, and normalize schema fields for docs. | `prompt.context`, `validation` |
| `scanner/` | Package | Plain functions for scanning project artifacts. All accept `project_root: Path`. |  |
| `scanner/__init__.py` | Module | `scan_workflows()`, `scan_readmes()`, `ReadmeData` dataclass plus re-exports from sub-modules. `scan_readmes()` returns `dict[str, ReadmeData]` with content and source directory for resolving relative image paths. | `config.defaults` |
| `scanner/data_scanners.py` | Module | `scan_prompts`, `scan_schemas`, `scan_workflow_data`, `scan_sqlite_readonly`, `scan_runs`, `scan_logs`, `extract_action_metrics`, `_unwrap_record_content` — data-oriented scan functions. `scan_sqlite_readonly` unwraps namespaced `content[action_name]` in preview records. `scan_logs` and `extract_action_metrics` cap file iteration at 100 000 lines via `itertools.islice` to prevent unbounded reads. | `output.response.loader`, `parser` |
| `scanner/code_scanners.py` | Module | `scan_tool_functions`, `extract_typed_dicts`, `extract_function_details` — AST-based code introspection. | `ast` |
| `scanner/component_scanners.py` | Module | `scan_vendors`, `scan_error_types`, `scan_event_types`, `scan_examples`, `scan_data_loaders`, `scan_processing_states` — component discovery via AST. | `ast`, `yaml` |
| `run_tracker.py` | Module | `RunTracker`, `RunConfig`, `ActionCompleteConfig`, and `_empty_runs_data()` factory that append runs to `artefact/runs.json` using file locks (`LOCK_EX \| LOCK_NB` with exponential backoff up to timeout). `RunTracker.__init__` accepts `project_root: Path \| None`. File creation under `start_workflow_run` is atomic (created under lock before releasing). | `tooling.docs`, `logging` |
| `server.py` | Module | `serve_docs` HTTP server and `DocsRequestHandler` that multiplex static files from the package (`docs_site/`) with data from the caller's `artefact/`. `serve_docs` accepts `project_root: Path \| None`. | `http.server`, `pathlib` |
| `docs_site/` | Static | Next.js static export that powers the documentation UI (served via `server.py`). Built from `frontend/` source. | - |
| `frontend/` | Source | Next.js + shadcn/ui + Tailwind app. Screens: home, workflows, actions, runs, data, logs, prompts, schemas, tools, settings. Build with `bash build_frontend.sh`. | `next`, `react`, `tailwindcss` |
| `build_frontend.sh` | Script | Builds `frontend/` and copies static export into `docs_site/`. | `npm`, `next build` |
