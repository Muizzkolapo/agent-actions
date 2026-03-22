# Models Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_schema.py` | Module | Unified schema model for workflow actions. Re-exports `ActionKind` from `config.schema`. | - |
| `ActionKind` | Re-export | Canonical `str, Enum` with case-insensitive `_missing_` (llm, tool, hitl, source, seed). Defined in `config/schema.py`. | - |
| `FieldSource` | Class | How a field is produced. | - |
| `FieldInfo` | Class | Information about a single field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `UpstreamReference` | Class | Reference to an upstream agent's field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `ActionSchema` | Class | Unified schema for any action type. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `available_outputs` | Method | Fields available to downstream agents (excludes dropped). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `dropped_outputs` | Method | Fields explicitly dropped from output. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `required_inputs` | Method | Required input field names (for tools). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `optional_inputs` | Method | Optional input field names (for tools). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `uses_fields` | Method | Unique 'agent.field' references from upstream. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
