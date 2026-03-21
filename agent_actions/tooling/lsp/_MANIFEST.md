# LSP Manifest

## Overview

Language Server Protocol helpers that index agent workflows/prompts/tools, resolve
references, and expose hover/definition/navigation for editors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `models.py` | Module | Data models (`ProjectIndex`, `ActionMetadata`, `PromptDefinition`, `ReferenceType`, `Location`) describing references, workflows, prompts, schemas, and tools. | `lsprotocol`, `pygls` |
| `indexer.py` | Module | Scans workflows/prompts/tools/schemas with safe YAML parsing, builds `ProjectIndex`, and records metadata used by navigation and hover. Provides `find_all_project_roots()` for multi-project workspace discovery. Context_scope list parsing correctly exits on non-list-item sibling keys. Uses `get_tool_dirs` from `path_config`. | `ruamel.yaml`, `yaml`, `logging` |
| `resolver.py` | Module | Detects references at cursor positions (`get_reference_at_position`) and resolves them to file `Location`s (`resolve_reference`). | `lsprotocol`, `pathlib`, `utils` |
| `server.py` | Module | `AgentActionsLanguageServer` setup plus LSP handlers for initialize/definition/hover using the indexer/resolver/navigator. | `pygls`, `lsprotocol`, `utils` |
| `utils.py` | Module | Shared LSP utilities: `uri_to_path()` for URI conversion, `is_in_dependencies_context()` and `is_in_context_scope_list()` for YAML block detection. | `pathlib` |
