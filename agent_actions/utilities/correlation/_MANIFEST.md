# Correlation Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `version_id_generator.py` | Module | Loop Correlation Service. | - |
| `VersionIdGenerator` | Class | Thread-safe version correlation ID generator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_or_create_version_correlation_id` | Method | Get or create a version correlation ID for a source_guid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_or_create_position_based_version_correlation_id` | Method | Get or create a version correlation ID based on record position. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_version_correlation_registry` | Method | Clear the version correlation ID registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_version_correlation_id` | Method | Add version correlation ID to an object if agent is in a loop. | - |
