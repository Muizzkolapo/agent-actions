# Agent Actions → dbt-like Structure Mapping

## Current Structure Analysis

Your codebase has:
- **185 Python files** organized in various modules
- **Processors** handling data transformation pipeline
- **Vendors/Providers** for LLM integrations
- **Workflow** orchestration
- **CLI** for user interaction
- **Artifacts** for output management

## Proposed dbt-like Structure

```
agent_actions/
├── core/                    # Core engine (like dbt/core)
├── agents/                  # Agent definitions (like dbt/models)
├── artifacts/              # Output artifacts (like dbt/artifacts)
├── tasks/                  # Task definitions (like dbt/task)
├── integrations/          # LLM & data integrations
├── cli/                   # CLI interface
└── projects/             # User projects
```

## Detailed File Mapping

### 1. CORE MODULE (Engine & Runtime)
```
agent_actions/core/
├── runtime/
│   ├── agent_runner.py         <- core/agent_runner.py
│   ├── agent_strategies.py     <- core/agent_strategies.py
│   └── application_container.py <- core/application_container.py
│
├── graph/
│   ├── agent_workflow.py       <- workflow/agent_workflow.py
│   ├── render_workflow.py      <- workflow/render_workflow.py
│   └── dependency_injection.py <- core/dependency_injection.py
│
├── parser/
│   ├── config_schema.py        <- models/config_schema.py
│   ├── config_types.py         <- models/config_types.py
│   ├── pipeline_config.py      <- models/pipeline_config.py
│   ├── processor_config.py     <- models/processor_config.py
│   └── where_parser.py         <- common/filters/where_parser.py
│
├── context/
│   ├── context.py              <- artifacts/context.py
│   ├── path_config.py          <- core/path_config.py
│   ├── path_manager.py         <- core/path_manager.py
│   └── environment_config.py   <- models/environment_config.py
│
├── contracts/
│   ├── base.py                 <- artifacts/base.py
│   ├── interfaces.py           <- common/interfaces/interfaces.py
│   └── base_async_processor.py <- common/interfaces/base_async_processor.py
│
├── exceptions.py               <- core/exceptions.py
├── utils.py                    <- core/utils.py
├── tooling.py                  <- core/tooling.py
├── constants.py                <- constants.py
└── config.py                   <- config.py
```

### 2. AGENTS MODULE (Agent Definitions)
```
agent_actions/agents/
├── extractors/
│   ├── source_data_loader.py   <- loaders/data_loaders/source_data_loader.py
│   ├── json_loader.py          <- loaders/data_loaders/json_loader.py
│   ├── xml_loader.py           <- loaders/data_loaders/xml_loader.py
│   ├── tabular_loader.py       <- loaders/data_loaders/tabular_loader.py
│   └── text_loader.py          <- loaders/data_loaders/text_loader.py
│
├── transformers/
│   ├── data_processor.py       <- processors/content/data_processor.py
│   ├── prompt_formatter.py     <- processors/prompt_processor/prompt_formatter.py
│   ├── context_preprocessor.py <- processors/content/context_preprocessor.py
│   ├── response_transformer.py <- processors/content/response_transformer.py
│   ├── sample_enricher.py      <- processors/content/sample_enricher.py
│   └── string_transformer.py   <- common/transformers/string_transformer.py
│
├── generators/
│   ├── content_generator.py    <- generators/content/content_generator.py
│   ├── data_generator.py       <- generators/content/data_generator.py
│   ├── target_generator.py     <- processors/target_processor/target_generator.py
│   └── output_processor.py     <- generators/output/output_processor.py
│
├── validators/
│   ├── validation_interceptor.py <- interceptors/validation_interceptor.py
│   ├── builtin_functions.py    <- validators/builtin_functions.py
│   ├── functions.py            <- validators/functions.py
│   └── schema_validator.py     <- cli/validators/schema_validator.py
│
├── handlers/
│   ├── agent_handlers.py       <- handlers/agent_handlers.py
│   ├── prompt_handler.py       <- handlers/prompt_handler.py
│   ├── file_handler.py         <- handlers/file_handler.py
│   └── output_handler.py       <- processors/target_processor/output_handler.py
│
└── base/
    ├── base_loader.py          <- loaders/data_loaders/base_loader.py
    ├── base_validator.py       <- cli/validators/base_validator.py
    └── agent_builder.py        <- models/agent_builder.py
```

### 3. ARTIFACTS MODULE (Output Management)
```
agent_actions/artifacts/
├── catalog.py                  <- artifacts/catalog.py
├── manifest.py                 <- artifacts/manifest.py
├── run_results.py              <- artifacts/run_results.py
├── validation_results.py       <- artifacts/validation_results.py
├── manager.py                  <- artifacts/manager.py
└── lineage/
    └── lineage_mixin.py        <- common/utils/lineage_mixin.py
```

### 4. TASKS MODULE (Command Tasks)
```
agent_actions/tasks/
├── run.py                      <- cli/commands/run_command.py
├── test.py                     <- cli/commands/clean_command.py (repurpose)
├── compile.py                  <- cli/commands/render_command.py
├── validate.py                 <- cli/validators/config_validator.py
├── batch.py                    <- cli/commands/batch_command.py
├── init.py                     <- cli/commands/init_command.py
├── docs.py                     <- cli/commands/docs_command.py
├── status.py                   <- cli/commands/status_command.py
└── services/
    ├── batch_service.py        <- services/batch_service.py
    ├── config_renderer.py      <- cli/services/config_renderer.py
    └── project_paths_factory.py <- cli/services/project_paths_factory.py
```

### 5. INTEGRATIONS MODULE (External Systems)
```
agent_actions/integrations/
├── providers/
│   ├── anthropic/
│   │   ├── provider.py         <- providers/anthropic_provider.py
│   │   └── vendor.py           <- vendors/anthropic_vendor.py
│   ├── openai/
│   │   ├── provider.py         <- providers/openai_provider.py
│   │   └── vendor.py           <- vendors/openai_vendor.py
│   ├── gemini/
│   │   ├── provider.py         <- providers/gemini_provider.py
│   │   └── vendor.py           <- vendors/gemini_vendor.py
│   ├── base.py                 <- providers/base.py
│   ├── factory.py              <- providers/factory.py
│   └── vendor_base.py          <- vendors/base_vendor.py
│
├── loaders/
│   └── batch_data_loader.py    <- loaders/data_loaders/batch_data_loader.py
│
└── interceptors/
    ├── base.py                 <- interceptors/base.py
    ├── factory.py              <- interceptors/factory.py
    └── reprompt_interceptor.py <- interceptors/reprompt_interceptor.py
```

### 6. CLI MODULE (Command Line Interface)
```
agent_actions/cli/
├── main.py                     <- cli/main.py
├── exceptions.py               <- cli/exceptions.py
└── utils/
    ├── error_handler.py        <- cli/utils/error_handler.py
    ├── service_logger.py       <- cli/utils/service_logger.py
    └── error_wrap.py           <- cli/validators/error_wrap.py
```

### 7. INTERNAL UTILITIES (_internal)
```
agent_actions/_internal/
├── common/
│   ├── monitoring/
│   │   ├── logging.py          <- common/monitoring/logging.py
│   │   └── metrics.py          <- common/monitoring/metrics.py
│   ├── resilience/
│   │   ├── circuit_breaker.py  <- common/resilience/circuit_breaker.py
│   │   └── retry.py            <- common/resilience/retry.py
│   ├── correlation/
│   │   └── tracker.py          <- common/correlation/tracker.py
│   └── feature_flags/
│       └── manager.py          <- common/feature_flags/manager.py
│
├── utils/
│   ├── processor_utils.py      <- common/utils/processor_utils.py
│   ├── processor_helpers.py    <- common/utils/processor_helpers.py
│   ├── error_handling.py       <- common/utils/error_handling.py
│   ├── field_chunking.py       <- utils/field_chunking.py
│   └── path_utils.py           <- utils/path_utils.py
│
├── filters/
│   ├── ast_nodes.py            <- common/filters/ast_nodes.py
│   ├── operator_registry.py    <- common/filters/operator_registry.py
│   ├── parser.py               <- common/filters/parser.py
│   ├── secure_parser.py        <- common/filters/secure_parser.py
│   └── where_filter.py         <- common/filters/where_filter.py
│
├── staging/
│   ├── staging_content.py      <- processors/staging_processor/staging_content.py
│   ├── staging_loader.py       <- processors/staging_processor/staging_loader.py
│   └── staging_processor.py    <- processors/staging_processor/staging_processor.py
│
└── bootstrap/
    ├── bootstrap.py            <- bootstrap.py
    ├── di_configurator.py      <- core/di_configurator.py
    └── startup_validator.py    <- core/startup_validator.py
```

## Files to Remove/Deprecate
- All empty `__init__.py` files (keep only necessary ones)
- `processors/async/` (empty)
- `common/health/` (empty)
- `common/performance/` (empty)
- `security/` (empty)
- `generators/templates/` (empty)

## New Files to Create
- `agent_actions/__version__.py` (version info)
- `agent_actions/core/__init__.py` (main imports)
- `agent_actions/agents/registry.py` (agent registry)
- `agent_actions/projects/example_project/` (example project structure)

## Import Updates Required
All imports will need to be updated from:
- `from agent_actions.processors.content.X` → `from agent_actions.agents.transformers.X`
- `from agent_actions.workflow.X` → `from agent_actions.core.graph.X`
- `from agent_actions.models.X` → `from agent_actions.core.parser.X`
- `from agent_actions.vendors.X` → `from agent_actions.integrations.providers.X`
- `from agent_actions.common.X` → `from agent_actions._internal.common.X`