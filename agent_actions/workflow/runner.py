"""Module for managing and executing agents with different strategies in a workflow."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Tuple, Dict, Optional, List, Any, Set, Union

if TYPE_CHECKING:
    from agent_actions.workflow.managers.manifest import ManifestManager
    from agent_actions.storage.backend import StorageBackend
from agent_actions.errors import FileSystemError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source
from agent_actions.output.file_handler import FileHandler
from agent_actions.workflow.strategies import (
    InitialStrategy,
    StandardStrategy,
    AgentStrategy,
    StrategyExecutionParams,
)
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.merge import merge_json_files, merge_records_by_key
from agent_actions.config.di.container import ProcessorFactory

logger = logging.getLogger(__name__)


@dataclass
class FileProcessParams:
    """Parameters for processing files."""

    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    upstream_data_dirs: List[str]
    output_directory: str
    idx: int
    file_type_filter: Optional[Set[str]] = None


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
    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    idx: int
    source_relative_path: Optional[str] = None  # For storage backend reads
    data: Optional[List[Dict[str, Any]]] = None  # Pre-loaded data (skips file read)


@dataclass
class ProcessGenerateParams:
    """Parameters for process_and_generate_for_agent method."""

    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    previous_agent_type: Optional[str]
    idx: int


class AgentRunner:
    """
    Manages the execution of agents using different strategies in a workflow.

    Handles the selection and application of appropriate strategies (initial,
    intermediate, or terminal) for each agent in the workflow sequence.
    """

    def __init__(
        self,
        use_tools: bool,
        processor_factory: Optional[ProcessorFactory] = None,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> None:
        """
        Initialize the AgentRunner with strategy configurations.

        Args:
            use_tools (bool): Flag indicating whether to use tools during agent execution.
            processor_factory (Optional[ProcessorFactory]): Factory for creating processors with DI.
            storage_backend (Optional[StorageBackend]): Storage backend for data persistence.
        """
        self.use_tools: bool = use_tools
        self.processor_factory = processor_factory
        self.storage_backend = storage_backend
        self.agent_configs: Optional[Dict[str, Dict]] = None
        self.workflow_name: Optional[str] = None  # Set by AgentWorkflow for agent_io folder lookups
        self.manifest_manager: Optional[ManifestManager] = None  # Set by AgentWorkflow
        self.data_source_config: Optional[Union[str, Dict[str, Any]]] = None  # Set by coordinator
        self.strategies: Dict[str, AgentStrategy] = {
            "initial": InitialStrategy(processor_factory),
            "intermediate": StandardStrategy(processor_factory),
            "terminal": StandardStrategy(processor_factory),
        }

    def get_agent_folder(self, agent_name: str) -> str:
        """
        Retrieves the agent folder using FileHandler.

        Args:
            agent_name (str): Name of the agent (or workflow name if workflow_name is not set).

        Returns:
            str: Path to the agent folder.

        Raises:
            ValueError: If the agent folder is not found.
        """
        current_dir: Path = Path.cwd()
        # Use workflow_name if set (for multi-agent workflows),
        # otherwise use agent_name (for single-agent or legacy)
        folder_name = self.workflow_name if self.workflow_name else agent_name
        agent_folder: Optional[str] = FileHandler.find_specific_folder(
            str(current_dir), folder_name, "agent_io"
        )
        if agent_folder is None:
            raise FileSystemError(
                f"Agent folder not found for agent: {agent_name}",
                context={
                    "agent_name": agent_name,
                    "workflow_name": folder_name,
                    "current_dir": str(current_dir),
                    "operation": "get_agent_folder",
                },
            )
        return agent_folder

    def _resolve_upstream_from_manifest(self, agent_folder: Path) -> Optional[List[Path]]:
        """
        Resolve upstream directories from manifest file.

        When a workflow depends on an upstream workflow, the artifact linker
        writes a manifest file pointing to the upstream's output. This method
        reads that manifest and returns the upstream path(s).

        Args:
            agent_folder: Path to the agent's folder (contains agent_io).

        Returns:
            List of upstream paths from manifest, or None if no manifest exists.
        """
        agent_io_dir = (
            agent_folder / "agent_io" if "agent_io" not in str(agent_folder) else agent_folder
        )
        manifest = ArtifactLinker.read_manifest(agent_io_dir)
        if manifest is None:
            return None

        upstream_path = Path(manifest["upstream_path"])
        if not upstream_path.exists():
            logger.warning("Manifest upstream path doesn't exist: %s", upstream_path)
            return None

        logger.debug("Resolved upstream from manifest: %s", upstream_path)
        return [upstream_path]

    def _resolve_start_node_directories(self, agent_folder: Path, agent_name: str) -> List[Path]:
        """Resolve upstream directories for a start node (no dependencies).

        Tries manifest-based resolution first for inter-workflow dependencies,
        then delegates to the data source resolver (which defaults to staging).
        Uses workflow-level ``self.data_source_config`` — not per-agent config.
        """
        manifest_dirs = self._resolve_upstream_from_manifest(agent_folder)
        if manifest_dirs:
            return manifest_dirs
        result = resolve_start_node_data_source(agent_folder, self.data_source_config, agent_name)
        return result.directories

    def _resolve_dependency_directories(
        self, agent_folder: Path, dependencies: List[str], agent_config: Dict, agent_name: str
    ) -> List[Path]:
        """Resolve upstream directories from dependencies (input sources).

        SIMPLIFIED BEHAVIOR (Auto-Inferred Context Dependencies):
        - `dependencies` field = input sources only
        - Context sources are auto-inferred from context_scope (not handled here)
        - Returns directories for ALL input sources

        Single dependency: Returns [dep_dir]
        Multiple dependencies: Returns [dep1_dir, dep2_dir, ...] for merging

        Args:
            agent_folder: Path to agent folder
            dependencies: List of input source names (from dependencies field)
            agent_config: Full agent configuration
            agent_name: Agent name (for logging/errors)

        Returns:
            List of input source directory paths

        Raises:
            DependencyError: If any input source directory not found
        """
        from agent_actions.errors import DependencyError
        from agent_actions.prompt.context.scope import ContextScopeProcessor

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
            has_reduce_key = agent_config.get("reduce_key") is not None
            is_parallel = ContextScopeProcessor._is_parallel_branches(dependencies)

            if has_reduce_key:
                # Aggregation pattern with reduce_key - merge all dependencies
                # Note: This applies regardless of whether deps are parallel branches
                # (parallel branches merge by default, reduce_key just adds grouping)
                logger.debug(
                    f"Action '{agent_name}': Aggregation pattern (reduce_key set). "
                    f"Merging all {len(dependencies)} dependencies: {dependencies}"
                )
            elif not is_parallel:
                # Fan-in pattern - use shared helper from ContextScopeProcessor
                primary_dep = agent_config.get("primary_dependency")
                try:
                    input_deps, non_primary = (
                        ContextScopeProcessor._resolve_input_sources_for_fan_in(
                            dependencies, primary_dep
                        )
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
            logger.info(f"Action '{agent_name}': Using '{dependencies[0]}' as input source")
        else:
            logger.info(
                f"Action '{agent_name}': Merging {len(resolved_dirs)} input sources: {dependencies}"
            )

        return resolved_dirs

    def _resolve_single_dependency(self, target_dir: Path, dep_name: str) -> Optional[Path]:
        """Resolve a single dependency directory.

        Tries storage backend first (if available), then manifest-based resolution,
        then direct path.

        Args:
            target_dir: Target directory path
            dep_name: Dependency name

        Returns:
            Resolved Path or None if not found
        """
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

    def _resolve_linear_directory(self, agent_folder: Path, previous_agent_type: str) -> Path:
        """Resolve upstream directory for linear workflow (default behavior).

        Uses simple directory name (action name) without index prefix.

        Args:
            agent_folder: Path to agent folder
            previous_agent_type: Name of previous action
        """
        # Use simple name without index prefix
        return agent_folder / "target" / previous_agent_type

    def setup_directories(
        self, agent_folder: str, agent_config: Dict, previous_agent_type: Optional[str], idx: int
    ) -> Tuple[List[str], str]:
        """
        Sets up input and output directories for the agent.

        Args:
            agent_folder (str): Path to the agent folder.
            agent_config (dict): Configuration for the agent.
            previous_agent_type (Optional[str]): Type of the previous agent in workflow.
            idx (int): Numeric index (used for execution order, not directory naming).

        Returns:
            Tuple[List[str], str]: (upstream_data_dirs, output_directory)
        """
        agent_folder_path = Path(agent_folder)
        # Use simple name without index prefix
        agent_type = agent_config["agent_type"]
        dependencies = agent_config.get("dependencies", [])

        # Determine upstream directories based on workflow position
        # Start node: no dependencies AND no previous agent (parallel/DAG workflows)
        if not dependencies and not previous_agent_type:
            upstream_data_dirs = self._resolve_start_node_directories(
                agent_folder_path, agent_config.get("agent_type", "unknown")
            )
        elif dependencies and hasattr(self, "agent_indices") and self.agent_indices:
            upstream_data_dirs = self._resolve_dependency_directories(
                agent_folder_path,
                dependencies,
                agent_config,
                agent_type,  # agent_name
            )
        elif previous_agent_type:
            upstream_data_dirs = [
                self._resolve_linear_directory(agent_folder_path, previous_agent_type)
            ]
        else:
            upstream_data_dirs = [agent_folder_path / "staging"]

        # Output directory uses simple name (no index prefix)
        output_directory = agent_folder_path / "target" / agent_type
        # Only create directory if not using storage backend
        if self.storage_backend is None:
            output_directory.mkdir(parents=True, exist_ok=True)
        return ([str(d) for d in upstream_data_dirs], str(output_directory))

    def _process_single_file(self, params: SingleFileProcessParams):
        """Process a single file with the strategy."""
        relative_path = params.locations.item.relative_to(params.locations.input_path)
        output_file_path = params.locations.output_path / relative_path
        # Only create directory if not using storage backend
        if self.storage_backend is None:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
        params.strategy.execute(
            StrategyExecutionParams(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                file_path=str(params.locations.item),
                base_directory=str(params.locations.input_directory),
                output_directory=str(output_file_path.parent),
                idx=params.idx,
                agent_configs=self.agent_configs,
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
        file_type_filter: Optional[Set[str]] = None,
    ) -> bool:
        """Check if an item should be skipped during processing."""
        if "batch" in item.parts:
            return True
        if not item.is_file():
            return True
        if item.name.startswith("."):
            return True
        relative_path = item.relative_to(input_path)
        if relative_path in processed_paths:
            return True
        if file_type_filter and item.suffix.lstrip(".").lower() not in file_type_filter:
            return True
        return False

    def _collect_files_from_upstream(self, upstream_data_dirs: List[str]) -> Dict[Path, List[Path]]:
        """
        Collect all files from upstream directories, grouped by relative path.

        This is used to identify files that need to be merged when processing
        outputs from multiple parallel branches.

        Args:
            upstream_data_dirs: List of upstream directory paths

        Returns:
            Dict mapping relative path -> list of absolute file paths
        """
        files_by_relative_path: Dict[Path, List[Path]] = {}

        for input_directory in upstream_data_dirs:
            input_path = Path(input_directory)
            if not input_path.exists():
                continue

            for item in input_path.rglob("*"):
                if "batch" in item.parts:
                    continue
                if not item.is_file():
                    continue
                if item.name.startswith("."):
                    continue

                relative_path = item.relative_to(input_path)
                if relative_path not in files_by_relative_path:
                    files_by_relative_path[relative_path] = []
                files_by_relative_path[relative_path].append(item)

        return files_by_relative_path

    def _process_directory_files(
        self,
        input_path: Path,
        output_path: Path,
        input_directory: str,
        params: FileProcessParams,
        processed_paths: set,
    ) -> int:
        """Process all files in a single directory. Returns count of files processed."""
        count = 0
        for item in input_path.rglob("*"):
            if self._should_skip_item(item, input_path, processed_paths, params.file_type_filter):
                continue

            relative_path = item.relative_to(input_path)
            processed_paths.add(relative_path)

            self._process_single_file(
                SingleFileProcessParams(
                    locations=FileLocationParams(
                        item=item,
                        input_path=input_path,
                        output_path=output_path,
                        input_directory=input_directory,
                    ),
                    agent_config=params.agent_config,
                    agent_name=params.agent_name,
                    strategy=params.strategy,
                    idx=params.idx,
                )
            )
            count += 1
        return count

    def _warn_no_files_found(self, params: FileProcessParams) -> None:
        """Log warning if no files were found in upstream directories."""
        has_content = any(
            Path(d).exists() and any(Path(d).iterdir()) for d in params.upstream_data_dirs
        )
        if not has_content:
            logger.warning(
                "No files found in upstream directories: %s. Processing continues.",
                params.upstream_data_dirs,
                extra={
                    "upstream_data_dirs": params.upstream_data_dirs,
                    "agent_name": params.agent_name,
                    "operation": "directory_processing",
                },
            )

    def _process_merged_files(self, params: FileProcessParams) -> int:
        """
        Process files from multiple upstream directories with content merging.

        When the same file exists in multiple upstream directories (parallel branches),
        merge their JSON contents before processing. This ensures downstream actions
        receive ALL data from ALL parallel branches.

        Args:
            params: FileProcessParams with processing configuration

        Returns:
            Count of files processed
        """
        output_path = Path(params.output_directory)
        files_by_path = self._collect_files_from_upstream(params.upstream_data_dirs)
        files_processed_count = 0

        for relative_path, file_paths in files_by_path.items():
            if len(file_paths) == 1:
                # Single source - process normally
                file_path = file_paths[0]
                input_path = file_path.parent
                while input_path.name != "target" and input_path.parent != input_path:
                    input_path = input_path.parent
                if input_path.name == "target":
                    input_path = file_path.parent

                # Find the upstream directory this file belongs to
                for upstream_dir in params.upstream_data_dirs:
                    upstream_path = Path(upstream_dir)
                    if file_path.is_relative_to(upstream_path):
                        input_path = upstream_path
                        break

                self._process_single_file(
                    SingleFileProcessParams(
                        locations=FileLocationParams(
                            item=file_path,
                            input_path=input_path,
                            output_path=output_path,
                            input_directory=str(input_path),
                        ),
                        agent_config=params.agent_config,
                        agent_name=params.agent_name,
                        strategy=params.strategy,
                        idx=params.idx,
                    )
                )
            else:
                # Multiple sources - merge contents (MapReduce pattern)
                # Get reduce_key from agent config for correlation
                reduce_key = params.agent_config.get("reduce_key")
                logger.debug(
                    "Merging %d files for %s from parallel branches (reduce_key=%s)",
                    len(file_paths),
                    relative_path,
                    reduce_key or "auto",
                )
                merged_data = merge_json_files(file_paths, reduce_key=reduce_key)

                # Use the first upstream directory as the base for path structure
                # This ensures the path contains 'agent_io' which source_loader expects
                # The source_loader expects: agent_io/target/{node_name}/{filename}
                # So we write the merged file to the first upstream directory
                first_upstream = Path(params.upstream_data_dirs[0])
                merged_file = first_upstream / relative_path

                # Save original content if file exists (to restore after processing)
                original_content = None
                if merged_file.exists():
                    with open(merged_file, "r", encoding="utf-8") as f:
                        original_content = f.read()

                # Write merged data
                merged_file.parent.mkdir(parents=True, exist_ok=True)
                with open(merged_file, "w", encoding="utf-8") as f:
                    json.dump(merged_data, f)

                try:
                    self._process_single_file(
                        SingleFileProcessParams(
                            locations=FileLocationParams(
                                item=merged_file,
                                input_path=first_upstream,
                                output_path=output_path,
                                input_directory=str(first_upstream),
                            ),
                            agent_config=params.agent_config,
                            agent_name=params.agent_name,
                            strategy=params.strategy,
                            idx=params.idx,
                        )
                    )
                finally:
                    # Restore original content if we had one
                    if original_content is not None:
                        with open(merged_file, "w", encoding="utf-8") as f:
                            f.write(original_content)
                    # Don't delete the file - it's a real upstream output

            files_processed_count += 1

        return files_processed_count

    def _process_from_storage_backend(self, params: FileProcessParams) -> Tuple[int, int]:
        """
        Process data from storage backend instead of filesystem.

        Queries the storage backend for target files from upstream node(s)
        and processes each entry. Merges data from parallel branches when
        the same relative path exists in multiple upstream nodes.

        Args:
            params: FileProcessParams with processing configuration

        Returns:
            Tuple of (files_found, files_processed) to distinguish between
            "no data in DB" and "data found but processing failed"
        """
        if self.storage_backend is None:
            return (0, 0)

        output_path = Path(params.output_directory)
        processing_errors = []

        # Collect data from all upstream nodes, grouped by relative path
        # This enables merge behavior for parallel branches
        data_by_path: Dict[str, List[Tuple[str, Any]]] = {}  # path -> [(node_name, data), ...]

        for input_directory in params.upstream_data_dirs:
            input_path = Path(input_directory)
            node_name = input_path.name

            # Skip staging directories - those are still file-based
            if "staging" in str(input_path):
                continue

            # Query backend for files from this node
            try:
                target_files = self.storage_backend.list_target_files(node_name)
            except Exception as e:
                logger.debug(
                    "Could not list target files from backend for %s: %s",
                    node_name,
                    e,
                )
                continue

            for relative_path in target_files:
                try:
                    data = self.storage_backend.read_target(node_name, relative_path)
                    if relative_path not in data_by_path:
                        data_by_path[relative_path] = []
                    data_by_path[relative_path].append((node_name, data))
                except Exception as e:
                    logger.warning(
                        "Failed to read backend entry %s/%s: %s",
                        node_name,
                        relative_path,
                        e,
                    )

        files_found = len(data_by_path)
        files_processed = 0

        for relative_path, data_sources in data_by_path.items():
            try:
                if len(data_sources) == 1:
                    # Single source - use data directly
                    _, data = data_sources[0]
                else:
                    # Multiple sources - merge contents (MapReduce pattern)
                    reduce_key = params.agent_config.get("reduce_key")
                    logger.debug(
                        "Merging %d sources for %s from parallel branches (reduce_key=%s)",
                        len(data_sources),
                        relative_path,
                        reduce_key or "auto",
                    )
                    # Collect all data lists and merge them
                    all_data = []
                    for _, source_data in data_sources:
                        if isinstance(source_data, list):
                            all_data.extend(source_data)
                        else:
                            all_data.append(source_data)
                    data = merge_records_by_key(all_data, reduce_key)

                # Pass data directly to avoid temp file I/O overhead.
                # We use output_path as the virtual input path because:
                # 1. Template resolution requires valid file_path and base_directory
                # 2. The actual data comes from params.data, not from reading the file
                # 3. Using output_path ensures relative path calculation works correctly
                source_key = str(Path(relative_path).with_suffix(""))
                virtual_input_path = output_path / relative_path

                record_count = len(data) if isinstance(data, list) else 1
                logger.debug(
                    "Processing %s with %d pre-loaded records (no file read)",
                    relative_path,
                    record_count,
                )
                self._process_single_file(
                    SingleFileProcessParams(
                        locations=FileLocationParams(
                            item=virtual_input_path,
                            input_path=output_path,
                            output_path=output_path,
                            input_directory=str(output_path),
                        ),
                        agent_config=params.agent_config,
                        agent_name=params.agent_name,
                        strategy=params.strategy,
                        idx=params.idx,
                        source_relative_path=source_key,
                        data=data,
                    )
                )
                files_processed += 1

            except Exception as e:
                error_msg = f"{relative_path}: {e}"
                processing_errors.append(error_msg)
                logger.warning(
                    "Failed to process backend entry %s: %s",
                    relative_path,
                    e,
                    exc_info=True,
                )

        # Log summary if some files failed
        if files_found > 0 and files_processed < files_found:
            logger.error(
                "Storage backend processing incomplete: %d/%d files processed for %s. Errors: %s",
                files_processed,
                files_found,
                params.agent_name,
                "; ".join(processing_errors[:3]),  # Show first 3 errors
                extra={
                    "agent_name": params.agent_name,
                    "files_found": files_found,
                    "files_processed": files_processed,
                    "error_count": len(processing_errors),
                },
            )

        return (files_found, files_processed)

    def _is_target_directory(self, path: str) -> bool:
        """Check if path is a target directory (not staging)."""
        return "target" in path and "staging" not in path

    def process_files(self, params: FileProcessParams) -> None:
        """
        Walks through the upstream data directories, processing each file with the given strategy,
        explicitly excluding:
        - Any directory named 'batch'
        - Hidden files (starting with '.')
        - Marker files (e.g., .passthrough_processed)

        When a storage backend is available, reads from the database instead of filesystem.

        When processing files from multiple upstream directories (parallel branches),
        files with the same relative path will have their JSON contents merged to ensure
        downstream actions receive all data from all branches.
        """
        # Try storage backend first for target directories
        if self.storage_backend is not None:
            # Check if all upstream directories are target directories (not staging)
            all_targets = all(self._is_target_directory(d) for d in params.upstream_data_dirs)
            if all_targets:
                files_found, files_processed = self._process_from_storage_backend(params)
                if files_processed > 0:
                    return
                if files_found > 0:
                    # Data was found in DB but processing failed
                    # Don't fall through to filesystem (virtual paths don't exist)
                    from agent_actions.errors import DependencyError

                    raise DependencyError(
                        f"Action '{params.agent_name}': Found {files_found} files in storage "
                        f"backend but failed to process any. Check logs for details.",
                        context={
                            "action": params.agent_name,
                            "files_found": files_found,
                            "upstream_dirs": params.upstream_data_dirs,
                        },
                    )
                # Fall through to filesystem if backend had no data

        # Use merging approach when there are multiple upstream directories
        # This handles parallel branch outputs correctly
        if len(params.upstream_data_dirs) > 1:
            # Check if this is parallel branches (same action) or multiple deps
            upstream_paths = [Path(d) for d in params.upstream_data_dirs]
            dep_names = [p.name for p in upstream_paths]
            unique_names = set(dep_names)

            if len(unique_names) == 1:
                # Parallel branches from same action - merge them
                logger.info(
                    f"Detected parallel branches from '{unique_names.pop()}'. "
                    f"Merging {len(upstream_paths)} outputs."
                )
                files_processed_count = self._process_merged_files(params)
                if files_processed_count == 0:
                    self._warn_no_files_found(params)
                return
            else:
                # Fan-in pattern: multiple different dependencies
                # This should have been resolved to primary dependency in _resolve_dependency_directories()
                # If we reach here, it means all directories should be merged (aggregation pattern)
                logger.info(
                    f"Multiple dependency directories detected: {dep_names}. "
                    f"Merging all inputs (aggregation pattern)."
                )
                files_processed_count = self._process_merged_files(params)
                if files_processed_count == 0:
                    self._warn_no_files_found(params)
                return

        # Single upstream directory - use original logic (more efficient)
        files_processed_count = 0
        output_path = Path(params.output_directory)
        processed_relative_paths: set = set()

        for input_directory in params.upstream_data_dirs:
            input_path = Path(input_directory)
            if not input_path.exists():
                logger.warning("Upstream directory not found: %s", input_directory)
                continue

            files_processed_count += self._process_directory_files(
                input_path, output_path, input_directory, params, processed_relative_paths
            )

        if files_processed_count == 0:
            self._warn_no_files_found(params)

    def process_and_generate_for_agent(self, params: ProcessGenerateParams) -> str:
        """
        Processes and generates data for an agent using the provided strategy.

        Args:
            params: ProcessGenerateParams containing all required parameters

        Returns:
            str: Path to the output directory.
        """
        agent_folder: str = self.get_agent_folder(params.agent_name)
        input_directories, output_directory = self.setup_directories(
            agent_folder, params.agent_config, params.previous_agent_type, params.idx
        )

        # Resolve file_type_filter for start nodes — only when the data source
        # resolver is used (not when inputs come from an upstream manifest)
        file_type_filter = None
        if not params.agent_config.get("dependencies") and not params.previous_agent_type:
            agent_folder_path = Path(agent_folder)
            if not self._resolve_upstream_from_manifest(agent_folder_path):
                result = resolve_start_node_data_source(
                    agent_folder_path, self.data_source_config, params.agent_name
                )
                file_type_filter = result.file_type_filter

        self.process_files(
            FileProcessParams(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                strategy=params.strategy,
                upstream_data_dirs=input_directories,
                output_directory=output_directory,
                idx=params.idx,
                file_type_filter=file_type_filter,
            )
        )
        return output_directory

    def run_agent(
        self,
        agent_config: Dict,
        agent_name: str,
        previous_agent_type: Optional[str],
        idx: int,
    ) -> str:
        """
        Runs an agent with the appropriate strategy based on its position.

        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (Optional[str]): Type of previous agent.
            idx (int): Current agent's index in workflow.

        Returns:
            str: Path to the output directory.
        """
        # Determine strategy based on dependencies, not position
        # Actions without dependencies (including loop iterations of first-stage actions)
        # should use InitialStrategy with is_first_stage=True to generate source_guid
        dependencies = agent_config.get("dependencies", [])
        if not dependencies:
            strategy_name = "initial"
        else:
            strategy_name = "intermediate"

        strategy = self.strategies[strategy_name]
        output_folder: str = self.process_and_generate_for_agent(
            ProcessGenerateParams(
                agent_config=agent_config,
                agent_name=agent_name,
                strategy=strategy,
                previous_agent_type=previous_agent_type,
                idx=idx,
            )
        )
        return output_folder
