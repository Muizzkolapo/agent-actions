"""Module for managing and executing agents with different strategies in a workflow."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Tuple, Dict, Optional, List

if TYPE_CHECKING:
    from agent_actions.workflow.managers.manifest import ManifestManager
    from agent_actions.storage.backend import StorageBackend
from agent_actions.errors import FileSystemError
from agent_actions.output.file_handler import FileHandler
from agent_actions.workflow.strategies import (
    InitialStrategy,
    StandardStrategy,
    AgentStrategy,
    StrategyExecutionParams,
)
from agent_actions.workflow.managers.artifacts import ArtifactLinker
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

    def _resolve_start_node_directories(self, agent_folder: Path) -> List[Path]:
        """Resolve upstream directories for the start node (idx=0).

        Tries manifest-based resolution first for inter-workflow dependencies,
        falls back to staging directory for direct file input.
        """
        manifest_dirs = self._resolve_upstream_from_manifest(agent_folder)
        if manifest_dirs:
            return manifest_dirs
        return [agent_folder / "staging"]

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

    def _resolve_linear_directory(
        self, agent_folder: Path, previous_agent_type: str, _idx: int
    ) -> Path:
        """Resolve upstream directory for linear workflow (default behavior).

        Uses simple directory name (action name) without index prefix.

        Args:
            agent_folder: Path to agent folder
            previous_agent_type: Name of previous action
            _idx: Unused - kept for API compatibility
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
        if idx == 0:
            upstream_data_dirs = self._resolve_start_node_directories(agent_folder_path)
        elif dependencies and hasattr(self, "agent_indices") and self.agent_indices:
            upstream_data_dirs = self._resolve_dependency_directories(
                agent_folder_path,
                dependencies,
                agent_config,
                agent_type,  # agent_name
            )
        elif previous_agent_type:
            upstream_data_dirs = [
                self._resolve_linear_directory(agent_folder_path, previous_agent_type, idx)
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
            )
        )

    def _should_skip_file(self, item: Path, processed_paths: set) -> bool:
        """Check if file should be skipped."""
        if item.name.startswith("."):
            logger.debug("Skipping hidden/marker file: %s", item.name)
            return True
        relative_path = item.relative_to(item.parent)
        if relative_path in processed_paths:
            logger.debug("Skipping duplicate file: %s", relative_path)
            return True
        return False

    def _should_skip_item(self, item: Path, input_path: Path, processed_paths: set) -> bool:
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
        return False

    def _merge_json_contents(
        self, file_paths: List[Path], reduce_key: Optional[str] = None
    ) -> List:
        """
        Merge JSON contents from multiple files by correlating on a key field.

        Used when processing files from multiple parallel branches that have
        the same filename. Records with the same correlation key are merged into
        a single record with all fields combined (MapReduce pattern).

        For example, if validator_1 outputs {"parent_target_id": "x", "answer_1": "A"}
        and validator_2 outputs {"parent_target_id": "x", "answer_2": "B"},
        the merged result is {"parent_target_id": "x", "answer_1": "A", "answer_2": "B"}.

        Args:
            file_paths: List of paths to JSON files to merge
            reduce_key: Field name to use for correlation (e.g., "parent_target_id").
                       Falls back to: parent_target_id -> source_guid if not specified.

        Returns:
            List of merged records, correlated by the reduce key
        """
        # Collect all records from all files
        all_records = []
        for file_path in file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_records.extend(data)
                    else:
                        all_records.append(data)
            except (json.JSONDecodeError, OSError, IOError) as e:
                logger.warning(
                    "Could not read JSON file for merging: %s - %s",
                    file_path,
                    e,
                )

        # Group records by correlation key and merge their contents
        records_by_key: Dict[str, Dict] = {}
        records_without_key = []

        # Key resolution order: explicit reduce_key -> parent_target_id -> source_guid
        key_candidates = []
        if reduce_key:
            key_candidates.append(reduce_key)
        key_candidates.extend(["parent_target_id", "source_guid"])

        for record in all_records:
            if not isinstance(record, dict):
                records_without_key.append(record)
                continue

            # Try to find correlation key using fallback chain
            correlation_value = None
            for key_name in key_candidates:
                correlation_value = record.get(key_name)
                if not correlation_value:
                    # Try nested in content
                    content = record.get("content", {})
                    if isinstance(content, dict):
                        correlation_value = content.get(key_name)
                if correlation_value:
                    break

            if correlation_value:
                if correlation_value not in records_by_key:
                    records_by_key[correlation_value] = {}

                # Merge this record into the existing one
                existing = records_by_key[correlation_value]
                self._deep_merge_record(existing, record)
            else:
                # No correlation key found - can't correlate, just include as-is
                records_without_key.append(record)

        # Return merged records plus any that couldn't be correlated
        merged = list(records_by_key.values()) + records_without_key

        logger.debug(
            "Merged %d records from %d files into %d correlated records (key=%s)",
            len(all_records),
            len(file_paths),
            len(merged),
            reduce_key or "auto",
        )

        return merged

    def _deep_merge_record(self, existing: Dict, new_record: Dict) -> None:
        """
        Deep merge a new record into an existing record.

        Handles special cases for content (dict merge) and lineage (array merge with dedup).

        Args:
            existing: Target record to merge into (modified in place)
            new_record: Source record to merge from
        """
        for key, value in new_record.items():
            if key == "content" and isinstance(value, dict):
                # Deep merge content dictionaries
                if "content" not in existing:
                    existing["content"] = {}
                if isinstance(existing["content"], dict):
                    existing["content"].update(value)
                else:
                    existing["content"] = value
            elif key == "lineage" and isinstance(value, list):
                # Merge lineage arrays with deduplication
                # Lineage entries can be strings (node_ids) or dicts with node_id
                if "lineage" not in existing:
                    existing["lineage"] = []
                if isinstance(existing["lineage"], list):
                    # Build set of existing node_ids for dedup
                    existing_node_ids = set()
                    for entry in existing["lineage"]:
                        if isinstance(entry, str):
                            existing_node_ids.add(entry)
                        elif isinstance(entry, dict) and "node_id" in entry:
                            existing_node_ids.add(entry["node_id"])

                    # Add new entries that aren't duplicates
                    for entry in value:
                        if isinstance(entry, str):
                            if entry not in existing_node_ids:
                                existing["lineage"].append(entry)
                                existing_node_ids.add(entry)
                        elif isinstance(entry, dict) and "node_id" in entry:
                            if entry["node_id"] not in existing_node_ids:
                                existing["lineage"].append(entry)
                                existing_node_ids.add(entry["node_id"])
            elif key not in existing:
                # First occurrence wins for non-mergeable fields
                existing[key] = value

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
            if self._should_skip_item(item, input_path, processed_paths):
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
                merged_data = self._merge_json_contents(file_paths, reduce_key=reduce_key)

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

    def _process_from_storage_backend(self, params: FileProcessParams) -> int:
        """
        Process data from storage backend instead of filesystem.

        Queries the storage backend for target files from upstream node(s)
        and processes each entry.

        Args:
            params: FileProcessParams with processing configuration

        Returns:
            Count of files processed
        """
        if self.storage_backend is None:
            return 0

        files_processed_count = 0
        output_path = Path(params.output_directory)

        for input_directory in params.upstream_data_dirs:
            input_path = Path(input_directory)
            # Extract node name from path (last component of target/NODE_NAME)
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
                temp_dir = None
                try:
                    # Read data from backend
                    data = self.storage_backend.read_target(node_name, relative_path)

                    # Create a temporary file with the data for processing
                    # (maintains compatibility with existing processing pipeline)
                    temp_dir = tempfile.mkdtemp()
                    temp_file = Path(temp_dir) / relative_path
                    temp_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(temp_file, "w", encoding="utf-8") as f:
                        json.dump(data, f)

                    # Process the file
                    self._process_single_file(
                        SingleFileProcessParams(
                            locations=FileLocationParams(
                                item=temp_file,
                                input_path=Path(temp_dir),
                                output_path=output_path,
                                input_directory=temp_dir,
                            ),
                            agent_config=params.agent_config,
                            agent_name=params.agent_name,
                            strategy=params.strategy,
                            idx=params.idx,
                        )
                    )
                    files_processed_count += 1

                except Exception as e:
                    logger.warning(
                        "Failed to process backend entry %s/%s: %s",
                        node_name,
                        relative_path,
                        e,
                    )
                finally:
                    # Always clean up temp directory
                    if temp_dir is not None:
                        shutil.rmtree(temp_dir, ignore_errors=True)

        return files_processed_count

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
            all_targets = all(
                self._is_target_directory(d) for d in params.upstream_data_dirs
            )
            if all_targets:
                files_processed_count = self._process_from_storage_backend(params)
                if files_processed_count > 0:
                    return
                # Fall through to filesystem if backend returned nothing

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
        self.process_files(
            FileProcessParams(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                strategy=params.strategy,
                upstream_data_dirs=input_directories,
                output_directory=output_directory,
                idx=params.idx,
            )
        )
        return output_directory

    def run_agent(
        self,
        agent_config: Dict,
        agent_name: str,
        previous_agent_type: Optional[str],
        idx: int,
        _is_last_agent: bool = False,
    ) -> str:
        """
        Runs an agent with the appropriate strategy based on its position.

        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (Optional[str]): Type of previous agent.
            idx (int): Current agent's index in workflow.
            _is_last_agent (bool): Flag indicating if this is the last agent.

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
