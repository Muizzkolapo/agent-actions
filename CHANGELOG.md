# Changelog

All notable changes to agent-actions will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Added `CHANGELOG.md` to track project changes
- Added `CLI_USAGE.md` with comprehensive guide on running commands from subdirectories
