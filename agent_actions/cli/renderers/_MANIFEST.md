# Renderers Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `schema_renderer.py` | Module | Unified Rich rendering for schema display. | `models` |
| `SchemaRenderer` | Class | Unified Rich rendering for schema display. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render_summary_table` | Method | Render a summary table of all actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render_flow_tree` | Method | Render workflow flow as a tree. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render_data_flow_panel` | Method | Render a data flow panel (verbose tree view). | - |
| `whole_table.py` | Module | `print_whole(console, table)`: prints a Rich table at its full width, wider than the terminal if it has to be, so no cell is cut with an ellipsis. Used by the `agac dispositions` tables and the `agac expect report` per-rule table. | `rich` |
