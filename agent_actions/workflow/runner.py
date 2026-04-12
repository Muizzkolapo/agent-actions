"""Module for managing and executing actions with different strategies in a workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
    from agent_actions.workflow.managers.manifest import ManifestManager
from agent_actions.config.di.container import ProcessorFactory
from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.types import ActionConfigDict
from agent_actions.errors import FileSystemError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source
from agent_actions.utils.file_handler import FileHandler
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream as _collect_files_from_upstream,
)
from agent_actions.workflow.runner_file_processing import (
    is_target_directory as _is_target_directory,
)
from agent_actions.workflow.runner_file_processing import (
    process_directory_files as _process_directory_files,
)
from agent_actions.workflow.runner_file_processing import (
    process_files as _process_files,
)
from agent_actions.workflow.runner_file_processing import (
    process_from_storage_backend as _process_from_storage_backend,
)
from agent_actions.workflow.runner_file_processing import (
    process_merged_files as _process_merged_files,
)
from agent_actions.workflow.runner_file_processing import (
    should_skip_item as _should_skip_item,
)
from agent_actions.workflow.runner_file_processing import (
    warn_no_files_found as _warn_no_files_found,
)
from agent_actions.workflow.strategies import (
    ActionStrategy,
    InitialStrategy,
    StandardStrategy,
    StrategyExecutionParams,
)

logger = logging.getLogger(__name__)


@dataclass
class FileProcessParams:
    """Parameters for processing files."""

    action_config: dict
    action_name: str
    strategy: ActionStrategy
    upstream_data_dirs: list[str]
    output_directory: str
    idx: int
    file_type_filter: set[str] | None = None


@dataclass
class FileLocationParams:
    """File location parameters."""

    item: Path
    input_path: Path
    output_path: Path
    input_directory: str


@dataclass
class SingleFileProcessParams:
    """Parameters for processing a single file."""

    locations: FileLocationParams
    action_config: dict
    action_name: str
    strategy: ActionStrategy
    idx: int
    source_relative_path: str | None = None  # For storage backend reads
    data: list[dict[str, Any]] | None = None  # Pre-loaded data (skips file read)


@dataclass
class ProcessGenerateParams:
    """Parameters for process_and_generate_for_action method."""

    action_config: dict
    action_name: str
    strategy: ActionStrategy
    previous_action_type: str | None
    idx: int


class ActionRunner:
    """Manages action execution using different strategies in a workflow."""

    def __init__(
        self,
        use_tools: bool,
        processor_factory: ProcessorFactory | None = None,
        storage_backend: StorageBackend | None = None,
    ) -> None:
        """Initialize the ActionRunner with strategy configurations."""
        self.use_tools: bool = use_tools
        self.processor_factory = processor_factory
        self.storage_backend = storage_backend
        self.action_configs: dict[str, dict] | None = None
        self.execution_order: list[str] = []  # Set by service_init.initialize_services
        self.action_indices: dict[str, int] = {}  # Set by service_init.initialize_services
        self.workflow_name: str | None = None  # Set by AgentWorkflow for agent_io folder lookups
        self.manifest_manager: ManifestManager | None = None  # Set by AgentWorkflow
        self.data_source_config: str | dict[str, Any] | None = None  # Set by coordinator
        self.project_root: Path | None = None  # Set by service_init.initialize_services
        self.strategies: dict[str, ActionStrategy] = {
            "initial": InitialStrategy(processor_factory),
            "intermediate": StandardStrategy(processor_factory),
            "terminal": StandardStrategy(processor_factory),
        }

    def get_action_folder(self, action_name: str, project_root: Path | None = None) -> str:
        """Return the action folder path.

        Raises:
            FileSystemError: If the action folder is not found.
        """
        search_dir: Path = resolve_project_root(project_root or self.project_root)
        folder_name = self.workflow_name if self.workflow_name else action_name
        action_folder: str | None = FileHandler.find_specific_folder(
            str(search_dir), folder_name, "agent_io"
        )
        if action_folder is None:
            raise FileSystemError(
                f"Action folder not found for action: {action_name}",
                context={
                    "action_name": action_name,
                    "workflow_name": folder_name,
                    "search_root": str(search_dir),
                    "operation": "get_action_folder",
                },
            )
        return action_folder

    def _resolve_start_node_directories(self, agent_folder: Path, agent_name: str) -> list[Path]:
        """Resolve upstream directories for a start node (no dependencies)."""
        result = resolve_start_node_data_source(agent_folder, self.data_source_config, agent_name)
        return result.directories

    def _resolve_dependency_directories(
        self, agent_folder: Path, dependencies: list[str], action_config: dict, agent_name: str
    ) -> list[Path]:
        """Resolve upstream directories from dependencies (input sources).

        Raises:
            DependencyError: If any input source directory is not found.
        """
        from agent_actions.errors import DependencyError
        from agent_actions.prompt.context.scope_inference import (
            _is_parallel_branches,
            _resolve_input_sources_for_fan_in,
        )

        target_dir = agent_folder / "target"

        # Detect fan-in pattern: multiple DIFFERENT dependencies
        # For fan-in, only resolve the primary dependency directories
        # Non-primary dependencies are loaded via historical loader (context sources)
        #
        # Exception: If reduce_key is set, it's an aggregation pattern - merge all dependencies
        #
        # Versioned primary handling: If primary_dependency is a base name (e.g., "research")
        # that matches version branches (research_1, research_2), ALL matching branches
        # become input sources.
        if len(dependencies) > 1:
            has_reduce_key = action_config.get("reduce_key") is not None
            is_parallel = _is_parallel_branches(dependencies)

            if has_reduce_key:
                # Aggregation pattern with reduce_key - merge all dependencies
                # Note: This applies regardless of whether deps are parallel branches
                # (parallel branches merge by default, reduce_key just adds grouping)
                logger.debug(
                    f"Action '{agent_name}': Aggregation pattern (reduce_key set). "
                    f"Merging all {len(dependencies)} dependencies: {dependencies}"
                )
            elif not is_parallel:
                # Fan-in pattern - use shared helper
                primary_dep = action_config.get("primary_dependency")
                try:
                    input_deps, non_primary = _resolve_input_sources_for_fan_in(
                        dependencies, primary_dep
                    )
                except ValueError as e:
                    raise DependencyError(
                        f"Action '{agent_name}': {e}",
                        context={"action": agent_name, "dependencies": dependencies},
                    ) from e

                logger.debug(
                    f"Action '{agent_name}': Fan-in pattern detected. "
                    f"Input sources: {input_deps}. "
                    f"Context sources (loaded via historical loader): {non_primary}"
                )
                dependencies = input_deps

        # Resolve all input source directories
        resolved_dirs = []
        missing_dirs = []

        for dep_name in dependencies:
            dep_path = self._resolve_single_dependency(target_dir, dep_name)
            if dep_path:
                resolved_dirs.append(dep_path)
            else:
                missing_dirs.append((dep_name, str(target_dir / dep_name)))

        # Error if any input sources are missing
        if missing_dirs:
            missing_info = [f"'{name}' ({path})" for name, path in missing_dirs]
            raise DependencyError(
                f"Action '{agent_name}': Input source directories not found: {missing_info}",
                context={
                    "action": agent_name,
                    "dependencies": dependencies,
                    "missing": [m[0] for m in missing_dirs],
                    "expected_parent": str(target_dir),
                },
            )

        # Log resolution
        if len(resolved_dirs) == 1:
            logger.debug("Action '%s': Using '%s' as input source", agent_name, dependencies[0])
        else:
            logger.info(
                "Action '%s': Merging %d input sources: %s",
                agent_name,
                len(resolved_dirs),
                dependencies,
            )

        return resolved_dirs

    def _resolve_single_dependency(self, target_dir: Path, dep_name: str) -> Path | None:
        """Resolve a single dependency directory, or None if not found."""
        # Try storage backend first if available
        if self.storage_backend is not None:
            try:
                target_files = self.storage_backend.list_target_files(dep_name)
                logger.debug(
                    "Storage backend check for %s: found %d files: %s",
                    dep_name,
                    len(target_files),
                    target_files[:5] if target_files else [],
                )
                if target_files:
                    # Data exists in SQLite - return a virtual path
                    # The actual data will be loaded from SQLite, not filesystem
                    virtual_path = target_dir / dep_name
                    return virtual_path
            except Exception as e:
                logger.warning("Storage backend check failed for %s: %s", dep_name, e)
        else:
            logger.debug("No storage backend available for dependency check: %s", dep_name)

        # Try manifest-based resolution
        if self.manifest_manager:
            try:
                dep_path = self.manifest_manager.get_output_directory(dep_name)
                if dep_path.exists():
                    return dep_path
            except KeyError:
                pass

        # Direct path using simple name
        simple_path = target_dir / dep_name
        if simple_path.exists():
            return simple_path

        logger.warning("Dependency directory not found for %s", dep_name)
        return None

    def _resolve_linear_directory(self, agent_folder: Path, previous_action_type: str) -> Path:
        """Resolve upstream directory for linear workflow (default behavior)."""
        # Use simple name without index prefix
        return agent_folder / "target" / previous_action_type

    def setup_directories(
        self, agent_folder: str, action_config: dict, previous_action_type: str | None, idx: int
    ) -> tuple[list[str], str]:
        """Set up input and output directories for the action."""
        agent_folder_path = Path(agent_folder)
        agent_type = action_config["agent_type"]
        dependencies = action_config.get("dependencies", [])

        if not dependencies and not previous_action_type:
            upstream_data_dirs = self._resolve_start_node_directories(
                agent_folder_path, action_config.get("agent_type", "unknown")
            )
        elif dependencies and hasattr(self, "action_indices") and self.action_indices:
            upstream_data_dirs = self._resolve_dependency_directories(
                agent_folder_path,
                dependencies,
                action_config,
                agent_type,  # action_name
            )
        elif previous_action_type:
            upstream_data_dirs = [
                self._resolve_linear_directory(agent_folder_path, previous_action_type)
            ]
        else:
            upstream_data_dirs = [agent_folder_path / "staging"]

        output_directory = agent_folder_path / "target" / agent_type
        if self.storage_backend is None:
            output_directory.mkdir(parents=True, exist_ok=True)
        return ([str(d) for d in upstream_data_dirs], str(output_directory))

    def _process_single_file(self, params: SingleFileProcessParams):
        """Process a single file with the strategy."""
        relative_path = params.locations.item.relative_to(params.locations.input_path)
        output_file_path = params.locations.output_path / relative_path
        if self.storage_backend is None:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
        params.strategy.execute(
            StrategyExecutionParams(
                action_config=cast("ActionConfigDict", params.action_config),
                action_name=params.action_name,
                file_path=str(params.locations.item),
                base_directory=str(params.locations.input_directory),
                output_directory=str(output_file_path.parent),
                idx=params.idx,
                action_configs=self.action_configs,
                storage_backend=self.storage_backend,
                source_relative_path=params.source_relative_path,
                data=params.data,
            )
        )

    def _should_skip_item(
        self,
        item: Path,
        input_path: Path,
        processed_paths: set,
        file_type_filter: set[str] | None = None,
    ) -> bool:
        """Check if an item should be skipped during processing."""
        return _should_skip_item(item, input_path, processed_paths, file_type_filter)

    def _collect_files_from_upstream(self, upstream_data_dirs: list[str]) -> dict[Path, list[Path]]:
        """Collect files from upstream directories, grouped by relative path."""
        return _collect_files_from_upstream(upstream_data_dirs)

    def _process_directory_files(
        self,
        input_path: Path,
        output_path: Path,
        input_directory: str,
        params: FileProcessParams,
        processed_paths: set,
    ) -> int:
        """Process all files in a single directory. Returns count of files processed."""
        return _process_directory_files(
            self, input_path, output_path, input_directory, params, processed_paths
        )

    def _warn_no_files_found(self, params: FileProcessParams) -> None:
        """Log warning if no files were found in upstream directories."""
        _warn_no_files_found(params)

    def _process_merged_files(self, params: FileProcessParams) -> int:
        """Process files from multiple upstream directories with content merging."""
        return _process_merged_files(self, params)

    def _process_from_storage_backend(self, params: FileProcessParams) -> tuple[int, int]:
        """Process data from storage backend instead of filesystem.

        Returns:
            (files_found, files_processed) to distinguish "no data" from
            "data found but processing failed".
        """
        return _process_from_storage_backend(self, params)

    def _is_target_directory(self, path: str) -> bool:
        """Return True if path is a target directory (not staging)."""
        return _is_target_directory(path)

    def process_files(self, params: FileProcessParams) -> None:
        """Walk upstream data directories and process each file with the given strategy."""
        _process_files(self, params)

    def process_and_generate_for_action(self, params: ProcessGenerateParams) -> str:
        """Process and generate data for an action using the provided strategy."""
        agent_folder: str = self.get_action_folder(params.action_name)
        input_directories, output_directory = self.setup_directories(
            agent_folder, params.action_config, params.previous_action_type, params.idx
        )

        # Resolve file_type_filter for start nodes
        file_type_filter = None
        if not params.action_config.get("dependencies") and not params.previous_action_type:
            agent_folder_path = Path(agent_folder)
            result = resolve_start_node_data_source(
                agent_folder_path, self.data_source_config, params.action_name
            )
            file_type_filter = result.file_type_filter

        self.process_files(
            FileProcessParams(
                action_config=params.action_config,
                action_name=params.action_name,
                strategy=params.strategy,
                upstream_data_dirs=input_directories,
                output_directory=output_directory,
                idx=params.idx,
                file_type_filter=file_type_filter,
            )
        )
        return output_directory

    def run_action(
        self,
        action_config: dict,
        action_name: str,
        previous_action_type: str | None,
        idx: int,
    ) -> str:
        """Run an action with the appropriate strategy based on its position in the workflow."""
        dependencies = action_config.get("dependencies", [])
        if not dependencies:
            strategy_name = "initial"
        else:
            strategy_name = "intermediate"

        strategy = self.strategies[strategy_name]
        output_folder: str = self.process_and_generate_for_action(
            ProcessGenerateParams(
                action_config=action_config,
                action_name=action_name,
                strategy=strategy,
                previous_action_type=previous_action_type,
                idx=idx,
            )
        )
        return output_folder
