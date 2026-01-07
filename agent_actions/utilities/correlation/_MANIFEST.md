# Correlation Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `loop_id_generator.py` | Module | Loop Correlation Service. | - |
| `LoopIdGenerator` | Class | Thread-safe loop correlation ID generator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_or_create_loop_correlation_id` | Method | Get or create a loop correlation ID for a source_guid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_or_create_position_based_loop_correlation_id` | Method | Get or create a loop correlation ID based on record position. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_loop_correlation_registry` | Method | Clear the loop correlation ID registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_loop_correlation_id` | Method | Add loop correlation ID to an object if agent is in a loop. | - |
