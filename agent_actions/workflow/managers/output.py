"""
Agent output management module.

Handles previous output loading, passthrough creation, and version correlation.
Extracted from agent_workflow.py to consolidate output handling.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
from rich.console import Console

from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.merge import merge_json_files

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class OutputManagerConfig:
    """Configuration for AgentOutputManager."""

    agent_folder: Path
    execution_order: List[str]
    agent_configs: Dict[str, Dict[str, Any]]
    agent_status: Dict[str, Dict[str, Any]]
    version_correlator: Any
    console: Optional[Console] = None
    storage_backend: Optional["StorageBackend"] = field(default=None)


class AgentOutputManager:
    """
    Manages agent output operations.

    Responsibilities:
    - Load previous agent outputs with metadata
    - Create passthrough outputs for skipped agents
    - Setup version output correlation
    - Manage input directory resolution
    """

    def __init__(self, config: OutputManagerConfig):
        """
        Initialize output manager.

        Args:
            config: OutputManagerConfig with all required parameters
        """
        self.agent_folder = config.agent_folder
        self.execution_order = config.execution_order
        self.agent_configs = config.agent_configs
        self.agent_status = config.agent_status
        self.version_correlator = config.version_correlator
        self.console = config.console or Console()
        self.storage_backend = config.storage_backend

    def _load_json_files(self, json_files: List[Path], agent_output: Dict[str, Any]) -> List[Any]:
        """Load data from JSON files."""
        outputs = []
        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        outputs.extend(data)
                    else:
                        outputs.append(data)
            except (OSError, IOError, ValueError, TypeError) as file_error:
                agent_output["errors"].append(f"Failed to read {json_file.name}: {file_error}")
        return outputs

    def _read_marker_file(self, marker_path: Path, marker_type: str, agent_name: str) -> str:
        """Read a marker file and return its content."""
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except (OSError, IOError, PermissionError) as e:
            logger.warning(
                "Could not read %s marker, using 'Unknown'",
                marker_type,
                extra={
                    "operation": f"read_{marker_type}_marker",
                    "file": str(marker_path),
                    "agent": agent_name,
                    "error": str(e),
                },
            )
            return "Unknown"
        except (ValueError, TypeError, UnicodeDecodeError) as e:
            logger.exception(
                "Unexpected error reading %s marker",
                marker_type,
                extra={
                    "operation": f"read_{marker_type}_marker",
                    "file": str(marker_path),
                    "agent": agent_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return "Unknown"

    def _process_agent_output(self, output_dir: Path, prev_agent_name: str) -> Dict[str, Any]:
        """Process output directory for a single agent."""
        agent_output = {
            "data": [],
            "status": self.agent_status.get(prev_agent_name, {}).get("status", "unknown"),
            "output_count": 0,
            "output_files": [],
            "has_data": False,
            "errors": [],
        }

        if not output_dir.exists():
            return agent_output

        json_files = list(output_dir.glob("*.json"))
        agent_output["output_files"] = [str(f.name) for f in json_files]

        if json_files:
            outputs = self._load_json_files(json_files, agent_output)
            agent_output["data"] = outputs
            agent_output["output_count"] = len(outputs)
            agent_output["has_data"] = len(outputs) > 0

        # Check for passthrough marker
        passthrough_marker = output_dir / ".passthrough_processed"
        if passthrough_marker.exists():
            agent_output["passthrough"] = True
            agent_output["passthrough_reason"] = self._read_marker_file(
                passthrough_marker, "passthrough", prev_agent_name
            )

        # Check for skip marker
        skip_marker = output_dir / ".agent_skipped"
        if skip_marker.exists():
            agent_output["skipped"] = True
            agent_output["skip_reason"] = self._read_marker_file(
                skip_marker, "skip", prev_agent_name
            )

        return agent_output

    def get_previous_outputs(self, current_idx: int) -> Dict[str, Any]:
        """
        Get outputs from previously executed agents with enhanced metadata.

        Args:
            current_idx: Index of the current agent

        Returns:
            Dictionary of previous agent outputs with metadata.
            For each agent 'foo', returns:
            - previous_outputs['foo'] = [data items]
            - previous_outputs['foo_meta'] = {status, output_count, etc.}
        """
        previous_outputs = {}

        for i in range(current_idx):
            prev_agent_name = self.execution_order[i]
            # Use simple directory name (no index prefix)
            output_dir = self.agent_folder / "target" / prev_agent_name

            try:
                agent_output = self._process_agent_output(output_dir, prev_agent_name)
                previous_outputs[prev_agent_name] = agent_output["data"]
                previous_outputs[f"{prev_agent_name}_meta"] = agent_output

            except (OSError, IOError, ValueError, TypeError, KeyError) as e:
                error_msg = f"Could not load outputs for {prev_agent_name}: {e}"
                logger.warning(
                    "Could not load output data: %s",
                    error_msg,
                    extra={
                        "prev_agent_name": prev_agent_name,
                        "output_dir": str(output_dir),
                        "operation": "load_previous_outputs",
                    },
                )
                agent_output = {
                    "data": [],
                    "status": "error",
                    "output_count": 0,
                    "output_files": [],
                    "has_data": False,
                    "errors": [error_msg],
                }
                previous_outputs[prev_agent_name] = []
                previous_outputs[f"{prev_agent_name}_meta"] = agent_output

        return previous_outputs

    def create_passthrough_output(self, idx: int, agent_type: str):
        """
        Create passthrough output for a skipped agent.

        Copies input files from ALL upstream directories to output directory
        and creates skip marker. When the same JSON file exists in multiple
        upstream directories (parallel branches), merges records by reduce_key.

        Args:
            idx: Index of the agent
            agent_type: Type/name of the agent
        """
        upstream_dirs = self.get_upstream_directories(idx)
        # Use simple directory name (no index prefix)
        output_dir = self.agent_folder / "target" / agent_type
        # Only create directory when not using storage backend
        if self.storage_backend is None:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Get reduce_key from agent config for JSON merging
        agent_config = self.agent_configs.get(agent_type, {})
        reduce_key = agent_config.get("reduce_key")

        # Collect files by name to detect duplicates that need merging
        files_by_name: Dict[str, List[str]] = {}
        for input_dir in upstream_dirs:
            if not input_dir or not os.path.exists(input_dir):
                continue
            for item in os.listdir(input_dir):
                if item.startswith("."):
                    continue
                src = os.path.join(input_dir, item)
                if os.path.isfile(src):
                    if item not in files_by_name:
                        files_by_name[item] = []
                    files_by_name[item].append(src)

        # Process each file - copy or merge as needed
        for filename, source_paths in files_by_name.items():
            dst = output_dir / filename

            if len(source_paths) == 1:
                # Single source - just copy
                try:
                    shutil.copy2(source_paths[0], dst)
                except (OSError, IOError, shutil.Error) as e:
                    logger.warning(
                        "Could not copy %s to %s: %s",
                        filename,
                        dst,
                        e,
                        exc_info=True,
                        extra={
                            "source": source_paths[0],
                            "destination": str(dst),
                            "operation": "passthrough_file_copy",
                        },
                    )
            elif filename.endswith(".json"):
                # Multiple JSON sources - merge by reduce_key
                try:
                    merged_data = self._merge_json_files(source_paths, reduce_key)
                    with open(dst, "w", encoding="utf-8") as f:
                        json.dump(merged_data, f)
                    logger.debug(
                        "Merged %d JSON files into %s (reduce_key=%s)",
                        len(source_paths),
                        filename,
                        reduce_key or "auto",
                    )
                except (OSError, IOError, json.JSONDecodeError) as e:
                    logger.warning(
                        "Could not merge JSON files for %s: %s",
                        filename,
                        e,
                    )
            else:
                # Multiple non-JSON sources - copy first (first occurrence wins)
                try:
                    shutil.copy2(source_paths[0], dst)
                except (OSError, IOError, shutil.Error) as e:
                    logger.warning(
                        "Could not copy %s to %s: %s",
                        filename,
                        dst,
                        e,
                    )

        # Create skip marker
        skip_marker = output_dir / ".agent_skipped"
        with open(skip_marker, "w", encoding="utf-8") as f:
            f.write(f"Agent {agent_type} skipped due to WHERE clause condition")

    def _merge_json_files(
        self, file_paths: List[str], reduce_key: Optional[str] = None
    ) -> List[Dict]:
        """
        Merge JSON files from multiple parallel branches by correlation key.

        Args:
            file_paths: List of JSON file paths to merge
            reduce_key: Field to correlate records by (falls back to parent_target_id -> source_guid)

        Returns:
            List of merged records
        """
        return merge_json_files([Path(p) for p in file_paths], reduce_key)

    def _resolve_upstream_from_manifest(self) -> Optional[List[str]]:
        """
        Resolve upstream directories from manifest file.

        Returns:
            List of upstream path strings from manifest, or None if no manifest.
        """
        agent_io_dir = self.agent_folder
        manifest = ArtifactLinker.read_manifest(agent_io_dir)
        if manifest is None:
            return None

        upstream_path = Path(manifest["upstream_path"])
        if not upstream_path.exists():
            logger.warning("Manifest upstream path doesn't exist: %s", upstream_path)
            return None

        return [str(upstream_path)]

    def get_upstream_directories(self, idx: int) -> List[str]:
        """
        Get upstream data directories for an agent, resolving dependencies.

        Args:
            idx: Index of the agent

        Returns:
            List of paths to upstream directories
        """
        # First agent: check manifest first, fall back to staging
        if idx == 0:
            manifest_dirs = self._resolve_upstream_from_manifest()
            if manifest_dirs:
                return manifest_dirs
            return [str(self.agent_folder / "staging")]

        current_agent = self.execution_order[idx]
        agent_config = self.agent_configs.get(current_agent, {})

        # Check for explicitly declared dependencies (DAG/Diamond)
        dependencies = agent_config.get("dependencies", [])
        if dependencies:
            upstream_dirs = []
            target_dir = self.agent_folder / "target"

            for dep_name in dependencies:
                # Use simple directory name (no index prefix)
                dep_output = target_dir / dep_name
                if dep_output.exists():
                    upstream_dirs.append(str(dep_output))
                else:
                    logger.warning(
                        "Dependency %s for agent %s not found.",
                        dep_name,
                        current_agent,
                        extra={"agent": current_agent, "dependency": dep_name},
                    )

            if upstream_dirs:
                return upstream_dirs

        # Check if agent consumes version outputs
        version_consumption_map = self.version_correlator.detect_explicit_version_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent in version_consumption_map:
            consumption_config = version_consumption_map[current_agent]
            version_sources = consumption_config["version_agents"]
            pattern = consumption_config["pattern"]

            correlated_dir = self.version_correlator.prepare_correlated_input(
                current_agent, version_sources, idx
            )

            if correlated_dir:
                self.console.print(
                    f"[blue]🔗 Using correlated input for {current_agent} from "
                    f"{len(version_sources)} version sources (pattern: {pattern})[/blue]"
                )
                return [correlated_dir]

            # Version correlation configured but failed - this is an error, not a fallback
            from agent_actions.errors import ConfigurationError

            raise ConfigurationError(
                f"Version correlation failed for '{current_agent}'. "
                f"Could not load outputs from version sources: {version_sources}. "
                f"Check that all version agents completed successfully.",
                context={
                    "agent": current_agent,
                    "version_sources": version_sources,
                    "pattern": pattern,
                },
            )

        # Standard case: use previous agent's output (Linear Chain Default)
        prev_agent = self.execution_order[idx - 1]
        # Use simple directory name (no index prefix)
        return [str(self.agent_folder / "target" / prev_agent)]

    def setup_correlation_wrapper(
        self, idx: int, original_setup_directories: Callable
    ) -> Optional[Callable]:
        """
        Create a correlation-aware setup_directories wrapper if needed.

        Args:
            idx: Index of the agent
            original_setup_directories: Original setup_directories function

        Returns:
            Wrapped setup_directories function if correlation needed, None otherwise
        """
        current_agent = self.execution_order[idx]

        version_consumption_map = self.version_correlator.detect_explicit_version_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent not in version_consumption_map:
            return None

        consumption_config = version_consumption_map[current_agent]
        version_sources = consumption_config["version_agents"]
        pattern = consumption_config["pattern"]

        def correlation_setup_directories(
            agent_folder, agent_config, previous_agent_type, agent_idx
        ):
            """Wrapper that uses correlated input for version consumers."""
            correlated_dir = self.version_correlator.prepare_correlated_input(
                current_agent, version_sources, agent_idx
            )

            if correlated_dir:
                self.console.print(
                    f"[blue]🔗 Using correlated input for {current_agent} from "
                    f"{len(version_sources)} version sources (pattern: {pattern})[/blue]"
                )
                input_directory = correlated_dir
                # Setup output directory (simple name, no index prefix)
                agent_type = agent_config["agent_type"]
                output_directory = Path(agent_folder) / "target" / agent_type
                # Only create directory when not using storage backend
                if self.storage_backend is None:
                    output_directory.mkdir(parents=True, exist_ok=True)
                # Return list of directories (not a single string) to match setup_directories signature
                return ([str(input_directory)], str(output_directory))

            # Version correlation configured but failed - this is an error, not a fallback
            from agent_actions.errors import ConfigurationError

            raise ConfigurationError(
                f"Version correlation failed for '{current_agent}'. "
                f"Could not load outputs from version sources: {version_sources}. "
                f"Check that all version agents completed successfully.",
                context={
                    "agent": current_agent,
                    "version_sources": version_sources,
                    "pattern": pattern,
                },
            )

        return correlation_setup_directories
