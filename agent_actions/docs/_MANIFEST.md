# Docs Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `generator.py` | Module | Catalog and runs data generator. | `response_processing` |
| `CatalogGenerator` | Class | Generate catalog.json from workflows. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `generate` | Method | Generate the complete catalog structure. | - |
| `RunsGenerator` | Class | Initialize runs data structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `initialize_empty` | Method | Initialize empty runs data structure. | - |
| `generate_docs` | Function | Main entry point for docs generation. | - |
| `parser.py` | Module | Workflow YAML parser for documentation generation. | - |
| `extract_fields_for_docs` | Function | Extract normalized field list from raw schema for documentation. | - |
| `WorkflowParser` | Class | Parse and extract information from agent workflow YAML files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_workflow` | Method | Parse a workflow YAML file and extract all relevant information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_input_fields` | Method | Extract input field names from context_scope. | - |
| `run_tracker.py` | Module | Run tracking for documentation system. | `utilities` |
| `RunConfig` | Class | Configuration for recording a workflow run. | - |
| `ActionCompleteConfig` | Class | Configuration for recording action completion. | - |
| `RunTracker` | Class | Track workflow execution runs for documentation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `record_run` | Method | Record a workflow execution run with atomic file locking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `update_run` | Method | Update an existing run record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `start_workflow_run` | Method | Start tracking a new workflow run with action-level tracking support. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `record_action_start` | Method | Record when an action starts executing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `record_action_complete` | Method | Record when an action completes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `finalize_workflow_run` | Method | Finalize workflow run when it completes or fails. | - |
| `track_workflow_run` | Function | Quick function to track a workflow run. | - |
| `scanner.py` | Module | Project scanner for finding workflow files and prompts. | `response_processing` |
| `ProjectScanner` | Class | Scan project directory for agent workflows and prompts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `scan` | Method | Scan project directory for workflow files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `scan_prompts` | Method | Scan project directory for prompt files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `scan_schemas` | Method | Scan project directory for schema files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `scan_tool_functions` | Method | Scan project directory for tool function implementations. | - |
| `server.py` | Module | Documentation HTTP server. | - |
| `DocsRequestHandler` | Class | HTTP handler that serves from two directories: | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `translate_path` | Method | Map URL path to filesystem path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_message` | Method | Suppress default logging for cleaner output. | - |
| `serve_docs` | Function | Start HTTP server to serve documentation. | - |
