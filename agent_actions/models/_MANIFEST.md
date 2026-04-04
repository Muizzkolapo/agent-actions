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

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `ActionKind` | `agent_config/{workflow}.yml` | Validates | `actions[].kind` |
| `ActionSchema` | `agent_config/{workflow}.yml` | Transforms | `actions[]` |
| `ActionSchema` | `schema/{workflow}/{action}.yml` | Transforms | `actions[].schema` |
| `FieldInfo` | `schema/{workflow}/{action}.yml` | Transforms | `fields[]` |
| `UpstreamReference` | `agent_config/{workflow}.yml` | Transforms | `actions[].context_scope.observe` |

**Internal only**: `FieldSource` enum, `to_dict()` methods — used for serialization within `schema` and `inspect` CLI commands but do not directly read or write user files.

**Examples** — see this module in action:
- [`examples/support_resolution/agent_workflow/support_resolution/agent_config/support_resolution.yml`](../../examples/support_resolution/agent_workflow/support_resolution/agent_config/support_resolution.yml) — workflow config whose `actions[].kind` values are parsed into `ActionKind`; `output_field` and `context_scope.observe` become `FieldInfo` and `UpstreamReference` instances
- [`examples/support_resolution/schema/support_resolution/format_output.yml`](../../examples/support_resolution/schema/support_resolution/format_output.yml) — schema file transformed into `ActionSchema.output_fields`
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml) — complex multi-action workflow with tool/llm/source kinds exercising `ActionKind` enum variants
- [`examples/incident_triage/schema/incident_triage/extract_incident_details.yml`](../../examples/incident_triage/schema/incident_triage/extract_incident_details.yml) — schema with multiple fields demonstrating `FieldInfo` and `FieldSource` usage
