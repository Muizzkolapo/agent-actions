# Lineage Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `lineage_builder.py` | Module | Lineage Tracking Service. | - |
| `LineageBuilder` | Class | Builds and tracks lineage chains for data processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_node_lineage` | Method | Filter lineage to only include valid node IDs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_lineage` | Method | Build lineage by appending node_id to existing lineage. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_lineage_tracking` | Method | Add lineage tracking to an object based on source item. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_context_lineage_tracking` | Method | Add lineage tracking to an object based on context data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_lineage_tracking_from_sources` | Method | Add lineage from multiple source items (many-to-one). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_conditional_response` | Method | Create a standard response with lineage for conditional scenarios. | - |
