"""
Domain-Driven Restructure Migration Map

This file defines the complete mapping from old paths to new paths.
Used by migrate.py to execute the restructure.
"""

# Format: "old_module_path" -> "new_module_path"
# Paths are relative to agent_actions/

DIRECTORY_STRUCTURE = [
    # New top-level domains
    "workflow",
    "workflow/managers",
    "workflow/parallel",
    "processing",
    "processing/guards",
    "processing/recovery",
    "processing/transform",
    "prompt",
    "prompt/context",
    "input",
    "input/loaders",
    "input/preprocessing",
    "input/preprocessing/chunking",
    "input/preprocessing/parsing",
    "input/preprocessing/parsing/operator_registry",
    "input/preprocessing/field_resolution",
    "input/preprocessing/transformation",
    "input/preprocessing/filtering",
    "input/preprocessing/staging",
    "input/context",
    "output",
    "output/response",
    "llm",
    "llm/providers",
    "llm/providers/anthropic",
    "llm/providers/openai",
    "llm/providers/gemini",
    "llm/providers/groq",
    "llm/providers/mistral",
    "llm/providers/cohere",
    "llm/providers/ollama",
    "llm/providers/agac",
    "llm/batch",
    "llm/batch/processing",
    "llm/batch/infrastructure",
    "llm/batch/services",
    "llm/realtime",
    "llm/realtime/services",
    "llm/config",
    "config",
    "config/di",
    "validation",
    "validation/preflight",
    "validation/static_analysis",
    "validation/agent",
    "validation/orchestration",
    "validation/utils",
    "cli",
    "cli/commands",
    "cli/renderers",
    "cli/utils",
    "tooling",
    "tooling/lsp",
    "tooling/docs",
    "tooling/docs/site",
    "logging",
    "logging/errors",
    "logging/errors/formatters",
    "logging/errors/services",
    "errors",
    "models",
    "utils",
    "utils/id_generation",
    "utils/field_management",
    "utils/lineage",
    "utils/metadata",
    "utils/correlation",
    "utils/transformation",
    "utils/transformation/strategies",
    "utils/udf_management",
    "utils/udf_management/type_conversion",
    "skills",
]

# File migrations: old_path -> new_path (relative to agent_actions/)
FILE_MIGRATIONS = {
    # ============================================================
    # MODELS (shared data types) - Move first, no internal deps
    # ============================================================
    "models/action_schema.py": "models/action.py",
    "models/__init__.py": "models/__init__.py",
    # ============================================================
    # ERRORS - Foundation, move early
    # ============================================================
    "errors/base.py": "errors/base.py",
    "errors/common.py": "errors/common.py",
    "errors/configuration.py": "errors/configuration.py",
    "errors/external_services.py": "errors/external.py",
    "errors/filesystem.py": "errors/filesystem.py",
    "errors/operations.py": "errors/operations.py",
    "errors/preflight.py": "errors/preflight.py",
    "errors/processing.py": "errors/processing.py",
    "errors/resources.py": "errors/resources.py",
    "errors/validation.py": "errors/validation.py",
    "errors/__init__.py": "errors/__init__.py",
    # ============================================================
    # UTILS (minimal, generic utilities)
    # ============================================================
    "utilities/constants.py": "utils/constants.py",
    "utilities/dict_utils.py": "utils/dict.py",
    "utilities/module_loader.py": "utils/module_loader.py",
    "utilities/safe_format.py": "utils/safe_format.py",
    "utilities/output_splitter.py": "utils/output_splitter.py",
    "utilities/passthrough_item_builder.py": "utils/passthrough_builder.py",
    "utilities/path_utils.py": "utils/path_utils.py",
    "utilities/tools_resolver.py": "utils/tools_resolver.py",
    "utilities/__init__.py": "utils/__init__.py",
    # Utils subdirectories
    "utilities/id_generation/id_generator.py": "utils/id_generation/generator.py",
    "utilities/id_generation/__init__.py": "utils/id_generation/__init__.py",
    "utilities/field_management/field_manager.py": "utils/field_management/manager.py",
    "utilities/field_management/__init__.py": "utils/field_management/__init__.py",
    "utilities/lineage/lineage_builder.py": "utils/lineage/builder.py",
    "utilities/lineage/__init__.py": "utils/lineage/__init__.py",
    "utilities/metadata/metadata_extractor.py": "utils/metadata/extractor.py",
    "utilities/metadata/metadata_types.py": "utils/metadata/types.py",
    "utilities/metadata/__init__.py": "utils/metadata/__init__.py",
    "utilities/correlation/loop_id_generator.py": "utils/correlation/loop_id.py",
    "utilities/correlation/__init__.py": "utils/correlation/__init__.py",
    "utilities/transformation/passthrough_transformer.py": "utils/transformation/passthrough.py",
    "utilities/transformation/__init__.py": "utils/transformation/__init__.py",
    "utilities/transformation/strategies/base.py": "utils/transformation/strategies/base.py",
    "utilities/transformation/strategies/context_scope_strategies.py": "utils/transformation/strategies/context_scope.py",
    "utilities/transformation/strategies/precomputed_strategies.py": "utils/transformation/strategies/precomputed.py",
    "utilities/transformation/strategies/__init__.py": "utils/transformation/strategies/__init__.py",
    "utilities/udf_management/tooling.py": "utils/udf_management/tooling.py",
    "utilities/udf_management/udf_registry.py": "utils/udf_management/registry.py",
    "utilities/udf_management/__init__.py": "utils/udf_management/__init__.py",
    "utilities/udf_management/type_conversion/converters.py": "utils/udf_management/type_conversion/converters.py",
    "utilities/udf_management/type_conversion/__init__.py": "utils/udf_management/type_conversion/__init__.py",
    # Processor helpers -> processing domain
    "utilities/processor/processor_helpers.py": "processing/helpers.py",
    "utilities/processor/error_handling.py": "processing/error_handling.py",
    "utilities/processor/__init__.py": "processing/processor_init.py",  # Will merge
    # ============================================================
    # LOGGING
    # ============================================================
    "logging/factory.py": "logging/factory.py",
    "logging/config.py": "logging/config.py",
    "logging/context.py": "logging/context.py",
    "logging/formatters.py": "logging/formatters.py",
    "logging/filters.py": "logging/filters.py",
    "logging/__init__.py": "logging/__init__.py",
    # User errors -> logging/errors
    "shared/user_errors/user_error.py": "logging/errors/user_error.py",
    "shared/user_errors/error_translator.py": "logging/errors/translator.py",
    "shared/user_errors/__init__.py": "logging/errors/__init__.py",
    "shared/user_errors/formatters/error_formatter_base.py": "logging/errors/formatters/base.py",
    "shared/user_errors/formatters/api_formatter.py": "logging/errors/formatters/api.py",
    "shared/user_errors/formatters/authentication_formatter.py": "logging/errors/formatters/authentication.py",
    "shared/user_errors/formatters/configuration_formatter.py": "logging/errors/formatters/configuration.py",
    "shared/user_errors/formatters/file_formatter.py": "logging/errors/formatters/file.py",
    "shared/user_errors/formatters/function_formatter.py": "logging/errors/formatters/function.py",
    "shared/user_errors/formatters/generic_formatter.py": "logging/errors/formatters/generic.py",
    "shared/user_errors/formatters/model_formatter.py": "logging/errors/formatters/model.py",
    "shared/user_errors/formatters/template_formatter.py": "logging/errors/formatters/template.py",
    "shared/user_errors/formatters/yaml_formatter.py": "logging/errors/formatters/yaml.py",
    "shared/user_errors/formatters/__init__.py": "logging/errors/formatters/__init__.py",
    "shared/user_errors/services/error_context_service.py": "logging/errors/services/context.py",
    "shared/user_errors/services/__init__.py": "logging/errors/services/__init__.py",
    "shared/__init__.py": None,  # Delete - will be empty
    # ============================================================
    # INPUT DOMAIN (input_loading + preprocessing)
    # ============================================================
    # Loaders
    "input_loading/base_base_loader.py": "input/loaders/base.py",
    "input_loading/json_loader.py": "input/loaders/json.py",
    "input_loading/tabular_loader.py": "input/loaders/tabular.py",
    "input_loading/xml_loader.py": "input/loaders/xml.py",
    "input_loading/text_loader.py": "input/loaders/text.py",
    "input_loading/template_yaml_loader.py": "input/loaders/yaml.py",
    "input_loading/udf_loader.py": "input/loaders/udf.py",
    "input_loading/file_reader.py": "input/loaders/file_reader.py",
    "input_loading/extractors_source_data_loader.py": "input/loaders/source_data.py",
    "input_loading/__init__.py": "input/loaders/__init__.py",
    # Preprocessing
    "preprocessing/staging/initial_stage_pipeline.py": "input/preprocessing/staging/initial_pipeline.py",
    "preprocessing/staging/__init__.py": "input/preprocessing/staging/__init__.py",
    "preprocessing/chunking/chunker.py": "input/preprocessing/chunking/chunker.py",
    "preprocessing/chunking/__init__.py": "input/preprocessing/chunking/__init__.py",
    "preprocessing/parsing/parser.py": "input/preprocessing/parsing/parser.py",
    "preprocessing/parsing/ast_nodes.py": "input/preprocessing/parsing/ast_nodes.py",
    "preprocessing/parsing/__init__.py": "input/preprocessing/parsing/__init__.py",
    "preprocessing/parsing/operator_registry/registry.py": "input/preprocessing/parsing/operator_registry/registry.py",
    "preprocessing/parsing/operator_registry/__init__.py": "input/preprocessing/parsing/operator_registry/__init__.py",
    "preprocessing/field_resolution/field_reference_resolver.py": "input/preprocessing/field_resolution/resolver.py",
    "preprocessing/field_resolution/reference_validator.py": "input/preprocessing/field_resolution/validator.py",
    "preprocessing/field_resolution/evaluation_context_provider.py": "input/preprocessing/field_resolution/context_provider.py",
    "preprocessing/field_resolution/__init__.py": "input/preprocessing/field_resolution/__init__.py",
    "preprocessing/transformation/data_transformer.py": "input/preprocessing/transformation/transformer.py",
    "preprocessing/transformation/__init__.py": "input/preprocessing/transformation/__init__.py",
    "preprocessing/filtering/guard_filter.py": "input/preprocessing/filtering/guard_filter.py",
    "preprocessing/filtering/guard_handler.py": "input/preprocessing/filtering/guard_handler.py",
    "preprocessing/filtering/filter_service.py": "input/preprocessing/filtering/service.py",
    "preprocessing/filtering/__init__.py": "input/preprocessing/filtering/__init__.py",
    "preprocessing/__init__.py": "input/preprocessing/__init__.py",
    # Preprocessing context -> input/context (non-LLM context)
    "preprocessing/context/historical_node_loader.py": "input/context/historical.py",
    "preprocessing/context/context_scope_normalizer.py": "input/context/normalizer.py",
    "preprocessing/context/__init__.py": "input/context/__init__.py",
    # Preprocessing utilities
    "preprocessing/utilities/source_path_manager.py": "input/preprocessing/source_path.py",
    "preprocessing/utilities/__init__.py": None,  # Merge into parent
    # Input __init__
    # Will create new: "input/__init__.py"
    # ============================================================
    # PROCESSING DOMAIN (core)
    # ============================================================
    "core/types.py": "processing/types.py",
    "core/record_processor.py": "processing/processor.py",
    "core/enrichment.py": "processing/enrichment.py",
    "core/result_collector.py": "processing/result_collector.py",
    "core/exhausted_record_builder.py": "processing/exhausted_builder.py",
    "core/result_adapters.py": "processing/result_adapters.py",
    "core/__init__.py": "processing/__init__.py",
    # Recovery
    "core/retry_service.py": "processing/recovery/retry.py",
    "core/reprompt_service.py": "processing/recovery/reprompt.py",
    "core/reprompt_validation.py": "processing/recovery/validation.py",
    "core/recovery_stats.py": "processing/recovery/stats.py",
    # Guards (from preprocessing filtering)
    "preprocessing/filtering/guard_filter.py": "processing/guards/filter.py",
    "preprocessing/filtering/guard_handler.py": "processing/guards/handler.py",
    # ============================================================
    # PROMPT DOMAIN
    # ============================================================
    "prompt_generation/prompt_preparation_service.py": "prompt/service.py",
    "prompt_generation/prompt_formatter.py": "prompt/formatter.py",
    "prompt_generation/prompt_handler.py": "prompt/handler.py",
    "prompt_generation/config_renderer.py": "prompt/renderer.py",
    "prompt_generation/sample_enricher.py": "prompt/enricher.py",
    "prompt_generation/data_generator.py": "prompt/data_generator.py",
    "prompt_generation/render_workflow.py": "prompt/render_workflow.py",
    "prompt_generation/__init__.py": "prompt/__init__.py",
    # LLM context building -> prompt/context
    "preprocessing/context/llm_context_builder.py": "prompt/context/builder.py",
    "preprocessing/context/static_data_loader.py": "prompt/context/static_loader.py",
    "preprocessing/context/context_scope_processor.py": "prompt/context/scope.py",
    # ============================================================
    # OUTPUT DOMAIN (file_io + response_processing)
    # ============================================================
    "file_io/file_handler.py": "output/file_handler.py",
    "file_io/file_writer.py": "output/writer.py",
    "file_io/unified_source_data_saver.py": "output/saver.py",
    "file_io/__init__.py": "output/__init__.py",
    # Response processing
    "response_processing/action_expander.py": "output/response/expander.py",
    "response_processing/schema_change.py": "output/response/schema.py",
    "response_processing/schema_loader.py": "output/response/loader.py",
    "response_processing/guard_parser.py": "output/response/guard_parser.py",
    "response_processing/consolidated_guard.py": "output/response/consolidated_guard.py",
    "response_processing/config_types.py": "output/response/config_types.py",
    "response_processing/config_schema.py": "output/response/config_schema.py",
    "response_processing/config_field_definitions.py": "output/response/config_fields.py",
    "response_processing/__init__.py": "output/response/__init__.py",
    # ============================================================
    # LLM DOMAIN
    # ============================================================
    "llm_invocation/providers/batch_client_base.py": "llm/providers/batch_base.py",
    "llm_invocation/providers/failure_injection.py": "llm/providers/failure_injection.py",
    "llm_invocation/providers/mixins.py": "llm/providers/mixins.py",
    "llm_invocation/providers/usage_tracker.py": "llm/providers/usage_tracker.py",
    "llm_invocation/providers/__init__.py": "llm/providers/__init__.py",
    # Provider subdirectories (keep structure)
    "llm_invocation/providers/anthropic/client.py": "llm/providers/anthropic/client.py",
    "llm_invocation/providers/anthropic/batch_client.py": "llm/providers/anthropic/batch_client.py",
    "llm_invocation/providers/anthropic/__init__.py": "llm/providers/anthropic/__init__.py",
    "llm_invocation/providers/openai/client.py": "llm/providers/openai/client.py",
    "llm_invocation/providers/openai/__init__.py": "llm/providers/openai/__init__.py",
    "llm_invocation/providers/gemini/client.py": "llm/providers/gemini/client.py",
    "llm_invocation/providers/gemini/__init__.py": "llm/providers/gemini/__init__.py",
    "llm_invocation/providers/groq/client.py": "llm/providers/groq/client.py",
    "llm_invocation/providers/groq/__init__.py": "llm/providers/groq/__init__.py",
    "llm_invocation/providers/mistral/client.py": "llm/providers/mistral/client.py",
    "llm_invocation/providers/mistral/__init__.py": "llm/providers/mistral/__init__.py",
    "llm_invocation/providers/cohere/client.py": "llm/providers/cohere/client.py",
    "llm_invocation/providers/cohere/__init__.py": "llm/providers/cohere/__init__.py",
    "llm_invocation/providers/ollama/client.py": "llm/providers/ollama/client.py",
    "llm_invocation/providers/ollama/batch_client.py": "llm/providers/ollama/batch_client.py",
    "llm_invocation/providers/ollama/failure_injection.py": "llm/providers/ollama/failure_injection.py",
    "llm_invocation/providers/ollama/__init__.py": "llm/providers/ollama/__init__.py",
    "llm_invocation/providers/agac/client.py": "llm/providers/agac/client.py",
    "llm_invocation/providers/agac/batch_client.py": "llm/providers/agac/batch_client.py",
    "llm_invocation/providers/agac/fake_data_generator.py": "llm/providers/agac/fake_data.py",
    "llm_invocation/providers/agac/__init__.py": "llm/providers/agac/__init__.py",
    # Batch
    "llm_invocation/batch/batch_service.py": "llm/batch/service.py",
    "llm_invocation/batch/__init__.py": "llm/batch/__init__.py",
    "llm_invocation/batch/processing/batch_result_processor.py": "llm/batch/processing/result_processor.py",
    "llm_invocation/batch/processing/batch_result_reconciler.py": "llm/batch/processing/reconciler.py",
    "llm_invocation/batch/processing/batch_task_preparator.py": "llm/batch/processing/preparator.py",
    "llm_invocation/batch/processing/batch_side_output_handler.py": "llm/batch/processing/side_output.py",
    "llm_invocation/batch/processing/__init__.py": "llm/batch/processing/__init__.py",
    "llm_invocation/batch/infrastructure/batch_job_manager.py": "llm/batch/infrastructure/job_manager.py",
    "llm_invocation/batch/infrastructure/batch_registry_manager.py": "llm/batch/infrastructure/registry.py",
    "llm_invocation/batch/infrastructure/batch_context_manager.py": "llm/batch/infrastructure/context.py",
    "llm_invocation/batch/infrastructure/__init__.py": "llm/batch/infrastructure/__init__.py",
    "llm_invocation/batch/services/batch_processing_service.py": "llm/batch/services/processing.py",
    "llm_invocation/batch/services/batch_retrieval_service.py": "llm/batch/services/retrieval.py",
    "llm_invocation/batch/services/batch_submission_service.py": "llm/batch/services/submission.py",
    "llm_invocation/batch/services/__init__.py": "llm/batch/services/__init__.py",
    # Realtime
    "llm_invocation/realtime/agent_handlers.py": "llm/realtime/handlers.py",
    "llm_invocation/realtime/config_handler.py": "llm/realtime/config.py",
    "llm_invocation/realtime/cleaner.py": "llm/realtime/cleaner.py",
    "llm_invocation/realtime/output_handler.py": "llm/realtime/output.py",
    "llm_invocation/realtime/agent_builder.py": "llm/realtime/builder.py",
    "llm_invocation/realtime/__init__.py": "llm/realtime/__init__.py",
    "llm_invocation/realtime/services/client_invocation_service.py": "llm/realtime/services/invocation.py",
    "llm_invocation/realtime/services/context_service.py": "llm/realtime/services/context.py",
    "llm_invocation/realtime/services/__init__.py": "llm/realtime/services/__init__.py",
    # Config
    "llm_invocation/config/model_config.py": "llm/config/model.py",
    "llm_invocation/config/__init__.py": "llm/config/__init__.py",
    "llm_invocation/__init__.py": "llm/__init__.py",
    # ============================================================
    # CONFIG DOMAIN (configuration + state_management)
    # ============================================================
    "configuration/config.py": "config/loader.py",
    "configuration/factory.py": "config/factory.py",
    "configuration/interfaces.py": "config/interfaces.py",
    "configuration/base.py": "config/base.py",
    "configuration/base_async_processor.py": "config/async_processor.py",
    "configuration/new_format_schema.py": "config/schema.py",
    "configuration/init.py": "config/init.py",
    "configuration/initializer.py": "config/initializer.py",
    "configuration/core_bootstrap.py": "config/bootstrap.py",
    "configuration/__init__.py": "config/__init__.py",
    # DI
    "configuration/di_configurator.py": "config/di/configurator.py",
    "orchestration/dependency_injection.py": "config/di/container.py",
    "orchestration/application_container.py": "config/di/application.py",
    # State management -> config
    "state_management/path_manager.py": "config/paths.py",
    "state_management/path_config.py": "config/path_config.py",
    "state_management/environment_config.py": "config/environment.py",
    "state_management/lineage_mixin.py": "processing/lineage_mixin.py",  # Goes to processing
    "state_management/__init__.py": None,  # Delete
    # ============================================================
    # VALIDATION DOMAIN
    # ============================================================
    "validation/project_validator.py": "validation/project.py",
    "validation/config_validator.py": "validation/config.py",
    "validation/schema_validator.py": "validation/schema.py",
    "validation/prompt_validator.py": "validation/prompt.py",
    "validation/prompt_ast_analyzer.py": "validation/prompt_ast.py",
    "validation/path_validator.py": "validation/path.py",
    "validation/directory_validator.py": "validation/directory.py",
    "validation/base_validator.py": "validation/base.py",
    "validation/batch_validator.py": "validation/batch.py",
    "validation/clean_validator.py": "validation/clean.py",
    "validation/docs_validator.py": "validation/docs.py",
    "validation/init_validator.py": "validation/init.py",
    "validation/render_validator.py": "validation/render.py",
    "validation/run_validator.py": "validation/run.py",
    "validation/startup_validator.py": "validation/startup.py",
    "validation/status_validator.py": "validation/status.py",
    "validation/validate_udfs.py": "validation/udfs.py",
    "validation/__init__.py": "validation/__init__.py",
    # Validation subdirs (keep structure)
    "validation/preflight/preflight_runner.py": "validation/preflight/runner.py",
    "validation/preflight/__init__.py": "validation/preflight/__init__.py",
    "validation/static_analyzer/workflow_static_analyzer.py": "validation/static_analysis/analyzer.py",
    "validation/static_analyzer/__init__.py": "validation/static_analysis/__init__.py",
    "validation/agent_validators/": "validation/agent/",  # Directory copy
    "validation/orchestration/": "validation/orchestration/",  # Keep
    "validation/utils/": "validation/utils/",  # Keep
    # ============================================================
    # WORKFLOW DOMAIN (orchestration)
    # ============================================================
    "orchestration/agent_workflow.py": "workflow/coordinator.py",
    "orchestration/agent_executor.py": "workflow/executor.py",
    "orchestration/agent_runner.py": "workflow/runner.py",
    "orchestration/agent_strategies.py": "workflow/strategies.py",
    "orchestration/processing_pipeline.py": "workflow/pipeline.py",
    "orchestration/workflow_models.py": "workflow/models.py",
    "orchestration/node_mapper.py": "workflow/node_mapper.py",
    "orchestration/workspace_index.py": "workflow/workspace_index.py",
    "orchestration/__init__.py": "workflow/__init__.py",
    # Managers
    "orchestration/batch_manager.py": "workflow/managers/batch.py",
    "orchestration/state_manager.py": "workflow/managers/state.py",
    "orchestration/output_manager.py": "workflow/managers/output.py",
    "orchestration/skip_evaluator.py": "workflow/managers/skip.py",
    "orchestration/loop_correlator.py": "workflow/managers/loop.py",
    "orchestration/manifest_manager.py": "workflow/managers/manifest.py",
    "orchestration/artifact_linker.py": "workflow/managers/artifacts.py",
    # Parallel
    "orchestration/action_level_executor.py": "workflow/parallel/action_executor.py",
    "orchestration/workflow_dependency_orchestrator.py": "workflow/parallel/dependency.py",
    # ============================================================
    # CLI DOMAIN
    # ============================================================
    "cli/main.py": "cli/main.py",
    "cli/run.py": "cli/commands/run.py",
    "cli/init.py": "cli/commands/init.py",
    "cli/validate.py": "cli/commands/validate.py",
    "cli/inspect.py": "cli/commands/inspect.py",
    "cli/compile.py": "cli/commands/compile.py",
    "cli/status.py": "cli/commands/status.py",
    "cli/docs.py": "cli/commands/docs.py",
    "cli/clean.py": "cli/commands/clean.py",
    "cli/render.py": "cli/commands/render.py",
    "cli/batch.py": "cli/commands/batch.py",
    "cli/project_paths_factory.py": "cli/paths_factory.py",
    "cli/__init__.py": "cli/__init__.py",
    # CLI utils
    "cli/utils/service_logger.py": "cli/utils/service_logger.py",
    "cli/utils/error_handler.py": "cli/utils/error_handler.py",
    "cli/utils/error_wrap.py": "cli/utils/error_wrap.py",
    "cli/utils/__init__.py": "cli/utils/__init__.py",
    # CLI renderers (keep structure)
    "cli/renderers/": "cli/renderers/",
    # ============================================================
    # TOOLING (lsp + docs)
    # ============================================================
    "lsp/server.py": "tooling/lsp/server.py",
    "lsp/indexer.py": "tooling/lsp/indexer.py",
    "lsp/resolver.py": "tooling/lsp/resolver.py",
    "lsp/models.py": "tooling/lsp/models.py",
    "lsp/__init__.py": "tooling/lsp/__init__.py",
    "docs/generator.py": "tooling/docs/generator.py",
    "docs/parser.py": "tooling/docs/parser.py",
    "docs/scanner.py": "tooling/docs/scanner.py",
    "docs/server.py": "tooling/docs/server.py",
    "docs/run_tracker.py": "tooling/docs/run_tracker.py",
    "docs/__init__.py": "tooling/docs/__init__.py",
    "docs/docs_site/": "tooling/docs/site/",  # Directory copy
    "docs/docs-site-builder/": "tooling/docs/site-builder/",  # Directory copy
    # ============================================================
    # SERVICES (merge into appropriate domains)
    # ============================================================
    "services/workflow_schema_service.py": "workflow/schema_service.py",
    "services/__init__.py": None,  # Delete
    # ============================================================
    # SKILLS (keep as-is under tooling or root)
    # ============================================================
    "skills/": "skills/",  # Keep structure
}

# Import rewrites: old_import -> new_import
IMPORT_REWRITES = {
    # Core -> Processing
    "agent_actions.core.types": "agent_actions.processing.types",
    "agent_actions.core.record_processor": "agent_actions.processing.processor",
    "agent_actions.core.enrichment": "agent_actions.processing.enrichment",
    "agent_actions.core.result_collector": "agent_actions.processing.result_collector",
    "agent_actions.core.retry_service": "agent_actions.processing.recovery.retry",
    "agent_actions.core.reprompt_service": "agent_actions.processing.recovery.reprompt",
    "agent_actions.core.reprompt_validation": "agent_actions.processing.recovery.validation",
    "agent_actions.core.recovery_stats": "agent_actions.processing.recovery.stats",
    "agent_actions.core.exhausted_record_builder": "agent_actions.processing.exhausted_builder",
    "agent_actions.core": "agent_actions.processing",
    # Orchestration -> Workflow
    "agent_actions.orchestration.agent_workflow": "agent_actions.workflow.coordinator",
    "agent_actions.orchestration.agent_executor": "agent_actions.workflow.executor",
    "agent_actions.orchestration.agent_runner": "agent_actions.workflow.runner",
    "agent_actions.orchestration.agent_strategies": "agent_actions.workflow.strategies",
    "agent_actions.orchestration.processing_pipeline": "agent_actions.workflow.pipeline",
    "agent_actions.orchestration.workflow_models": "agent_actions.workflow.models",
    "agent_actions.orchestration.batch_manager": "agent_actions.workflow.managers.batch",
    "agent_actions.orchestration.state_manager": "agent_actions.workflow.managers.state",
    "agent_actions.orchestration.output_manager": "agent_actions.workflow.managers.output",
    "agent_actions.orchestration.skip_evaluator": "agent_actions.workflow.managers.skip",
    "agent_actions.orchestration.loop_correlator": "agent_actions.workflow.managers.loop",
    "agent_actions.orchestration.manifest_manager": "agent_actions.workflow.managers.manifest",
    "agent_actions.orchestration.artifact_linker": "agent_actions.workflow.managers.artifacts",
    "agent_actions.orchestration.action_level_executor": "agent_actions.workflow.parallel.action_executor",
    "agent_actions.orchestration.workflow_dependency_orchestrator": "agent_actions.workflow.parallel.dependency",
    "agent_actions.orchestration.dependency_injection": "agent_actions.config.di.container",
    "agent_actions.orchestration.application_container": "agent_actions.config.di.application",
    "agent_actions.orchestration": "agent_actions.workflow",
    # Utilities -> Utils
    "agent_actions.utilities.constants": "agent_actions.utils.constants",
    "agent_actions.utilities.dict_utils": "agent_actions.utils.dict",
    "agent_actions.utilities.module_loader": "agent_actions.utils.module_loader",
    "agent_actions.utilities.safe_format": "agent_actions.utils.safe_format",
    "agent_actions.utilities.id_generation": "agent_actions.utils.id_generation",
    "agent_actions.utilities.field_management": "agent_actions.utils.field_management",
    "agent_actions.utilities.lineage": "agent_actions.utils.lineage",
    "agent_actions.utilities.metadata": "agent_actions.utils.metadata",
    "agent_actions.utilities.correlation": "agent_actions.utils.correlation",
    "agent_actions.utilities.transformation": "agent_actions.utils.transformation",
    "agent_actions.utilities.udf_management": "agent_actions.utils.udf_management",
    "agent_actions.utilities.processor.processor_helpers": "agent_actions.processing.helpers",
    "agent_actions.utilities.processor": "agent_actions.processing",
    "agent_actions.utilities": "agent_actions.utils",
    # Configuration -> Config
    "agent_actions.configuration.factory": "agent_actions.config.factory",
    "agent_actions.configuration.interfaces": "agent_actions.config.interfaces",
    "agent_actions.configuration.config": "agent_actions.config.loader",
    "agent_actions.configuration.di_configurator": "agent_actions.config.di.configurator",
    "agent_actions.configuration.core_bootstrap": "agent_actions.config.bootstrap",
    "agent_actions.configuration.new_format_schema": "agent_actions.config.schema",
    "agent_actions.configuration": "agent_actions.config",
    # State management -> Config
    "agent_actions.state_management.path_manager": "agent_actions.config.paths",
    "agent_actions.state_management.environment_config": "agent_actions.config.environment",
    "agent_actions.state_management.lineage_mixin": "agent_actions.processing.lineage_mixin",
    "agent_actions.state_management": "agent_actions.config",
    # Input loading -> Input
    "agent_actions.input_loading": "agent_actions.input.loaders",
    # Preprocessing -> Input/preprocessing or Prompt/context
    "agent_actions.preprocessing.staging": "agent_actions.input.preprocessing.staging",
    "agent_actions.preprocessing.chunking": "agent_actions.input.preprocessing.chunking",
    "agent_actions.preprocessing.parsing": "agent_actions.input.preprocessing.parsing",
    "agent_actions.preprocessing.field_resolution": "agent_actions.input.preprocessing.field_resolution",
    "agent_actions.preprocessing.transformation": "agent_actions.input.preprocessing.transformation",
    "agent_actions.preprocessing.filtering": "agent_actions.input.preprocessing.filtering",
    "agent_actions.preprocessing.context.llm_context_builder": "agent_actions.prompt.context.builder",
    "agent_actions.preprocessing.context.static_data_loader": "agent_actions.prompt.context.static_loader",
    "agent_actions.preprocessing.context.context_scope_processor": "agent_actions.prompt.context.scope",
    "agent_actions.preprocessing.context": "agent_actions.input.context",
    "agent_actions.preprocessing": "agent_actions.input.preprocessing",
    # Prompt generation -> Prompt
    "agent_actions.prompt_generation.prompt_preparation_service": "agent_actions.prompt.service",
    "agent_actions.prompt_generation.prompt_formatter": "agent_actions.prompt.formatter",
    "agent_actions.prompt_generation.prompt_handler": "agent_actions.prompt.handler",
    "agent_actions.prompt_generation.config_renderer": "agent_actions.prompt.renderer",
    "agent_actions.prompt_generation.sample_enricher": "agent_actions.prompt.enricher",
    "agent_actions.prompt_generation": "agent_actions.prompt",
    # File IO -> Output
    "agent_actions.file_io": "agent_actions.output",
    # Response processing -> Output/response
    "agent_actions.response_processing": "agent_actions.output.response",
    # LLM invocation -> LLM
    "agent_actions.llm_invocation.providers": "agent_actions.llm.providers",
    "agent_actions.llm_invocation.batch": "agent_actions.llm.batch",
    "agent_actions.llm_invocation.realtime": "agent_actions.llm.realtime",
    "agent_actions.llm_invocation": "agent_actions.llm",
    # Shared -> Logging/errors
    "agent_actions.shared.user_errors": "agent_actions.logging.errors",
    "agent_actions.shared": "agent_actions.logging.errors",
    # LSP/Docs -> Tooling
    "agent_actions.lsp": "agent_actions.tooling.lsp",
    "agent_actions.docs": "agent_actions.tooling.docs",
    # Services -> Workflow
    "agent_actions.services": "agent_actions.workflow",
    # Validation (mostly same, just file renames)
    "agent_actions.validation.project_validator": "agent_actions.validation.project",
    "agent_actions.validation.config_validator": "agent_actions.validation.config",
    "agent_actions.validation.schema_validator": "agent_actions.validation.schema",
    "agent_actions.validation.static_analyzer": "agent_actions.validation.static_analysis",
}
