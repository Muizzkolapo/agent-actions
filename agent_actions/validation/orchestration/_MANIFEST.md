# Orchestration Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_entry_validation_orchestrator.py` | Module | Orchestrator for agent entry validation. | `validation` |
| `AgentEntryValidationContext` | Class | Encapsulates validation context passed to all validators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid` | Method | Check if context is properly configured. | - |
| `AgentEntryValidationOrchestrator` | Class | Orchestrates agent entry validation through a chain of specialized validators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_agent_entry` | Method | Validate a single agent entry through the validation chain. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_validation_errors` | Method | Get all validation errors collected from validators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_validation_warnings` | Method | Get all validation warnings collected from validators. | - |
