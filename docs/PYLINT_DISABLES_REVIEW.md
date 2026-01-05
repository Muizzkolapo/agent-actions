# Pylint Inline Disables Review

This document catalogs all inline `# pylint: disable=` comments in the codebase for review.

---

## Summary by Category

| Category | Count |
|----------|-------|
| too-many-arguments / too-many-positional-arguments | 45 |
| import-outside-toplevel | 52 |
| too-few-public-methods | 28 |
| broad-exception-caught | 24 |
| too-many-locals | 12 |
| too-many-branches | 10 |
| duplicate-code | 11 |
| unnecessary-pass | 6 |
| protected-access | 5 |
| unused-argument | 5 |
| no-member | 6 |
| too-many-instance-attributes | 9 |
| too-many-return-statements | 4 |
| too-many-statements | 3 |
| too-many-nested-blocks | 2 |
| global-statement | 4 |
| cyclic-import | 2 |
| line-too-long | 4 |
| Other | misc |

---

## Detailed Listing

### 1. `too-many-arguments` / `too-many-positional-arguments`

These indicate functions with many parameters - potential candidates for refactoring into config objects or builder patterns.

| File | Line | Context |
|------|------|---------|
| `agent_actions/validation/preflight/path_validator.py` | 135 | function definition |
| `agent_actions/services/workflow_schema_service.py` | 52 | `__init__` |
| `agent_actions/validation/static_analyzer/errors.py` | 84, 107 | `__init__` |
| `agent_actions/validation/preflight/preflight_validator.py` | 99 | function |
| `agent_actions/cli/run.py` | 352 | function |
| `agent_actions/cli/inspect.py` | 37, 415, 467 | class/function |
| `agent_actions/errors/preflight.py` | 31, 115, 166, 219, 267, 321 | error classes |
| `agent_actions/errors/external_services.py` | 2 | module-level |
| `agent_actions/errors/configuration.py` | 2 | module-level |
| `agent_actions/orchestration/agent_workflow.py` | 124 | `_create_child_workflow` |
| `agent_actions/orchestration/workflow_dependency_orchestrator.py` | 326 | `resolve_upstream_and_initialize` |
| `agent_actions/validation/static_analyzer/workflow_static_analyzer.py` | 49 | `__init__` |
| `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | 42, 66, 279, 373 | service methods |
| `agent_actions/llm_invocation/batch/services/batch_retrieval_service.py` | 137 | service method |
| `agent_actions/llm_invocation/batch/services/batch_retry_service.py` | 38, 201 | service methods |
| `agent_actions/llm_invocation/batch/services/batch_submission_service.py` | 38 | service method |
| `agent_actions/llm_invocation/batch/batch_service.py` | 54 | `__init__` |
| `agent_actions/llm_invocation/batch/retry/batch_retry_orchestrator.py` | 123 | method |
| `agent_actions/llm_invocation/batch/processing/batch_result_processor.py` | 68, 439 | class/method |
| `agent_actions/llm_invocation/batch/processing/batch_task_preparator.py` | 73, 180, 249 | methods |
| `agent_actions/prompt_generation/data_generator.py` | 167 | method |
| `agent_actions/prompt_generation/prompt_utils.py` | 16-17 | function |
| `agent_actions/prompt_generation/target_content_processor.py` | 35 | method |
| `agent_actions/prompt_generation/prompt_preparation_service.py` | 209 | method |
| `agent_actions/preprocessing/processing/data_processor.py` | 46 | `process_item` |
| `agent_actions/utilities/field_management/field_manager.py` | 49 | `create_processed_item` |
| `agent_actions/utilities/transformation/passthrough_transformer.py` | 54 | method |
| `agent_actions/utilities/processor/processor_helpers.py` | 113, 256 | functions |
| `agent_actions/utilities/transformation/strategies/base.py` | 37 | `transform` |
| `agent_actions/utilities/transformation/strategies/context_scope_strategies.py` | 38, 117, 176, 209 | `transform` methods |
| `agent_actions/utilities/transformation/strategies/precomputed_strategies.py` | 37, 75 | `transform` methods |
| `agent_actions/utilities/passthrough_item_builder.py` | 83 | `build_item` |
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 225 | method |
| `agent_actions/utilities/processor/error_handling.py` | 9 | module-level |

---

### 2. `import-outside-toplevel`

Deferred imports for performance or circular import avoidance. Review for necessity.

| File | Line | Import |
|------|------|--------|
| `agent_actions/cli/schema.py` | 104 | deferred import |
| `agent_actions/validation/static_analyzer/errors.py` | 207 | deferred import |
| `agent_actions/cli/run.py` | 119, 180 | `sys`, other |
| `agent_actions/cli/cli_decorators.py` | 79 | decorator helper |
| `agent_actions/cli/inspect.py` | 133, 545 | deferred import |
| `agent_actions/validation/static_analyzer/workflow_static_analyzer.py` | 382 | `yaml` |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | 180 | reference_extractor |
| `agent_actions/errors/base.py` | 6 | module-level |
| `agent_actions/orchestration/agent_workflow.py` | 171, 678 | deferred imports |
| `agent_actions/orchestration/application_container.py` | 186, 269 | deferred imports |
| `agent_actions/orchestration/agent_strategies.py` | 77 | target_generator |
| `agent_actions/response_processing/guard_parser.py` | 243 | consolidated_guard |
| `agent_actions/prompt_generation/prompt_formatter.py` | 117, 150 | deferred imports |
| `agent_actions/prompt_generation/prompt_preparation_service.py` | 306, 498 | deferred imports |
| `agent_actions/configuration/base.py` | 29 | agent_actions version |
| `agent_actions/configuration/base_async_processor.py` | 96, 119 | `aiofiles` |
| `agent_actions/configuration/new_format_schema.py` | 138 | deferred import |
| `agent_actions/configuration/di_configurator.py` | 42, 57, 77, 98, 123 | multiple DI imports |
| `agent_actions/configuration/factory.py` | 1 | module-level |
| `agent_actions/configuration/initializer.py` | 17 | module-level |
| `agent_actions/configuration/core_bootstrap.py` | 49, 64, 88, 117 | bootstrap imports |
| `agent_actions/preprocessing/staging/staging_loader.py` | 637 | deferred import |
| `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | 397 | deferred import |
| `agent_actions/llm_invocation/batch/services/batch_retrieval_service.py` | 161 | deferred import |
| `agent_actions/llm_invocation/batch/services/batch_retry_service.py` | 122, 225 | deferred imports |
| `agent_actions/llm_invocation/batch/batch_service.py` | 77, 132, 149, 164, 181 | provider imports |
| `agent_actions/llm_invocation/batch/retry/batch_retry_orchestrator.py` | 508 | deferred import |
| `agent_actions/llm_invocation/batch/processing/batch_result_processor.py` | 395, 411 | deferred imports |
| `agent_actions/llm_invocation/batch/infrastructure/batch_source_handler.py` | 32 | deferred import |
| `agent_actions/llm_invocation/batch/processing/batch_task_preparator.py` | 124, 262, 313, 337, 359, 388 | multiple |
| `agent_actions/llm_invocation/providers/batch_client_factory.py` | 72, 89, 109, 124, 139, 163 | provider imports |
| `agent_actions/llm_invocation/providers/mistral/batch_client.py` | 48, 54, 119, 165 | mistral/errors |
| `agent_actions/llm_invocation/providers/groq/batch_client.py` | 49, 55, 124, 165 | groq/errors |
| `agent_actions/llm_invocation/providers/anthropic/client.py` | 97, 120 | modular pattern |
| `agent_actions/llm_invocation/providers/anthropic/batch_client.py` | 51, 61, 71 | anthropic/modular |
| `agent_actions/llm_invocation/providers/gemini/batch_client.py` | 39, 178, 213, 224, 237 | modular pattern |
| `agent_actions/llm_invocation/providers/client_base.py` | 77 | modular pattern |
| `agent_actions/llm_invocation/providers/tools/client.py` | 32 | modular pattern |
| `agent_actions/llm_invocation/providers/batch_client_base.py` | 185, 207, 269, 512, 561 | logging/modular |
| `agent_actions/utilities/path_utils.py` | 234, 308, 332 | error imports |
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 6 | module-level |
| `agent_actions/utilities/processor/error_handling.py` | 8 | module-level |
| `agent_actions/utilities/udf_management/tooling.py` | 2 | module-level |
| `agent_actions/input_loading/base_base_loader.py` | 3 | module-level |

---

### 3. `too-few-public-methods`

Classes that might be better as dataclasses, functions, or protocols.

| File | Line | Class |
|------|------|-------|
| `agent_actions/cli/schema.py` | 25 | `SchemaCommand` |
| `agent_actions/cli/status.py` | 20 | `StatusCommand` |
| `agent_actions/cli/main.py` | 37 | `CLI` |
| `agent_actions/cli/run.py` | 29 | `RunCommand` |
| `agent_actions/cli/init.py` | 25 | `InitCommand` |
| `agent_actions/cli/compile.py` | 21 | `RenderCommand` |
| `agent_actions/cli/list_udfs.py` | 21 | `ListUDFsCommand` |
| `agent_actions/cli/inspect.py` | 34, 464 | `FieldFlowCommand`, `ConflictsCommand` |
| `agent_actions/validation/static_analyzer/errors.py` | 81, 104 | `StaticTypeError`, `StaticTypeWarning` |
| `agent_actions/docs/generator.py` | 16, 226 | `CatalogGenerator`, `RunsGenerator` |
| `agent_actions/shared/user_errors/services/error_context_service.py` | 6 | `ErrorContextService` |
| `agent_actions/shared/user_errors/error_translator.py` | 24 | `ErrorTranslator` |
| `agent_actions/file_io/unified_source_data_saver.py` | 101 | `UnifiedSourceDataSaver` |
| `agent_actions/response_processing/base.py` | 32 | class |
| `agent_actions/response_processing/guard_parser.py` | 15 | `GuardExpression` |
| `agent_actions/prompt_generation/sample_enricher.py` | 12 | class |
| `agent_actions/prompt_generation/config_renderer.py` | 32, 53, 72, 89, 191, 233, 261, 471 | multiple renderer classes |
| `agent_actions/prompt_generation/directory_handler.py` | 11 | class |
| `agent_actions/configuration/base.py` | 18 | `ArtifactMetadata` |
| `agent_actions/configuration/base_async_processor.py` | 179 | `ProcessingContext` |
| `agent_actions/configuration/interfaces.py` | 23, 35, 39, 43 | interface classes |
| `agent_actions/llm_invocation/batch/core/batch_context_metadata.py` | 16 | `BatchContextMetadata` |
| `agent_actions/llm_invocation/batch/core/batch_constants.py` | 89 | `ContextMetaKeys` |
| `agent_actions/llm_invocation/batch/services/batch_retrieval_service.py` | 29 | `BatchRetrievalService` |
| `agent_actions/llm_invocation/batch/services/batch_retry_service.py` | 32 | `BatchRetryService` |
| `agent_actions/llm_invocation/batch/services/batch_submission_service.py` | 32 | `BatchSubmissionService` |
| `agent_actions/llm_invocation/batch/processing/batch_task_preparator.py` | 30 | `BatchTaskPreparator` |
| `agent_actions/llm_invocation/batch/infrastructure/batch_source_handler.py` | 7 | `BatchSourceHandler` |
| `agent_actions/utilities/transformation/passthrough_transformer.py` | 20 | `PassthroughTransformer` |
| `agent_actions/utilities/passthrough_item_builder.py` | 72 | `PassthroughItemBuilder` |
| `agent_actions/input_loading/template_yaml_loader.py` | 2 | module-level |

---

### 4. `broad-exception-caught`

Generic exception handlers - review for more specific exception handling.

| File | Line | Context |
|------|------|---------|
| `agent_actions/cli/main.py` | 204 | main CLI error handling |
| `agent_actions/cli/run.py` | 288, 300 | run command error handling |
| `agent_actions/reprompting/engine.py` | 252 | reprompt error handling |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | 292, 326 | schema extraction |
| `agent_actions/docs/parser.py` | 101 | doc parsing |
| `agent_actions/errors/base.py` | 6 | module-level |
| `agent_actions/shared/user_errors/services/error_context_service.py` | 64 | error context |
| `agent_actions/shared/user_errors/__init__.py` | 51 | format error |
| `agent_actions/file_io/file_writer.py` | 59, 83, 104 | file write operations |
| `agent_actions/response_processing/schema_loader.py` | 52 | schema loading |
| `agent_actions/prompt_generation/config_renderer.py` | 255, 456, 495 | config rendering |
| `agent_actions/prompt_generation/target_content_processor.py` | 520 | content processing |
| `agent_actions/configuration/base.py` | 32 | version loading |
| `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | 197, 236 | batch processing |
| `agent_actions/llm_invocation/batch/infrastructure/batch_job_manager.py` | 112, 179 | job management |
| `agent_actions/llm_invocation/batch/infrastructure/batch_registry_manager.py` | 240, 306 | registry management |
| `agent_actions/llm_invocation/batch/processing/batch_result_processor.py` | 242 | result processing |
| `agent_actions/llm_invocation/batch/processing/batch_task_preparator.py` | 165 | task preparation |
| `agent_actions/utilities/processor/processor_helpers.py` | 223, 246 | intentional fallback |
| `agent_actions/utilities/safe_format.py` | 8 | intentional - safety |

---

### 5. `too-many-locals`

Functions with many local variables - potential extraction candidates.

| File | Line | Function |
|------|------|----------|
| `agent_actions/validation/preflight/context_structure_validator.py` | 31 | validator |
| `agent_actions/cli/run.py` | 102 | run command |
| `agent_actions/docs/generator.py` | 95, 245 | generator methods |
| `agent_actions/docs/scanner.py` | 283 | scanner method |
| `agent_actions/llm_invocation/batch/services/batch_processing_service.py` | 66 | service method |
| `agent_actions/llm_invocation/batch/services/batch_retry_service.py` | 63 | retry method |
| `agent_actions/llm_invocation/batch/retry/batch_retry_orchestrator.py` | 123 | orchestrator |
| `agent_actions/llm_invocation/batch/batch_service.py` | 54 | `__init__` |
| `agent_actions/prompt_generation/config_renderer.py` | 95, 312 | renderer methods |
| `agent_actions/prompt_generation/prompt_utils.py` | 17 | utility function |
| `agent_actions/prompt_generation/target_content_processor.py` | 393, 574 | processor methods |
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 225 | processor |
| `agent_actions/skills/agent-actions-workflow/scripts/analyze_field_flow.py` | 90 | analysis |
| `agent_actions/input_loading/template_yaml_loader.py` | 2 | module-level |

---

### 6. `too-many-branches`

Complex conditional logic - candidates for strategy pattern or decomposition.

| File | Line | Function |
|------|------|----------|
| `agent_actions/validation/preflight/path_validator.py` | 33 | path validation |
| `agent_actions/reprompting/interceptor.py` | 78 | `intercept` |
| `agent_actions/reprompting/json_repair.py` | 145 | `_extract_json_block` |
| `agent_actions/cli/run.py` | 102 | run command |
| `agent_actions/cli/renderers/schema_renderer.py` | 107 | `render_action_detail` |
| `agent_actions/cli/skills.py` | 52 | `install` |
| `agent_actions/docs/scanner.py` | 283 | scanner |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | 262, 437 | schema extraction |
| `agent_actions/response_processing/schema_change.py` | 237, 280 | schema processing |
| `agent_actions/llm_invocation/batch/infrastructure/batch_job_manager.py` | 136 | job manager |
| `agent_actions/prompt_generation/config_renderer.py` | 312 | config rendering |
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 226 | processor |

---

### 7. `duplicate-code`

Similar code blocks across files - DRY principle violations.

| File | Line | Context |
|------|------|---------|
| `agent_actions/validation/preflight/dependency_validator.py` | 1 | module-level |
| `agent_actions/orchestration/agent_workflow.py` | 1 | module-level |
| `agent_actions/orchestration/agent_runner.py` | 1 | module-level |
| `agent_actions/orchestration/output_manager.py` | 1 | module-level |
| `agent_actions/orchestration/workflow_dependency_orchestrator.py` | 1 | module-level |
| `agent_actions/configuration/base.py` | 1 | module-level |
| `agent_actions/configuration/di_configurator.py` | 1 | module-level |
| `agent_actions/configuration/initializer.py` | 1 | module-level |
| `agent_actions/configuration/factory.py` | 1 | module-level |
| `agent_actions/configuration/core_bootstrap.py` | 1 | module-level |
| `agent_actions/llm_invocation/batch/services/batch_retrieval_service.py` | 1 | module-level |
| `agent_actions/llm_invocation/batch/retry/batch_retry_orchestrator.py` | 8 | module-level |
| `agent_actions/input_loading/text_loader.py` | 3 | module-level |
| `agent_actions/input_loading/json_loader.py` | 3 | module-level |
| `agent_actions/input_loading/tabular_loader.py` | 3 | module-level |
| `agent_actions/input_loading/xml_loader.py` | 3 | module-level |
| `agent_actions/skills/agent-actions-workflow/scripts/generate_typeddict.py` | 2 | module-level |

---

### 8. `unnecessary-pass`

Empty class bodies - consider if truly needed or can be removed.

| File | Line | Context |
|------|------|---------|
| `agent_actions/errors/validation.py` | 2 | error module |
| `agent_actions/errors/preflight.py` | 6 | error module |
| `agent_actions/errors/processing.py` | 2 | error module |
| `agent_actions/errors/resources.py` | 2 | error module |
| `agent_actions/errors/common.py` | 5 | error module |
| `agent_actions/errors/operations.py` | 2 | error module |
| `agent_actions/errors/filesystem.py` | 2 | error module |
| `agent_actions/errors/external_services.py` | 2 | error module |
| `agent_actions/errors/configuration.py` | 2 | error module |
| `agent_actions/input_loading/base_base_loader.py` | 3 | loader module |

---

### 9. `protected-access`

Accessing private members - review for proper encapsulation.

| File | Line | Context |
|------|------|---------|
| `agent_actions/validation/static_analyzer/workflow_static_analyzer.py` | 121 | analyzer |
| `agent_actions/cli/cli_decorators.py` | 73 | decorator |
| `agent_actions/orchestration/agent_workflow.py` | 703 | `_already_displayed` |
| `agent_actions/llm_invocation/batch/batch_cli.py` | 38, 69 | CLI access |
| `agent_actions/llm_invocation/batch/processing/batch_result_processor.py` | 172, 496 | `_extract_node_index`, `_build_item` |

---

### 10. `too-many-instance-attributes`

Classes with many attributes - candidates for composition.

| File | Line | Class |
|------|------|-------|
| `agent_actions/validation/preflight/error_formatter.py` | 13 | `ValidationIssue` |
| `agent_actions/reprompting/engine.py` | 18 | `RepromptResult` |
| `agent_actions/reprompting/config.py` | 46 | `RepromptConfig` |
| `agent_actions/docs/run_tracker.py` | 19, 35 | `RunConfig`, `ActionCompleteConfig` |
| `agent_actions/cli/inspect.py` | 34 | `FieldFlowCommand` |
| `agent_actions/cli/project_paths_factory.py` | 26 | `ProjectPaths` |
| `agent_actions/orchestration/agent_workflow.py` | 57 | `AgentWorkflow` |
| `agent_actions/models/action_schema.py` | 98 | `ActionSchema` |
| `agent_actions/llm_invocation/batch/batch_service.py` | 47 | `BatchService` |
| `agent_actions/llm_invocation/batch/core/batch_models.py` | 14 | `BatchJobEntry` |
| `agent_actions/llm_invocation/batch/processing/batch_result_processor.py` | 32 | `BatchProcessingContext` |
| `agent_actions/prompt_generation/prompt_preparation_service.py` | 117 | `PromptPreparationRequest` |
| `agent_actions/utilities/field_resolution/evaluation_context_provider.py` | 37 | `ContextBuildConfig` |

---

### 11. Other Notable Disables

#### `no-member` (dynamic attributes)
| File | Line |
|------|------|
| `agent_actions/response_processing/processor_config.py` | 131, 169 |
| `agent_actions/response_processing/pipeline_config.py` | 168, 173, 244, 248, 252, 256 |
| `agent_actions/llm_invocation/config/vendor_config.py` | 151, 155, 163 |
| `agent_actions/utilities/transformation/strategies/context_scope_strategies.py` | 88 |

#### `global-statement`
| File | Line | Variable |
|------|------|----------|
| `agent_actions/preprocessing/parsing/parser.py` | 638 | `_GLOBAL_PARSER` |
| `agent_actions/preprocessing/filtering/guard_filter.py` | 389 | `_GLOBAL_GUARD_FILTER` |
| `agent_actions/preprocessing/filtering/filter_service.py` | 317 | `_GLOBAL_FILTER_SERVICE` |
| `agent_actions/preprocessing/filtering/guard_handler.py` | 537 | `_GLOBAL_GUARD_HANDLER` |
| `agent_actions/utilities/path_utils.py` | 26 | `_global_path_manager` |

#### `unused-argument`
| File | Line | Context |
|------|------|---------|
| `agent_actions/cli/main.py` | 60 | CLI group |
| `agent_actions/response_processing/schema_loader.py` | 88 | `directory` param |
| `agent_actions/configuration/base_async_processor.py` | 165 | `concurrency_limit` |
| `agent_actions/configuration/di_configurator.py` | 39, 54, 74 | `config` params |
| `agent_actions/configuration/factory.py` | 49, 50 | path params |
| `agent_actions/configuration/core_bootstrap.py` | 46, 60, 74 | `config` params |
| `agent_actions/utilities/context_scope/static_data_loader.py` | 2 | module-level |
| `agent_actions/utilities/processor/error_handling.py` | 9 | module-level |

#### `redefined-builtin`
| File | Line | Builtin |
|------|------|---------|
| `agent_actions/docs/server.py` | 52 | `format` |

#### `eval-used`
| File | Line | Context |
|------|------|---------|
| `agent_actions/preprocessing/parsing/parser.py` | 534 | dynamic evaluation |

#### `catching-non-exception`
| File | Line | Context |
|------|------|---------|
| `agent_actions/utilities/retry.py` | 87, 127 | dynamic exception types |

#### `cyclic-import`
| File | Line | Context |
|------|------|---------|
| `agent_actions/response_processing/schema_loader.py` | 1 | module-level |
| `agent_actions/response_processing/guard_parser.py` | 243 | deferred import |

#### `too-many-return-statements`
| File | Line | Function |
|------|------|----------|
| `agent_actions/cli/main.py` | 151 | CLI function |
| `agent_actions/reprompting/json_repair.py` | 58 | `attempt_repair` |
| `agent_actions/llm_invocation/batch/infrastructure/batch_job_manager.py` | 75, 136 | job manager |
| `agent_actions/skills/agent-actions-workflow/scripts/generate_typeddict.py` | 20 | `infer_python_type` |
| `agent_actions/skills/agent-actions-workflow/scripts/analyze_field_flow.py` | 26 | `get_field_type` |

#### `too-many-statements`
| File | Line | Function |
|------|------|----------|
| `agent_actions/cli/run.py` | 102 | run command |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | 262 | schema extraction |
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 226 | processor |

#### `too-many-nested-blocks`
| File | Line | Function |
|------|------|----------|
| `agent_actions/docs/scanner.py` | 162, 229 | scanner methods |

#### `line-too-long`
| File | Line |
|------|------|
| `agent_actions/utilities/context_scope/context_scope_processor.py` | 6 |
| `agent_actions/utilities/processor/error_handling.py` | 8 |
| `agent_actions/utilities/udf_management/tooling.py` | 2 |
| `agent_actions/utilities/field_resolution/reference_parser.py` | 20 |

#### External library imports with `import-error`
| File | Line | Library |
|------|------|---------|
| `agent_actions/llm_invocation/providers/mistral/client.py` | 10 | `mistralai` |
| `agent_actions/llm_invocation/providers/ollama/client.py` | 15 | `ollama` |
| `agent_actions/llm_invocation/providers/groq/client.py` | 11 | `groq` |
| `agent_actions/llm_invocation/providers/cohere/client.py` | 10 | `cohere` |
| `agent_actions/llm_invocation/providers/anthropic/client.py` | 13 | `anthropic` |
| `agent_actions/llm_invocation/providers/gemini/client.py` | 10 | `google.generativeai` |
| `agent_actions/configuration/base_async_processor.py` | 96, 119 | `aiofiles` |

---

## Recommendations

### High Priority (Potential Code Smell)

1. **`too-many-arguments`**: Consider using dataclasses, TypedDicts, or config objects to group related parameters
2. **`too-many-branches`/`too-many-statements`**: Extract into smaller functions or use strategy patterns
3. **`duplicate-code`**: Extract common code into shared utilities
4. **`protected-access`**: Consider exposing necessary functionality through public APIs

### Medium Priority (Technical Debt)

1. **`import-outside-toplevel`**: Evaluate if circular imports can be resolved structurally
2. **`too-few-public-methods`**: Consider converting to dataclasses, protocols, or functions
3. **`too-many-instance-attributes`**: Consider composition or splitting classes

### Low Priority (Acceptable)

1. **`broad-exception-caught`**: Often acceptable at system boundaries with proper logging
2. **`unnecessary-pass`**: Common for exception hierarchies
3. **`global-statement`**: Acceptable for singleton patterns with proper management
4. **`import-error`**: Expected for optional dependencies

---

*Generated: 2026-01-05*
