# Docs Tooling Manifest

## Overview

Documentation tooling is responsible for scanning workflows, enriching them with
prompt/schema metadata, generating `catalog.json`, tracking runs, and serving the
static docs site via `docs_site/`. Extended to also scan vendors, error types,
event types, example projects, data loaders, and processing states.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `generator.py` | Module | `CatalogGenerator` that builds catalog entries, enriches actions with input/output metadata, and merges runs/logs/prompts. Uses `_empty_runs_data` from `run_tracker` to initialize runs.json. | `prompt_generation`, `output.response.loader`, `run_tracker` |
| `parser.py` | Module | `WorkflowParser` plus helpers (`extract_fields_for_docs`) to parse rendered workflows, infer dependencies, and normalize schema fields for docs. | `prompt.context`, `validation` |
| `scanner.py` | Module | `ProjectScanner` that locates rendered/original workflows, prompts, schemas, run data, vendors, error types, event types, examples, data loaders, and processing states. Uses AST parsing for Python source introspection. | `file_io`, `logging`, `ast` |
| `run_tracker.py` | Module | `RunTracker`, `RunConfig`, `ActionCompleteConfig`, and `_empty_runs_data()` factory that append runs to `artefact/runs.json` using file locks (portalocker retry). | `tooling.docs`, `logging` |
| `server.py` | Module | `serve_docs` HTTP server and `DocsRequestHandler` that multiplex static files from the package (`docs_site/`) with data from the caller's `artefact/`. | `http.server`, `pathlib` |
| `docs_site/` | Static | Next.js static export that powers the documentation UI (served via `server.py`). Built from `frontend/` source. | - |
| `frontend/` | Source | Next.js + shadcn/ui + Tailwind app. Screens: home, workflows, actions, runs, data, logs, prompts, schemas, tools, settings. Build with `bash build_frontend.sh`. | `next`, `react`, `tailwindcss` |
| `build_frontend.sh` | Script | Builds `frontend/` and copies static export into `docs_site/`. | `npm`, `next build` |
