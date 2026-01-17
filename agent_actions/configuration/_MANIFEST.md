# Configuration Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Base classes for artifact system. | - |
| `ArtifactMetadata` | Class | Standard metadata for all artifacts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert metadata to dictionary format. | - |
| `SecurityError` | Class | Security-related artifact errors. | - |
| `BaseArtifact` | Class | Base class for all artifacts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert artifact to dictionary format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save` | Method | Persist artifact to a JSON file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load` | Method | Load artifact from JSON file with security validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_dict` | Method | Create artifact from dictionary. | - |
| `base_async_processor.py` | Module | Base async processor implementation with proper async patterns. | - |
| `BaseAsyncProcessor` | Class | Base class providing standardized async processing patterns. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True as this is an async-capable processor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return ASYNC as the preferred processing mode. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_items_parallel` | Method | Process multiple items in parallel with proper concurrency control. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_items_sequential` | Method | Process items sequentially (useful for order-dependent operations). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `read_file_async` | Method | Read file content asynchronously using proper async I/O. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write_file_async` | Method | Write file content asynchronously using proper async I/O. | - |
| `AsyncProcessorMixin` | Class | Mixin to add async capabilities to existing processors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True if async capabilities are enabled. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO to let the system choose based on context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `enable_async` | Method | Enable async processing capabilities. | - |
| `ProcessingContext` | Class | Context for managing processing state and configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_async` | Method | Determine if async processing should be used based on context. | - |
| `config.py` | Module | - | - |
| `core_bootstrap.py` | Module | Dependency Injection Configuration for Agent Actions. | `configuration`, `llm_invocation`, `orchestration`, `preprocessing`, `prompt_generation`, `state_management` |
| `DIConfigurator` | Class | Configures the dependency container with application services. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_container` | Method | Configure the container with all dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_processor_factory` | Method | Create a processor factory with the configured container. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_for_testing` | Method | Configure container for testing with mocks. | - |
| `ConfigurationProfile` | Class | Predefined configuration profiles for different environments. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `development` | Method | Development configuration profile. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `production` | Method | Production configuration profile. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `testing` | Method | Testing configuration profile. | - |
| `di_configurator.py` | Module | Dependency Injection Configuration for Agent Actions. | `configuration`, `llm_invocation`, `logging`, `orchestration`, `preprocessing`, `prompt_generation`, `state_management` |
| `DIConfigurator` | Class | Configures the dependency container with application services. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_container` | Method | Configure the container with all dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_processor_factory` | Method | Create a processor factory with the configured container. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_for_testing` | Method | Configure container for testing with mocks. | - |
| `ConfigurationProfile` | Class | Predefined configuration profiles for different environments. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `development` | Method | Development configuration profile. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `production` | Method | Production configuration profile. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `testing` | Method | Testing configuration profile. | - |
| `factory.py` | Module | Factory module for creating components with dependency injection. | `orchestration` |
| `application_container_context` | Function | Context manager for proper DI container lifecycle management. | - |
| `create_agent_runner` | Function | Create an AgentRunner with proper dependency injection. | - |
| `init.py` | Module | Module for initializing new Agent Actions projects. | `utilities` |
| `ProjectInitializer` | Class | Initialize new Agent Actions projects with standard structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_directory` | Method | Create a directory if it doesn't exist. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_file` | Method | Create a file if it doesn't exist. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `init_project` | Method | Initialize the new Agent Actions project by creating directories | - |
| `initializer.py` | Module | Application initializer with startup validation. | `orchestration`, `state_management` |
| `initialize_application` | Function | Initialize the application with full startup validation. | - |
| `application_container_context` | Function | Context manager for proper DI container lifecycle management. | - |
| `create_agent_runner` | Function | Create an AgentRunner with proper dependency injection. | - |
| `interfaces.py` | Module | Common interfaces for processors. | - |
| `ProcessingMode` | Class | Defines the processing mode for processors. | - |
| `IAsyncCapable` | Class | Interface for components that support async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True if this component supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return the preferred processing mode for this component. | - |
| `ILoader` | Class | Base interface for all loaders. | - |
| `IProcessor` | Class | Base interface for all processors. | - |
| `IGenerator` | Class | Base interface for all generators. | - |
| `IDataLoader` | Class | Interface for data loading operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_data` | Method | Load data from the given file path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_data_async` | Method | Async version of load_data. Default implementation uses sync version. | - |
| `ISourceDataLoader` | Class | Interface for source data loading operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_data` | Method | Load source data from the source directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_data_async` | Method | Async version of load_source_data. Default implementation uses sync version. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_source_data` | Method | Save source data to the source directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_source_data_async` | Method | Async version of save_source_data. Default implementation uses sync version. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_content` | Method | Load specific content from source file by source_guid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_content_async` | Method | Async version of load_source_content. Default implementation uses sync version. | - |
| `IContentProcessor` | Class | Interface for content processors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Process a list of data items. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_async` | Method | Async version of process. Default implementation uses sync version. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_for_side_output` | Method | Process data and separate into main and side outputs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_for_side_output_async` | Method | Async version of process_for_side_output. Default implementation. | - |
| `IDataProcessor` | Class | Interface for data processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_item` | Method | Process a single data item. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_item_async` | Method | Async version of process_item. Default implementation uses sync version. | - |
| `new_format_schema.py` | Module | Schema definitions for the new workflow format. | `errors`, `llm_invocation`, `response_processing` |
| `ActionKind` | Class | Types of actions in the workflow. | - |
| `Granularity` | Class | Granularity levels for action execution. | - |
| `LoopMode` | Class | Loop execution modes. | - |
| `LoopConfig` | Class | Configuration for loop-based actions. | - |
| `MergePattern` | Class | Patterns for merging loop outputs. | - |
| `LoopConsumptionConfig` | Class | Configuration for consuming loop outputs. | - |
| `ActionConfig` | Class | Configuration for a workflow action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_guard` | Method | Validate guard expressions for safety. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_retry` | Method | Validate retry configuration. | - |
| `DefaultsConfig` | Class | Default configuration applied to all actions. | - |
| `DependencyEdge` | Class | Represents a dependency relationship in the execution plan. | - |
| `WorkflowConfigV2` | Class | New workflow configuration format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action` | Method | Get an action by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_dependency_graph` | Method | Extract dependency graph from action definitions. | - |
