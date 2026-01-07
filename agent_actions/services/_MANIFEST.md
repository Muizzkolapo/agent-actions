# Services Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `workflow_schema_service.py` | Module | Workflow schema service for unified schema access. | `models`, `validation` |
| `WorkflowSchemaService` | Class | Single source of truth for workflow schema analysis. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `graph` | Method | Get the data flow graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action_schema` | Method | Get unified schema for a single action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_schemas` | Method | Get schemas for all actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Run static validation on the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_execution_order` | Method | Get topological execution order of actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_downstream_actions` | Method | Get actions that depend on the given action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert full analysis to dictionary for JSON serialization. | - |
