# Orchestration Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_level_executor.py` | Module | Action-level execution orchestration module. | `errors` |
| `ParallelExecutionParams` | Class | Parameters for executing parallel agents. | - |
| `LevelExecutionParams` | Class | Parameters for executing a level. | - |
| `ActionLevelOrchestrator` | Class | Orchestrates agent execution by dependency levels. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `compute_execution_levels` | Method | Compute execution levels from dependency graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_parallel_execution` | Method | Determine if workflow should use parallel execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_execution_levels` | Method | Log execution levels for user transparency. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_level_async` | Method | Execute all agents in a level asynchronously. | - |
| `agent_executor.py` | Module | Single agent execution module. | `docs`, `llm_invocation` |
| `ExecutorDependencies` | Class | Dependencies for AgentExecutor. | - |
| `AgentExecutionContext` | Class | Context for executing an agent. | - |
| `ExecutionMetrics` | Class | Metrics from agent execution. | - |
| `AgentRunParams` | Class | Parameters for agent execution. | - |
| `AgentExecutionResult` | Class | Result of agent execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `duration` | Method | Get duration from metrics. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `tokens` | Method | Get tokens from metrics. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `model_vendor` | Method | Get model_vendor from metrics. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `model_name` | Method | Get model_name from metrics. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `files_processed` | Method | Get files_processed from metrics. | - |
| `AgentExecutor` | Class | Executes individual agents with full lifecycle management. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_agent_sync` | Method | Execute a single agent synchronously. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_agent_async` | Method | Execute a single agent asynchronously. | - |
| `agent_runner.py` | Module | Module for managing and executing agents with different strategies in a workflow. | `errors`, `file_io`, `orchestration` |
| `FileProcessParams` | Class | Parameters for processing files. | - |
| `FileLocationParams` | Class | File location parameters. | - |
| `SingleFileProcessParams` | Class | Parameters for processing a single file. | - |
| `ProcessGenerateParams` | Class | Parameters for process_and_generate_for_agent method. | - |
| `AgentRunner` | Class | Manages the execution of agents using different strategies in a workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_folder` | Method | Retrieves the agent folder using FileHandler. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `setup_directories` | Method | Sets up input and output directories for the agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_files` | Method | Walks through the upstream data directories, processing each file with the given strategy, | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_and_generate_for_agent` | Method | Processes and generates data for an agent using the provided strategy. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `run_agent` | Method | Runs an agent with the appropriate strategy based on its position. | - |
| `agent_strategies.py` | Module | Module defining strategy classes for different agent execution patterns. | `orchestration`, `preprocessing` |
| `StrategyExecutionParams` | Class | Parameters for strategy execution. | - |
| `AgentStrategy` | Class | Abstract base class for agent execution strategies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the strategy for a specific agent and file. | - |
| `InitialStrategy` | Class | Strategy for the initial agent in a workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the initial agent strategy. | - |
| `StandardStrategy` | Class | Standard strategy for executing agents (formerly Intermediate/Terminal). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the standard agent strategy. | - |
| `agent_workflow.py` | Module | Agent workflow orchestration. | `configuration`, `errors`, `input_loading`, `llm_invocation`, `logging`, `orchestration`, `prompt_generation` |
| `AgentWorkflow` | Class | Orchestrates multi-agent workflow execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `state` | Method | Get workflow state from runtime context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `console` | Method | Get console from runtime context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `agent_name` | Method | Get agent name from metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execution_order` | Method | Get execution order from metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `agent_indices` | Method | Get agent indices from metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `agent_configs` | Method | Get agent configs from metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `child_pipeline` | Method | Get child pipeline from metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `async_run` | Method | Execute workflow level-by-level with parallelism within each level. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `run` | Method | Execute workflow sequentially. | - |
| `application_container.py` | Module | Application Container for managing all DI configuration and bootstrapping. | `configuration`, `errors`, `input_loading`, `llm_invocation`, `orchestration`, `preprocessing`, `prompt_generation`, `state_management` |
| `ApplicationContainer` | Class | Main application container that manages all dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_runner` | Method | Create an AgentRunner with all dependencies injected. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processor_factory` | Method | Get the processor factory for creating processors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_dependency_container` | Method | Get the underlying dependency container. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_target_content_processor` | Method | Create a TargetContentProcessor with all dependencies injected. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_for_environment` | Method | Create application container for specific environment. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_for_testing` | Method | Create application container configured for testing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_logging` | Method | Configure application logging based on container settings. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `health_check` | Method | Perform health check on all registered services. | - |
| `artifact_linker.py` | Module | Artifact linking for workflow input/output management. | - |
| `ArtifactLinker` | Class | Manages artifact linking between workflows via manifest files. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `link_workflow_artifacts` | Method | Link source workflow's output to target workflow via manifest. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `link_upstream_artifacts` | Method | Link upstream workflow's output to current workflow via manifest. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `link_downstream_artifacts` | Method | Link current workflow's output to downstream workflow via manifest. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_latest_node_dir` | Method | Find the most recent node directory in target. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_safe_path` | Method | Validate path doesn't escape base directory (path traversal protection). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `read_manifest` | Method | Read upstream manifest from agent_io directory. | - |
| `batch_manager.py` | Module | Batch job lifecycle management module. | `errors` |
| `BatchLifecycleManager` | Class | Manages batch job lifecycle and result processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_batch_agent` | Method | Handle batch agent status checking and result processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_batch_submission` | Method | Check if batch jobs were submitted for an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `cleanup_passthrough_marker` | Method | Remove passthrough marker after processing. | - |
| `dependency_injection.py` | Module | Dependency Injection Framework for Agent Actions. | `errors` |
| `ServiceLifetime` | Class | Service lifetime constants. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid` | Method | Check if a lifetime value is valid. | - |
| `ServiceDescriptor` | Class | Describes how a service should be created and managed. | - |
| `DependencyContainer` | Class | Lightweight dependency injection container. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_singleton` | Method | Register a singleton service. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_transient` | Method | Register a transient service. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_factory` | Method | Register a factory function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_instance` | Method | Register a specific instance. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get` | Method | Resolve a dependency. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has` | Method | Check if a service is registered. | - |
| `ProcessorRegistry` | Class | Registry for managing processor implementations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_processor` | Method | Decorator to register a processor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_loader` | Method | Decorator to register a data loader. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_generator` | Method | Decorator to register a generator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_service` | Method | Decorator to register a service. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processor` | Method | Get a processor class by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_loader` | Method | Get a loader class by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_generator` | Method | Get a generator class by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_service` | Method | Get a service class by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_processors` | Method | List all registered processors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_loaders` | Method | List all registered loaders. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_generators` | Method | List all registered generators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_services` | Method | List all registered services. | - |
| `ProcessorFactory` | Class | Factory for creating processors with dependency injection. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_processor` | Method | Create a processor instance with injected dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_loader` | Method | Create a loader instance with injected dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_generator` | Method | Create a generator instance with injected dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_service` | Method | Create a service instance with injected dependencies. | - |
| `loop_correlator.py` | Module | Loop output correlation system for parallel map-reduce patterns. | `errors` |
| `JsonLoadParams` | Class | Parameters for loading JSON from file. | - |
| `LoopOutputCorrelator` | Class | Correlates outputs from parallel loop executions for downstream consumption. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `detect_explicit_loop_consumption` | Method | Detect agents with explicit loop consumption configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_correlated_input` | Method | Prepare correlated input directory for an agent that depends on loop outputs. | - |
| `node_mapper.py` | Module | Module for mapping agent names to node indices. | - |
| `NodeMappingService` | Class | Service for mapping agent names to their node indices in a workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_agent_index_map` | Method | Build a mapping of agent names to their node indices. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_node_index_for_agent` | Method | Get the node index for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_node_prefix` | Method | Get the node prefix for a given index. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_node_directory_name` | Method | Get the full node directory name for an agent. | - |
| `output_manager.py` | Module | Agent output management module. | `orchestration` |
| `OutputManagerConfig` | Class | Configuration for AgentOutputManager. | - |
| `AgentOutputManager` | Class | Manages agent output operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_previous_outputs` | Method | Get outputs from previously executed agents with enhanced metadata. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_passthrough_output` | Method | Create passthrough output for a skipped agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_upstream_directories` | Method | Get upstream data directories for an agent, resolving dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `setup_correlation_wrapper` | Method | Create a correlation-aware setup_directories wrapper if needed. | - |
| `skip_evaluator.py` | Module | Agent skip condition evaluation module. | `preprocessing` |
| `SkipStrategy` | Class | Base strategy for evaluating skip conditions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_skip` | Method | Determine if agent should be skipped. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_strategy_name` | Method | Get name of this strategy for logging. | - |
| `SkipConditionStrategy` | Class | Strategy for evaluating 'skip_condition' field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_strategy_name` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_skip` | Method | Evaluate skip_condition using modern WHERE filter. | - |
| `GuardStrategy` | Class | Strategy for evaluating 'guard' with scope='agent'. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_strategy_name` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_skip` | Method | Evaluate agent-level guard condition. | - |
| `LegacySkipIfStrategy` | Class | Strategy for evaluating legacy 'skip_if' field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_strategy_name` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_skip` | Method | Evaluate legacy skip_if condition using modern WHERE filter. | - |
| `SkipEvaluator` | Class | Orchestrates skip condition evaluation using strategy pattern. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_skip_agent` | Method | Determine if an agent should be skipped based on skip conditions. | - |
| `state_manager.py` | Module | Agent workflow state management module. | - |
| `AgentStateManager` | Class | Manages agent execution state persistence and queries. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `update_status` | Method | Update agent status and save to file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_status` | Method | Get current status of an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_status_details` | Method | Get full status details for an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_completed` | Method | Check if agent is completed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_batch_submitted` | Method | Check if agent has batch jobs submitted. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_failed` | Method | Check if agent has failed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_pending_agents` | Method | Get list of agents that are not completed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_submitted_agents` | Method | Get list of agents with batch jobs submitted. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_failed_agents` | Method | Get list of failed agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `mark_running_as_failed` | Method | Mark any agent in 'running' or 'checking_batch' status as failed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_summary` | Method | Get summary counts of agent statuses. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_workflow_complete` | Method | Check if all agents are completed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_any_failed` | Method | Check if any agent has failed. | - |
| `target_generator.py` | Module | Module for target data generation based on configuration. | `configuration`, `errors`, `file_io`, `input_loading`, `llm_invocation`, `orchestration`, `utilities` |
| `GeneratorConfig` | Class | Configuration for TargetGenerator. | - |
| `BatchGenerationParams` | Class | Parameters for batch generation. | - |
| `FilePathsConfig` | Class | File paths configuration. | - |
| `GenerateParams` | Class | Parameters for target generation. | - |
| `TargetGenerator` | Class | Responsible for generating target data from input files based on | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `generate` | Method | Static method for generating target data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Process input file and generate output. | - |
| `create_target_generator` | Function | Factory function for creating a TargetGenerator instance. | - |
| `create_target_generator_from_params` | Function | Factory function for creating a TargetGenerator instance from individual parameters. | - |
| `workflow_dependency_orchestrator.py` | Module | Workflow dependency orchestration for upstream/downstream execution. | `logging`, `orchestration` |
| `WorkflowDependencyOrchestrator` | Class | Orchestrates upstream and downstream workflow dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `workspace_index` | Method | Get or create workspace index (lazy initialization). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve_upstream_workflows` | Method | Recursively resolve and execute upstream dependencies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve_downstream_workflows` | Method | Execute all downstream workflows after current workflow completes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `resolve_upstream_and_initialize` | Method | Initialize correlation context and resolve upstream dependencies. | - |
| `workflow_models.py` | Module | Dataclass models for agent workflow orchestration. | - |
| `WorkflowPaths` | Class | Path configuration for workflow. | - |
| `WorkflowConfig` | Class | Configuration container for workflow initialization. | - |
| `WorkflowState` | Class | Runtime state for workflow execution. | - |
| `RuntimeContext` | Class | Runtime context for workflow execution. | - |
| `WorkflowMetadata` | Class | Workflow configuration metadata. | - |
| `AgentLogParams` | Class | Parameters for logging agent results. | - |
| `CoreServices` | Class | Core execution services. | - |
| `SupportServices` | Class | Supporting services for workflow execution. | - |
| `WorkflowServices` | Class | Container for workflow orchestration services. | - |
| `workspace_index.py` | Module | Workspace index for building and traversing workflow dependency graphs. | `errors` |
| `WorkspaceIndex` | Class | Scans and indexes all workflows in a workspace to build | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `scan_workspace` | Method | Scan all agent_config/*.yml files to build dependency graphs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `topological_sort_downstream` | Method | Return all downstream workflows in topological execution order. | - |
