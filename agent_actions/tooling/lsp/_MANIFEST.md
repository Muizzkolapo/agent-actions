# LSP Manifest

## Overview

Language Server Protocol helpers that index agent workflows/prompts/tools, resolve
references, and expose hover/definition/navigation for editors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `models.py` | Module | Data models (`ProjectIndex`, `ActionMetadata`, `PromptDefinition`, `ReferenceType`, `Location`) describing references, workflows, prompts, schemas, and tools. | `lsprotocol`, `pygls` |
| `indexer.py` | Module | Scans workflows/prompts/tools/schemas with safe YAML parsing, builds `ProjectIndex`, and records metadata used by navigation and hover. Provides `find_all_project_roots()` for multi-project workspace discovery. Action values (`guard`, `context_scope`, `output_field`, `versions`) come from the PARSED document; the line pass supplies only positions and reference ranges. `output_field` defaults resolve workflow `defaults:` then `agent_actions.yml`'s `default_agent_config`. Guard-language keywords come from the operator registry. Uses `get_tool_dirs` from `path_config`. | `ruamel.yaml`, `yaml`, `logging`, `config.schema`, `input.preprocessing.parsing.operators` |
| `diagnostics.py` | Module | Collects LSP diagnostics: unresolved references, duplicate actions, guard clause validation. A guard reads the record as stored, so a clause is reported only where the file can prove it resolves nowhere: a bare name with no promotion available (suggesting the dotted spelling), or a dotted reference whose namespace no action in the workflow writes. Which fields a namespace holds is never judged. A versioned action produces `base_1`, `base_2`, ... and not its own name. | `lsprotocol`, `models`, `resolver`, `utils.constants`, `record.envelope` |
| `completions.py` | Module | LSP completion providers for context_scope blocks, guard conditions and `versions:` blocks. `build_guard_completions` delegates to `collect_available_guard_variables` for variable list; `build_versions_completions` reads `VersionConfig.model_fields`, so the editor cannot offer a key the loader refuses. | `lsprotocol`, `diagnostics`, `config.schema` |
| `resolver.py` | Module | Detects references at cursor positions (`get_reference_at_position`) and resolves them to file `Location`s (`resolve_reference`). | `lsprotocol`, `pathlib`, `utils` |
| `server.py` | Module | `AgentActionsLanguageServer` setup plus LSP handlers for initialize/definition/hover using the indexer/resolver/navigator. | `pygls`, `lsprotocol`, `utils` |
| `utils.py` | Module | Shared LSP utilities: `uri_to_path()` for URI conversion, `is_in_dependencies_context()` and `is_in_context_scope_list()` for YAML block detection. | `pathlib` |
| `__main__.py` | Entry | Enables `python -m agent_actions.tooling.lsp` invocation. Delegates to `server.main()`. | — |
