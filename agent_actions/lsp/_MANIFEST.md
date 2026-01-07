# Lsp Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `indexer.py` | Module | Project indexer for Agent Actions LSP. | - |
| `find_project_root` | Function | Find project root by looking for agent_actions.yml. | - |
| `build_index` | Function | Build complete project index. | - |
| `models.py` | Module | Data models for Agent Actions LSP. | - |
| `ReferenceType` | Class | Types of references that can be resolved. | - |
| `Location` | Class | A location in a file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_lsp` | Method | Convert to LSP Location format. | - |
| `Reference` | Class | A reference found in a workflow file. | - |
| `ActionDefinition` | Class | An action defined in a workflow YAML. | - |
| `PromptDefinition` | Class | A prompt defined in a prompt store file. | - |
| `ToolDefinition` | Class | A UDF tool function. | - |
| `ProjectIndex` | Class | Index of all definitions in an agent-actions project. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action` | Method | Get action location, preferring same-file actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_prompt` | Method | Get prompt by reference (file.PromptName). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_tool` | Method | Get tool by function name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_schema` | Method | Get schema file path by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_workflow` | Method | Get workflow directory by name. | - |
| `resolver.py` | Module | Reference resolver for Agent Actions LSP. | - |
| `get_reference_at_position` | Function | Detect what reference (if any) is at the given position. | - |
| `resolve_reference` | Function | Resolve a reference to its target location. | - |
| `server.py` | Module | Agent Actions LSP Server - Main entry point. | - |
| `AgentActionsLanguageServer` | Class | Language Server for agent-actions workflows. | - |
| `initialize` | Function | Handle initialize request. | - |
| `goto_definition` | Function | Handle go to definition request. | - |
| `hover` | Function | Handle hover request. | - |
| `completions` | Function | Handle completion request. | - |
| `document_symbols` | Function | Handle document symbols request (outline view). | - |
| `did_save` | Function | Handle file save - reindex the file. | - |
| `main` | Function | Main entry point. | - |
