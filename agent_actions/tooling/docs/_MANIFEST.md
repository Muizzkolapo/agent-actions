# Docs Tooling Manifest

## Overview

Documentation tooling is responsible for scanning workflows, enriching them with
prompt/schema metadata, generating `catalog.json`, tracking runs, and serving the
static docs site via `docs_site/`.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `generator.py` | Module | `CatalogGenerator` that builds catalog entries, enriches actions with input/output metadata, and merges runs/logs/prompts. | `prompt_generation`, `output.response.loader` |
| `parser.py` | Module | `WorkflowParser` plus helpers (`extract_fields_for_docs`) to parse rendered workflows, infer dependencies, and normalize schema fields for docs. | `prompt.context`, `validation` |
| `scanner.py` | Module | `ProjectScanner` that locates rendered/original workflows, prompts, schemas, and run data under `artefact/` plus `agent_config`. | `file_io`, `logging` |
| `run_tracker.py` | Module | `RunTracker`, `RunConfig`, and `ActionCompleteConfig` that append runs to `artefact/runs.json` using file locks (portalocker retry). | `tooling.docs`, `logging` |
| `server.py` | Module | `serve_docs` HTTP server and `DocsRequestHandler` that multiplex static files from the package (`docs_site/`) with data from the caller's `artefact/`. | `http.server`, `pathlib` |
| `docs_site/` | Static | Packaged React/next assets that power the documentation UI (served via `server.py`). | - |
