# Prompt Generation Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config_renderer.py` | Module | Configuration rendering service. | `cli`, `errors`, `llm_invocation`, `prompt_generation`, `response_processing`, `validation` |
| `TemplateRenderer` | Class | Abstract interface for template rendering. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render` | Method | Render a template with the given configuration. | - |
| `ConfigParser` | Class | Abstract interface for configuration parsing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse configuration data from a string. | - |
| `OutputWriter` | Class | Abstract interface for writing output to a file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write` | Method | Write content to the specified path. | - |
| `JinjaTemplateRenderer` | Class | Template renderer implementation using Jinja. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render` | Method | Render a template with the given configuration using Jinja. | - |
| `YAMLConfigParser` | Class | Configuration parser implementation for YAML. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse YAML configuration data from a string. | - |
| `FileOutputWriter` | Class | Output writer implementation for files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write` | Method | Write content to a file. | - |
| `ConfigRenderingService` | Class | Service for rendering and loading configuration data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render_and_load_config` | Method | Render templates and load configuration data. | - |
| `ConfigRenderer` | Class | Static facade for backwards compatibility with old code. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `render_and_load_config` | Method | Static method for backwards compatibility. | - |
| `data_generator.py` | Module | Module for generating data using agents. | `configuration`, `errors`, `orchestration`, `prompt_generation`, `response_processing`, `utilities` |
| `GuardEvaluationContext` | Class | Context for early guard evaluation. | - |
| `DataGenerator` | Class | Handles agent creation and data generation (Single Responsibility). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True as this generator supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO processing mode to let system choose. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_agent_with_data` | Method | Create an agent with the provided data and generate results. | - |
| `prompt_formatter.py` | Module | Module for prompt formatting and loading. | `errors`, `prompt_generation`, `utilities` |
| `PromptFormatter` | Class | Handles prompt formatting and loading (Single Responsibility). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_raw_prompt` | Method | Retrieve and process the raw prompt from the agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_prompt` | Method | Replace {reference.field} patterns in the prompt. | - |
| `prompt_handler.py` | Module | Module for loading and managing prompts from markdown files. | `file_io` |
| `PromptLoader` | Class | A class for loading and validating prompts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_prompt` | Method | Extracts a prompt from the content using the prompt_name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_prompt_names` | Method | Extracts all prompt names from the content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_unique_prompts` | Method | Validates that all prompt names in the content are unique. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_prompt_blocks` | Method | Ensure every prompt block is closed with an end token. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_prompt` | Method | Retrieve and generate a prompt based on the prompt name provided. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_few_shot_samples` | Method | Load random sample objects from JSON files in the sample output directory. | - |
| `prompt_preparation_service.py` | Module | Prompt Preparation Service - Unified prompt preparation for batch and realtime modes. | `errors`, `prompt_generation`, `utilities`, `validation` |
| `PromptPreparationRequest` | Class | Request parameters for prompt preparation. | - |
| `PromptPreparationResult` | Class | Result of prompt preparation. | - |
| `PromptPreparationService` | Class | Unified service for preparing prompts across batch and realtime modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid_mode` | Method | Validate if the given mode is supported. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_prompt_with_context` | Method | Unified entry point for prompt preparation (batch AND realtime). | - |
| `prompt_utils.py` | Module | Module for String Processing Functions | `errors`, `preprocessing` |
| `PromptUtils` | Class | A class for processing strings, including field reference replacement | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_dispatch_in_text` | Method | Process dispatch_task() calls in a single string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `inject_function_outputs_into_prompt` | Method | Replace multiple dispatch_task() calls in prompt_config with the result of their | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_field_references` | Method | Parse {reference.field} patterns from prompt. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve_field_reference` | Method | Resolve a field reference to its value in the context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `replace_field_references` | Method | Replace all {reference.field} patterns with their values. | - |
| `render_workflow.py` | Module | Module for rendering workflow templates with Jinja2 and YAML processing. | `errors`, `prompt_generation`, `utilities` |
| `normalize_yaml_indentation` | Function | Normalize common YAML indentation issues. | - |
| `render_pipeline_with_templates` | Function | Render a YAML pipeline configuration with Jinja2 templates. | - |
| `sample_enricher.py` | Module | Module for enriching prompts with few-shot samples. | `errors`, `file_io`, `prompt_generation` |
| `SampleEnricher` | Class | Handles enriching prompts with few-shot samples. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `append_few_shot_samples` | Method | Append few-shot samples to the prompt if configured. | - |
