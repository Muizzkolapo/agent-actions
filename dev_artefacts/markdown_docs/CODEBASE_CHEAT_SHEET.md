# Codebase Overview

This document provides a high-level overview of the `agent-actions` codebase, outlining its architecture, key components, and execution flow. It is intended to help developers understand the relationships between different parts of the application and contribute more effectively.

## Core Concepts

The `agent-actions` framework is designed to execute multi-agent workflows defined in YAML configuration files. Each workflow consists of a series of dependent agents that process data in a pipeline. Key features include:

- **Declarative Workflows:** Define complex agent interactions and data flows in simple YAML files.
- **Extensible Tooling:** Integrate custom Python functions (UDFs) to extend agent capabilities.
- **Configuration-Driven:** Centrally manage API keys, model names, and other settings in a default `agent_actions.yml` file.
- **CLI Interface:** A powerful command-line interface for running, managing, and debugging workflows.

## Execution Flow

The primary execution flow is initiated via the `run` command and proceeds as follows:

1.  **CLI Entrypoint (`agent_actions/cli/main.py`):**
    - The application starts here, using the `click` library to register and manage CLI commands (`run`, `init`, `clean`, etc.).
    - It handles top-level concerns like logging, versioning, and signal handling.

2.  **Run Command (`agent_actions/cli/commands/run_command.py`):**
    - The `run` command is the main entry point for executing a workflow.
    - It parses command-line arguments, including the agent name (`-a`), an optional path to user-defined functions (`-u`), and other flags.
    - It instantiates and calls `RunCommand.execute()` to start the process.

3.  **Path Resolution (`agent_actions/cli/services/project_paths_factory.py`):**
    - Before execution, `ProjectPathsFactory` is invoked to resolve and validate all necessary directory paths.
    - It ensures that critical directories like `prompt_store`, `agent_io`, and `schema` exist, creating them if necessary.

4.  **Configuration Loading (`agent_actions/handlers/config_handler.py`):**
    - `ConfigManager` is responsible for loading and merging configurations.
    - It reads the default settings from `agent_actions.yml`, including the default `tool_path` for user-defined functions.
    - It then loads the agent-specific workflow file (e.g., `my_agent.yml`), merges it with the defaults, validates the schema, and determines the execution order based on agent dependencies.

5.  **Workflow Orchestration (`agent_actions/workflow/agent_workflow.py`):**
    - `AgentWorkflow` is the central orchestrator that drives the execution.
    - It initializes the `ConfigManager` to get the workflow plan.
    - **Crucially, it checks for a `user_code_path` from the `-u` flag. If not provided, it falls back to the `tool_path` from the default configuration and adds it to the system path, making the UDFs importable.**
    - It iterates through the agents in the correct order, invoking the `AgentRunner` for each one.

6.  **Agent Execution (`agent_actions/core/agent_runner.py`):**
    - `AgentRunner` handles the execution of a single agent.
    - It uses a strategy pattern (`Initial`, `Intermediate`, `Terminal`) to determine how the agent should handle its inputs and outputs based on its position in the pipeline.
    - It sets up the I/O directories for the agent and processes the data.

## Key Directories & Files

- **`agent_actions.yml`:** The root configuration file for default settings, including API keys and the `tool_path`.
- **`agent_configs/`:** Contains the YAML files that define the agent workflows.
- **`prompt_store/`:** Stores the text prompts used by the agents.
- **`agent_io/`:** The default working directory for agent inputs, outputs, and intermediate staging data.
- **`tools/` (or custom tool path):** The directory where user-defined functions are stored.
- **`schema/`:** Contains YAML-based schema definitions for validating agent inputs and outputs.

This overview should provide a solid foundation for understanding the codebase. For more detailed information, refer to the docstrings and comments within the individual modules.

# Codebase Cheatsheet & Guide

This document provides a high-level overview of the `agent-actions` codebase, its architecture, and how to define and run agentic workflows.

## 1. Codebase Architecture

The project is structured around a modular pipeline for processing data using LLM-powered agents. The core components are designed to be extensible and configurable.

### Module Dependency Graph

The following graph illustrates the relationships between the major Python modules in the `agent_actions` directory. It shows how high-level components (like workflows and CLI commands) depend on lower-level handlers, processors, and vendor integrations.

*   **Direction**: An arrow from module `A` to `B` (`A -> B`) means `A` imports or depends on `B`.
*   **Color**: All nodes represent modules within the project.

```
digraph CodeGraph {
  rankdir="LR";
  node [shape=box, style="rounded,filled", fillcolor=lightblue];
  graph [splines=ortho];
  "__init__";
  "agent_builder";
  "agent_handlers";
  "agent_runner";
  "agent_strategies";
  "agent_workflow";
  "anthropic_vendor";
  "app";
  "base_loader";
  "base_validator";
  "base_vendor";
  "batch_command";
  "batch_data_loader";
  "batch_service";
  "clean_command";
  "cleaner";
  "cli";
  "cohere_vendor";
  "commands";
  "common";
  "config";
  "config_handler";
  "config_renderer";
  "config_schema";
  "config_types";
  "config_validator";
  "constants";
  "content_generator";
  "content_generators";
  "context_preprocessor";
  "core";
  "data_generator";
  "data_loaders";
  "data_processor";
  "data_transformer";
  "deepseek_vendor";
  "dependencies";
  "directory_handler";
  "directory_validator";
  "docs";
  "docs_command";
  "error_handler";
  "error_wrap";
  "exceptions";
  "few_shot_sample_manager";
  "file_handler";
  "file_reader";
  "file_writer";
  "gemini_vendor";
  "groq_llama";
  "handlers";
  "init";
  "init_command";
  "interfaces";
  "json_loader";
  "main";
  "manual_vendor_checks";
  "mistral_vendor";
  "models";
  "ollama_vendor";
  "openai_vendor";
  "output_handler";
  "output_processor";
  "path_validator";
  "processors";
  "project_paths_factory";
  "project_validator";
  "prompt_formatter";
  "prompt_handler";
  "prompt_processor";
  "prompt_utils";
  "prompt_validator";
  "render_command";
  "render_validator";
  "render_workflow";
  "response_transformer";
  "run_command";
  "sample_enricher";
  "schema_change";
  "schema_handler";
  "schema_validator";
  "service_logger";
  "services";
  "source_data_loader";
  "source_path_manager";
  "source_processor";
  "staging_content";
  "staging_loader";
  "staging_processor";
  "status_command";
  "string_transformer";
  "tabular_loader";
  "target_content_processor";
  "target_generator";
  "target_processor";
  "test_engine";
  "text_loader";
  "tooling";
  "tools";
  "tools_vendor";
  "topic_to_quiz_pipeline";
  "transformers";
  "utils";
  "validators";
  "vendors";
  "workflow";
  "xml_loader";
  "__init__" -> "anthropic_vendor";
  "__init__" -> "base_vendor";
  "__init__" -> "cohere_vendor";
  "__init__" -> "deepseek_vendor";
  "__init__" -> "gemini_vendor";
  "__init__" -> "groq_llama";
  "__init__" -> "mistral_vendor";
  "__init__" -> "ollama_vendor";
  "__init__" -> "openai_vendor";
  "__init__" -> "tools_vendor";
  "agent_builder" -> "config_schema";
  "agent_builder" -> "config_types";
  "agent_handlers" -> "agent_runner";
  "agent_handlers" -> "file_handler";
  "agent_handlers" -> "prompt_handler";
  "agent_runner" -> "agent_strategies";
  "agent_runner" -> "config_types";
  "agent_runner" -> "tooling";
  "agent_runner" -> "utils";
  "agent_strategies" -> "config_types";
  "agent_strategies" -> "utils";
  "agent_workflow" -> "agent_handlers";
  "agent_workflow" -> "config_handler";
  "agent_workflow" -> "file_handler";
  "anthropic_vendor" -> "base_vendor";
  "anthropic_vendor" -> "config_types";
  "app" -> "config";
  "base_loader" -> "interfaces";
  "batch_command" -> "batch_service";
  "batch_data_loader" -> "base_loader";
  "batch_service" -> "agent_workflow";
  "batch_service" -> "config_handler";
  "batch_service" -> "file_handler";
  "clean_command" -> "cleaner";
  "cohere_vendor" -> "base_vendor";
  "cohere_vendor" -> "config_types";
  "config";
  "config_handler" -> "config_schema";
  "config_handler" -> "file_handler";
  "config_renderer" -> "config";
  "config_renderer" -> "file_handler";
  "config_renderer" -> "project_paths_factory";
  "config_schema" -> "config_types";
  "config_validator" -> "base_validator";
  "config_validator" -> "config_schema";
  "config_validator" -> "file_handler";
  "config_validator" -> "path_validator";
  "config_validator" -> "schema_validator";
  "constants";
  "content_generator" -> "config_types";
  "content_generator" -> "context_preprocessor";
  "content_generator" -> "prompt_formatter";
  "content_generator" -> "response_transformer";
  "context_preprocessor" -> "prompt_utils";
  "core";
  "data_generator" -> "config_types";
  "data_generator" -> "content_generator";
  "data_generator" -> "file_handler";
  "data_generator" -> "interfaces";
  "data_processor" -> "config_types";
  "data_processor" -> "file_handler";
  "data_processor" -> "interfaces";
  "data_processor" -> "target_content_processor";
  "data_transformer" -> "string_transformer";
  "deepseek_vendor" -> "base_vendor";
  "deepseek_vendor" -> "config_types";
  "directory_handler" -> "file_handler";
  "directory_validator" -> "base_validator";
  "docs_command" -> "app";
  "error_handler" -> "service_logger";
  "error_wrap" -> "exceptions";
  "exceptions";
  "few_shot_sample_manager" -> "file_handler";
  "few_shot_sample_manager" -> "interfaces";
  "file_handler" -> "file_reader";
  "file_handler" -> "file_writer";
  "file_reader";
  "file_writer";
  "gemini_vendor" -> "base_vendor";
  "gemini_vendor" -> "config_types";
  "groq_llama" -> "base_vendor";
  "groq_llama" -> "config_types";
  "init";
  "init_command" -> "directory_handler";
  "init_command" -> "file_handler";
  "init_command" -> "project_paths_factory";
  "json_loader" -> "base_loader";
  "main" -> "cli";
  "main" -> "commands";
  "main" -> "error_handler";
  "main" -> "exceptions";
  "main" -> "service_logger";
  "mistral_vendor" -> "base_vendor";
  "mistral_vendor" -> "config_types";
  "ollama_vendor" -> "base_vendor";
  "ollama_vendor" -> "config_types";
  "openai_vendor" -> "base_vendor";
  "openai_vendor" -> "config_types";
  "output_handler" -> "file_handler";
  "output_handler" -> "interfaces";
  "output_processor" -> "directory_handler";
  "output_processor" -> "file_handler";
  "path_validator" -> "base_validator";
  "project_paths_factory" -> "config";
  "project_validator" -> "config_validator";
  "project_validator" -> "directory_validator";
  "project_validator" -> "prompt_validator";
  "project_validator" -> "render_validator";
  "prompt_formatter" -> "config_types";
  "prompt_formatter" -> "prompt_utils";
  "prompt_handler" -> "config_types";
  "prompt_handler" -> "file_handler";
  "prompt_handler" -> "schema_handler";
  "prompt_validator" -> "base_validator";
  "prompt_validator" -> "file_handler";
  "prompt_validator" -> "path_validator";
  "render_command" -> "config_renderer";
  "render_command" -> "render_workflow";
  "render_validator" -> "base_validator";
  "render_validator" -> "file_handler";
  "render_validator" -> "path_validator";
  "render_workflow" -> "config_handler";
  "render_workflow" -> "file_handler";
  "response_transformer" -> "config_types";
  "run_command" -> "agent_workflow";
  "run_command" -> "config_handler";
  "run_command" -> "file_handler";
  "run_command" -> "project_validator";
  "sample_enricher" -> "file_handler";
  "schema_change" -> "config_schema";
  "schema_handler" -> "config_schema";
  "schema_handler" -> "file_handler";
  "schema_validator" -> "base_validator";
  "service_logger";
  "source_data_loader" -> "batch_data_loader";
  "source_data_loader" -> "file_handler";
  "source_data_loader" -> "json_loader";
  "source_data_loader" -> "tabular_loader";
  "source_data_loader" -> "text_loader";
  "source_data_loader" -> "xml_loader";
  "source_path_manager" -> "file_handler";
  "staging_content" -> "file_handler";
  "staging_loader" -> "file_handler";
  "staging_processor" -> "file_handler";
  "staging_processor" -> "staging_content";
  "staging_processor" -> "staging_loader";
  "status_command" -> "file_handler";
  "string_transformer";
  "tabular_loader" -> "base_loader";
  "target_content_processor" -> "config_types";
  "target_content_processor" -> "data_transformer";
  "target_content_processor" -> "file_handler";
  "target_content_processor" -> "interfaces";
  "target_generator" -> "config_types";
  "target_generator" -> "data_generator";
  "target_generator" -> "data_processor";
  "target_generator" -> "few_shot_sample_manager";
  "target_generator" -> "file_handler";
  "target_generator" -> "output_handler";
  "target_generator" -> "source_data_loader";
  "target_generator" -> "source_path_manager";
  "target_generator" -> "staging_processor";
  "test_engine" -> "config";
  "test_engine" -> "vendors";
  "text_loader" -> "base_loader";
  "tooling" -> "config_types";
  "tools_vendor" -> "base_vendor";
  "tools_vendor" -> "config_types";
  "topic_to_quiz_pipeline";
  "utils";
  "xml_loader" -> "base_loader";
}
```

### Key Modules Explained

*   **`cli/`**: The command-line interface entry point. `main.py` uses the `click` library to define commands (e.g., `run`, `render`, `init`). It orchestrates the application's functionality based on user input.

*   **`workflow/`**: This directory contains the high-level business logic.
    *   `agent_workflow.py`: The core orchestrator. It reads the workflow configuration, resolves dependencies between agents, and executes them in the correct order.
    *   `render_workflow.py`: Handles the logic for the `render` command, allowing users to preview the final prompt that will be sent to the LLM.

*   **`handlers/`**: These modules are responsible for specific, isolated tasks.
    *   `config_handler.py`: Reads, parses, and validates the main YAML configuration file.
    *   `file_handler.py`: A wrapper for reading and writing files, providing a consistent interface for file I/O.
    *   `agent_handlers.py`: Manages the execution of a single agent, including setting up its dependencies and calling the appropriate services.
    *   `prompt_handler.py`: Resolves prompt references (e.g., `$TopicToQuizPipeline.Scenario_Generator`) by loading the corresponding prompt text from files.
    *   `schema_handler.py`: Loads and validates data schemas.

*   **`processors/`**: This is the heart of the data processing pipeline, broken into several sub-modules that handle data as it flows through the system.
    *   **`data_loaders/`**: Contains different loaders for various file formats (`.json`, `.csv`, `.txt`, etc.). `base_loader.py` defines the interface for all loaders.
    *   **`source_processor/`**: Manages the initial data loading. It uses the `data_loaders` to read the source files specified in the `run` command.
    *   **`staging_processor/`**: Prepares the data for the agent. This can involve cleaning, filtering, or transforming the data into a format the agent can work with.
    *   **`prompt_processor/`**: Constructs the final prompt sent to the LLM.
        *   `context_preprocessor.py`: Injects context from the source data into the prompt template.
        *   `prompt_formatter.py`: Formats the prompt with the data.
        *   `response_transformer.py`: Processes the raw output from the LLM, often converting it from a string to a structured format like JSON.
    *   **`target_processor/`**: Takes the processed output from an agent and prepares it for the next step. This includes generating the final data, handling few-shot samples, and managing output files.
    *   **`output_processor/`**: Writes the final results to the specified output directory.

*   **`models/`**: Defines the core data structures and schemas.
    *   `config_types.py`: Contains Python `TypedDict` classes that define the structure of the configuration objects. This provides static type checking and clarity.
    *   `config_schema.py`: Defines the validation schemas (using libraries like Pydantic or Marshmallow) that ensure the YAML configuration is correct.

*   **`vendors/`**: This directory contains integrations with third-party LLM providers.
    *   `base_vendor.py`: Defines the abstract base class that all vendor-specific clients must implement. This ensures a consistent interface for making API calls.
    *   Each other file (`openai_vendor.py`, `gemini_vendor.py`, etc.) implements the specifics for a particular LLM provider.

*   **`core/`**: Contains fundamental utilities and strategies that are used across the application.
    *   `agent_runner.py`: The engine that executes a single agent's logic.
    *   `agent_strategies.py`: Defines different strategies for how an agent might run (e.g., batch processing vs. single-record processing).

*   **`transformers/`**: Contains modules for data transformation.
    *   `data_transformer.py`: A generic transformer for manipulating data.
    *   `string_transformer.py`: Specific transformations for string data.

---

## 2. Workflow Definition

Workflows are defined in YAML files that specify a list of agents to be executed in a sequence. The system processes this YAML to run a multi-step, data-transformation pipeline.

### Sample Workflow: `explainer_list`

This example defines a three-agent pipeline to generate quiz scenarios from a topic.

```yaml
explainer_list:
  - agent_type: Overview_Summarizer
    dependencies: []
    api_key: OPENAI_API_KEY
    model_vendor: openai
    model_name: gpt-4o-mini
    schema_name: summary
    few_shot: 0
    is_operational: True
    run_mode: batch
    json_mode: true
    granularity: Record        
    prompt: $summary.summarizer

  - agent_type: ScenarioGenerator
    dependencies: ["Overview_Summarizer"]
    api_key: OPENAI_API_KEY
    model_vendor: openai
    model_name: gpt-4o-mini
    schema_name: question_schema
    few_shot: 0
    is_operational: True
    run_mode: batch
    side_collection:
      - id
      - url
      - topic
      - key_ideas
      - explanation
      - ask_code
      - code_sample
      - batch_name
    json_mode: true
    granularity: Record
    remove_collection:
      - decision
      - reasoning
      - total_tokens
      - source
      - title
      - page_content
      - ask_code
      - batch_name
    prompt: $TopicToQuizPipeline.Scenario_Generator 
    tokenizer_model: o200k_base
    split_method: tiktoken
    prompt_debug: false

  - agent_type: ScenarioFormatter
    dependencies: ["ScenarioGenerator"]
    # ... (other parameters similar to ScenarioGenerator)
    prompt: $TopicToQuizPipeline.Scenario_Generator_formatter
```

### Workflow Configuration Cheatsheet

This section explains the key parameters for defining an agent in the workflow YAML.

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `agent_type` | String | Yes | A unique name for the agent within the workflow. |
| `dependencies` | List | Yes | A list of `agent_type`s that must run before this agent. An empty list `[]` means it's a starting agent. |
| `api_key` | String | Yes | The environment variable name for the LLM API key (e.g., `OPENAI_API_KEY`). |
| `model_vendor` | String | Yes | The LLM provider to use. Must match a module in `agent_actions/vendors/`. (e.g., `openai`, `gemini`). |
| `model_name` | String | Yes | The specific model name from the vendor (e.g., `gpt-4o-mini`). |
| `schema_name` | String | Yes | The name of the output schema for data validation. Schemas are defined elsewhere. |
| `prompt` | String | Yes | The prompt to be used. A `$` prefix indicates a reference to a prompt file (e.g., `$summary.summarizer`). |
| `run_mode` | String | No | How the agent processes data. `batch` is a common value. Defaults to `batch`. |
| `granularity` | String | No | The level at which data is processed (e.g., `Record` for row-by-row). Defaults to `Record`. |
| `is_operational`| Boolean | No | If `False`, the agent is skipped. Useful for debugging. Defaults to `True`. |
| `json_mode` | Boolean | No | Whether to enable JSON output mode from the LLM. Defaults to `False`. |
| `use_few_shot` | Integer | No | Number of few-shot examples to use. `0` disables it. Defaults to `0`. |
| `side_collection`| List | No | A list of column names to **keep** and merge from the input data into the output. |
| `remove_collection`| List | No | A list of column names to **remove** from the input data before processing. |
| `tokenizer_model`| String | No | The tokenizer to use for splitting text (e.g., `o200k_base`). |
| `split_method` | String | No | The method for splitting text (e.g., `tiktoken`). |

---

## 3. How to Run a Workflow

The primary interface for executing these workflows is the command-line tool.

### Core Commands

*   **`agent-actions run ...`**: Executes an agent workflow.
    *   `--config-file`: Path to the YAML workflow definition.
    *   `--source-file`: Path to the input data file.
    *   `--output-dir`: Directory to save the results.
    *   `--agent-name`: (Optional) Run only a specific agent from the config.

*   **`agent-actions render ...`**: Renders a prompt without executing it, which is useful for debugging.
    *   `--config-file`: Path to the YAML workflow definition.
    *   `--source-file`: Path to the input data file.
    *   `--agent-name`: The specific agent whose prompt you want to render.

*   **`agent-actions init`**: Initializes a new project structure with default directories.

*   **`agent-actions status`**: Checks the status of processed files.

### Example Execution

To run the `ScenarioGenerator` agent from the sample workflow:

```bash
agent-actions run \
  --config-file path/to/your/workflow.yaml \
  --source-file path/to/input/data.csv \
  --output-dir path/to/output/ \
  --agent-name ScenarioGenerator
```

---

## 4. For Large Language Models: Core Concepts & Data Flow

This section provides the essential information an LLM needs to reason about the codebase, make modifications, and understand the data lifecycle.

### Core Philosophy

1.  **Configuration over Code**: Workflows are defined in YAML. The Python code is a generic engine that executes the declarative workflow. To change the behavior, you should almost always modify the YAML configuration, not the Python code.
2.  **Modularity and Extensibility**: Each part of the system (data loading, prompt formatting, vendor integration) is a distinct module with a clear interface. This makes it easy to add new functionality without breaking existing code.
3.  **Data Immutability**: The pipeline generally treats data as immutable. Each agent receives data from its dependency, transforms it, and passes a new version to the next agent. The original source data is never modified.
4.  **Explicit Dependencies**: The `dependencies` list in the workflow configuration creates a Directed Acyclic Graph (DAG). The engine uses this to determine the execution order.

### Data Flow & Execution Lifecycle (`agent-actions run`)

Understanding the data flow is critical. Here is the step-by-step lifecycle of a single agent execution:

1.  **CLI Entrypoint**: The `run` command in `cli/main.py` is invoked.
2.  **Config Loading**: `workflow/agent_workflow.py` calls `handlers/config_handler.py` to load and validate the workflow YAML.
3.  **Dependency Resolution**: The workflow identifies the correct agent to run based on the `--agent-name` flag and its `dependencies`.
4.  **Source Data Loading**:
    *   If the agent has dependencies, it loads the output file(s) from the predecessor agents.
    *   If the agent has no dependencies, `processors/source_processor/` is used to load the initial data from the `--source-file`. It uses the appropriate loader from `processors/data_loaders/`.
5.  **Prompt Preparation**: `handlers/prompt_handler.py` reads the prompt template specified by the `prompt` key (e.g., `$TopicToQuizPipeline.Scenario_Generator`).
6.  **Data Processing & Prompt Injection**:
    *   The `processors/prompt_processor/` takes the loaded data and the prompt template.
    *   It iterates through each record (if `granularity: Record`), using `context_preprocessor.py` to inject the data into the prompt template.
7.  **LLM Vendor Call**: The formatted prompt is sent to the appropriate LLM vendor specified by `model_vendor`. The call is made through the standardized interface in `vendors/base_vendor.py`.
8.  **Response Transformation**: The raw response from the LLM is processed by `response_transformer.py`. If `json_mode: true`, it parses the JSON string.
9.  **Output Generation**: `processors/target_processor/` and `processors/output_processor/` handle the final steps:
    *   The transformed response is merged with any columns from the original data specified in `side_collection`.
    *   The final data is written to a new file in the output directory. The filename typically includes the `agent_type`.

### Directory Structure Conventions

*   **Prompts**: All prompt files are expected to be in a `prompts/` directory. The reference `$summary.summarizer` maps to `prompts/summary/summarizer.prompt`.
*   **Schemas**: All data validation schemas are in a `schemas/` directory.
*   **Few-Shot Samples**: Few-shot examples are stored in a `few_shot_samples/` directory.

### How to Extend the System

*   **To Add a New LLM Vendor**:
    1.  Create a new file in `agent_actions/vendors/`, e.g., `my_new_vendor.py`.
    2.  Create a class that inherits from `BaseVendor` in `base_vendor.py`.
    3.  Implement the required methods, especially `invoke()`.
    4.  Update the `__init__.py` in the `vendors` directory to include your new vendor.

*   **To Add a New Data Loader**:
    1.  Create a new file in `agent_actions/processors/data_loaders/`, e.g., `my_new_loader.py`.
    2.  Create a class that inherits from `BaseLoader` in `base_loader.py`.
    3.  Implement the `load_data()` method.
    4.  Update `source_data_loader.py` to use your new loader based on the file extension or another condition.
