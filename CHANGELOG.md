# Changelog

All notable changes to agent-actions will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Improved Maintainability**: Refactored batch and realtime modes to eliminate code duplication ([#492](https://github.com/Muizzkolapo/agent-actions/issues/492))
  - **Phase 1**: Extracted WHERE clause and conditional filtering logic into `FilterService`
    - Eliminated ~100 lines of duplicated filtering code
    - Single source of truth for filter/skip behaviors
    - Consistent WHERE clause evaluation across modes
  - **Phase 2**: Extracted LLM context building logic into `LLMContextBuilder`
    - Eliminated ~40 lines of duplicated context building code
    - Unified interface with mode-specific implementations
    - Handles context_scope.drop and context_scope.observe directives
  - **Phase 3**: Unified prompt loading using existing `PromptFormatter`
    - Eliminated ~20 lines of duplicated prompt loading code
    - Fixed error handling typo (prompt_config → agent_config)
    - Added default fallback to agent_builder.py (previously missing)
  - **Phase 4**: Added comprehensive documentation
    - New architecture document: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
    - Enhanced inline documentation with usage examples
    - Data flow diagrams for both modes
  - **Impact**: ~160 lines of duplication eliminated, zero breaking changes, all tests passing
  - New shared services:
    - `FilterService` (`agent_actions/preprocessing/filter_service.py`) - 21 unit tests
    - `LLMContextBuilder` (`agent_actions/utilities/llm_context_builder.py`) - 20 unit tests
    - `PromptFormatter` (refactored existing) - Used by 5 files

- **Completed Prompt Preparation Unification** ([#487](https://github.com/Muizzkolapo/agent-actions/issues/487))
  - **Phase 1**: Extracted `PromptPreparationService` with 7-step orchestration pipeline
    - Eliminated ~85 lines of duplicated prompt preparation logic
    - Unified service for loading prompts, building context, applying context_scope, replacing field references, injecting functions, and adding few-shot samples
    - Fixed bug: Few-shot samples now applied in batch mode (was completely missing before)
  - **Phase 2**: Removed wrapper methods, direct service calls from generators
    - Eliminated ~115 lines of wrapper/indirection code
    - `DataGenerator` and `TargetDataGenerator` now call service directly
    - Simplified `run_dynamic_agent()` - removed `llm_additional_context` parameter
    - Fixed bug: Duplicate few-shot sample application (was appending samples twice)
  - **Phase 3**: Added integration tests and updated documentation
    - New parity tests proving batch/realtime produce identical outputs
    - Updated `BATCH_REALTIME_ARCHITECTURE.md` with PromptPreparationService documentation
    - Comprehensive usage examples for both modes
  - **Impact**: ~220 lines eliminated (duplicated logic + wrappers), guaranteed batch/realtime parity, zero breaking changes, all tests passing
  - New service:
    - `PromptPreparationService` (`agent_actions/prompt_generation/prompt_preparation_service.py`)
      - 22 unit tests in `test_prompt_preparation_service.py`
      - 6 parity integration tests in `test_prompt_preparation_parity.py`
  - **Benefits:**
    - Single point of truth for prompt preparation
    - Batch and realtime modes cannot diverge (use identical code)
    - Future features only need to modify one service
    - Comprehensive test coverage (>90%)
    - Better debugging with metadata tracking

### Added

- **UDF Auto-Discovery**: User-Defined Functions now use `@udf_tool` decorator for automatic registration. Reference functions by simple names (no module paths required), similar to dbt macros. ([#423](https://github.com/Muizzkolapo/agent-actions/issues/423))
  - `@udf_tool` decorator for auto-registering functions
  - Reference UDFs by simple function names in configs (`impl: function_name`)
  - Automatic function discovery from user_code directory
  - Duplicate function name detection at load time (prevents silent conflicts)
  - Case-insensitive exact name matching (like dbt)
- New command: `agent-actions list-udfs` to display all discovered UDFs
  - Table format output showing function names, locations, and descriptions
  - `--json` flag for programmatic use
  - `--verbose` flag for full signatures and docstrings
- New command: `agent-actions validate-udfs` to validate config references without running workflow
  - Checks all `impl` references exist in registry
  - Detects duplicate function names across files
  - Validates imports without execution
  - Ideal for CI/CD pipelines
- **Project root detection**: CLI commands now work from any subdirectory within a project. The CLI automatically searches for `agent_actions.yml` by walking up the directory tree, similar to git, dbt, and npm. ([#422](https://github.com/Muizzkolapo/agent-actions/issues/422))
  - Commands detect project root automatically by finding `agent_actions.yml`
  - Works from any subdirectory depth (src/utils/, a/b/c/d/, etc.)
  - Handles nested projects (uses nearest `agent_actions.yml`)
  - Resolves symlinks correctly
  - Displays detected project root to user: `📁 Project root: ../..`

### Changed

- Commands that require a project (`run`, `test`, `render`, `docs`, `clean`, `status`, `batch`) now display the detected project root for clarity
  - Shows relative path when possible (e.g., `../..`)
  - Shows absolute path when outside current working directory
- Error messages when not in a project now provide clearer guidance with actionable solutions
  - Shows current directory
  - Lists specific steps to resolve: navigate to project or run `agent-actions init`
  - Formatted with color (red "Error:" prefix) for better visibility

### Developer Notes

- Added `agent_actions/core/udf_registry.py` (167 lines) - Core UDF registration system
  - `@udf_tool` decorator for function registration with metadata extraction
  - `get_udf(func_name)` for case-insensitive function retrieval (exact matching only)
  - `list_udfs()` for registry inspection with full metadata
  - `clear_registry()` for test isolation
  - Global `UDF_REGISTRY` dict storing function metadata (module, file, docstring, signature)
  - Stores registry keys as lowercase for case-insensitive matching
- Added `agent_actions/core/udf_loader.py` (159 lines) - Auto-discovery logic
  - `discover_udfs(user_code_path)` scans directory and imports all Python files recursively
  - `validate_udf_references(config)` validates all `impl` fields in config exist in registry
  - Supports nested directories and multiple files
  - Skips files starting with `_` (e.g., `__init__.py`, `__pycache__`)
  - Handles import errors gracefully with `UDFLoadError`
- Added UDF-specific exceptions to `agent_actions/core/exceptions.py`:
  - `DuplicateFunctionError` - Shows both file locations when duplicate names found
  - `FunctionNotFoundError` - Lists available functions alphabetically (no fuzzy matching)
  - `UDFLoadError` - Wraps Python import errors with module/file context
- Updated `agent_actions/core/tooling.py`:
  - `execute_user_defined_function()` now uses `get_udf()` from registry
  - No backward compatibility with old `module.path` syntax (forward fixes only)
- Updated `agent_actions/core/graph/agent_workflow.py`:
  - Calls `discover_udfs()` during `__init__()` if `user_code_path` provided
  - Shows "🔍 Discovering UDFs..." and "✅ Discovered N UDF(s)" messages
  - Adds user_code_path to sys.path for imports
- Added CLI commands:
  - `agent_actions/tasks/list_udfs.py` (161 lines, 93% test coverage)
  - `agent_actions/tasks/validate_udfs.py` (193 lines, 95% test coverage)
  - Registered in `agent_actions/cli/main.py`
- Exported `udf_tool` from `agent_actions/__init__.py` for easy import
- Added `agent_actions/core/project_root.py` module with project detection utilities
  - `find_project_root(start_path)` - Walks up directory tree to find `agent_actions.yml`
  - `ensure_in_project()` - Raises `ProjectNotFoundError` if not in project
  - `get_project_root_or_cwd()` - Returns project root or current directory
  - `is_in_project()` - Boolean check for project context
  - Handles edge cases: symlinks, permission errors, nested projects, max depth limit
- Added `ProjectNotFoundError` exception (`agent_actions/core/exceptions.py`) with helpful user messages
  - Includes context: marker file, search path, solutions
  - Integrated with existing error handling system
- Added `@requires_project` decorator (`agent_actions/core/cli_decorators.py`) for CLI commands
  - Automatically finds project root before command execution
  - Changes working directory to project root
  - Always restores original CWD (try/finally pattern for defensive programming)
  - Provides user feedback with emoji icon
- Updated CLI main error handler to catch `ProjectNotFoundError` specifically
  - Custom formatting with clear, actionable error messages
  - Uses Click styling for colored output
- All project-aware commands now use `@requires_project` decorator:
  - `agent_actions/tasks/run.py`
  - `agent_actions/tasks/test.py` (clean command)
  - `agent_actions/tasks/compile.py` (render command)
  - `agent_actions/tasks/docs.py`
  - `agent_actions/tasks/status.py`
  - `agent_actions/tasks/batch.py` (status and retrieve subcommands)
- Commands that intentionally work outside projects remain unchanged:
  - `init` - Creates new projects
  - `--version` - Shows version info
  - `--help` - Displays help

### Testing

- Added comprehensive UDF tests - 53 total tests with 94%+ coverage:
  - `tests/core/test_udf_registry.py` - 16 unit tests, 100% coverage
  - `tests/core/test_udf_loader.py` - 17 unit tests, 100% coverage
  - `tests/integration/test_udf_discovery.py` - 7 integration tests
  - `tests/tasks/test_list_udfs.py` - 8 CLI tests, 93% coverage
  - `tests/tasks/test_validate_udfs.py` - 5 CLI tests, 95% coverage
- Test scenarios covered:
  - Function registration and retrieval (exact case-insensitive matching)
  - Duplicate function name detection across files
  - Auto-discovery from nested directories
  - Import error handling
  - Config reference validation
  - CLI command output formatting (table and JSON)
  - Registry isolation between tests
- Added comprehensive unit tests (`tests/core/test_project_root.py`) - 21 tests, 89% coverage
  - Project root detection from various directory depths
  - Nested projects handling
  - Symlink resolution
  - Edge cases (permission errors, directory-named marker files, very deep nesting)
- Added decorator tests (`tests/core/test_cli_decorators.py`) - 10 tests
  - Error handling
  - CWD restoration
  - Function metadata preservation
- Created manual testing checklist (`dev_artefacts/manual_testing/issue_422_checklist.md`)
  - 9 core scenarios
  - Cross-platform testing guidelines
  - Edge case verification

### Documentation

- Added comprehensive UDF documentation:
  - `agentaction-docs/docs/guides/udf-decorator.md` - Complete UDF decorator guide (~300 lines)
  - `agentaction-docs/docs/examples/udfs/` - UDF example directory with 5 files:
    - `index.md` - Overview of UDF examples
    - `basic-udf.md` - First UDF tutorial with testing
    - `multiple-files.md` - Organizing UDFs across files and directories
    - `validation-udfs.md` - Common validation patterns (8 patterns)
    - `transformation-udfs.md` - Data transformation examples (6 patterns)
  - Updated `agentaction-docs/docs/cli-reference.md` - Added `list-udfs` and `validate-udfs` command documentation
  - Updated `agentaction-docs/docs/getting-started.md` - Added "Using Custom Functions (UDFs)" section with quick examples
- Added `CHANGELOG.md` to track project changes
- Added `CLI_USAGE.md` with comprehensive guide on running commands from subdirectories
