"""
Agent output management module.

Handles previous output loading, passthrough creation, and version correlation.
Extracted from agent_workflow.py to consolidate output handling.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple, Union, TYPE_CHECKING
from rich.console import Console

from agent_actions.errors import ConfigurationError
from agent_actions.storage.backend import (
    NODE_LEVEL_RECORD_ID,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
)
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.merge import merge_records_by_key

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
    data_source_config: Optional[Union[str, Dict[str, Any]]] = None


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
        if config.storage_backend is None:
            raise ConfigurationError(
                "AgentOutputManager requires a storage_backend. "
                "Disposition tracking is not optional.",
                context={"component": "AgentOutputManager"},
            )
        self.agent_folder = config.agent_folder
        self.execution_order = config.execution_order
        self.agent_configs = config.agent_configs
        self.agent_status = config.agent_status
        self.version_correlator = config.version_correlator
        self.console = config.console or Console()
        self.storage_backend = config.storage_backend
        self.data_source_config = config.data_source_config

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

        # Try storage backend first
        outputs, backend_files = self._load_outputs_from_backend(prev_agent_name)
        if backend_files:
            agent_output["output_files"] = backend_files

        # Fall back to filesystem if backend had no data
        if not outputs and output_dir.exists():
            json_files = list(output_dir.glob("*.json"))
            agent_output["output_files"] = [str(f.name) for f in json_files]
            if json_files:
                outputs = self._load_json_files(json_files, agent_output)

        agent_output["data"] = outputs
        agent_output["output_count"] = len(outputs)
        agent_output["has_data"] = len(outputs) > 0

        # Check for node-level passthrough disposition
        passthrough_rows = self.storage_backend.get_disposition(
            prev_agent_name,
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_PASSTHROUGH,
        )
        if passthrough_rows:
            agent_output["passthrough"] = True
            agent_output["passthrough_reason"] = passthrough_rows[0].get("reason", "")

        # Check for node-level skip disposition
        skip_rows = self.storage_backend.get_disposition(
            prev_agent_name,
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
        )
        if skip_rows:
            agent_output["skipped"] = True
            agent_output["skip_reason"] = skip_rows[0].get("reason", "")

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

        Reads upstream data from storage backend (or filesystem fallback),
        merges parallel branches by reduce_key, and writes to storage backend.

        Args:
            idx: Index of the agent
            agent_type: Type/name of the agent
        """
        upstream_dirs = self.get_upstream_directories(idx)
        agent_config = self.agent_configs.get(agent_type, {})
        reduce_key = agent_config.get("reduce_key")

        # Collect data by relative_path from all upstream nodes
        data_by_path: Dict[str, List[List[Dict]]] = {}
        target_prefix = str(self.agent_folder / "target") + os.sep

        for input_dir in upstream_dirs:
            # Only query backend for paths under target/ (agent output dirs).
            # Start-node paths (staging/, local folders, API cache) are not
            # agent outputs and have no backend entries.
            if input_dir.startswith(target_prefix):
                action_name = Path(input_dir).name
                target_files = self._read_upstream_from_backend(action_name)
                if target_files:
                    for relative_path, data in target_files.items():
                        data_by_path.setdefault(relative_path, []).append(data)
                    continue

            # Filesystem: start-node dirs or backend had no data
            for relative_path, data in self._read_upstream_from_filesystem(input_dir):
                data_by_path.setdefault(relative_path, []).append(data)

        # Write each file to storage backend
        for relative_path, data_sources in data_by_path.items():
            if len(data_sources) == 1:
                data = data_sources[0]
            else:
                all_records: List[Any] = []
                for source_data in data_sources:
                    all_records.extend(source_data)
                data = merge_records_by_key(all_records, reduce_key)
            self.storage_backend.write_target(agent_type, relative_path, data)

        # Record skip disposition
        reason = f"Agent {agent_type} skipped due to WHERE clause condition"
        self.storage_backend.set_disposition(
            agent_type, NODE_LEVEL_RECORD_ID, DISPOSITION_SKIPPED, reason=reason
        )

    def _read_upstream_from_backend(self, action_name: str) -> Dict[str, List[Dict]]:
        """Read all target files for a node from storage backend."""
        try:
            target_files = self.storage_backend.list_target_files(action_name)
        except Exception as e:
            logger.warning("Failed to list target files for %s: %s", action_name, e, exc_info=True)
            return {}
        result: Dict[str, List[Dict]] = {}
        for relative_path in target_files:
            try:
                result[relative_path] = self.storage_backend.read_target(action_name, relative_path)
            except Exception as e:
                logger.warning(
                    "Failed to read backend entry %s/%s: %s", action_name, relative_path, e
                )
        return result

    def _read_upstream_from_filesystem(self, input_dir: str) -> List[Tuple[str, List[Dict]]]:
        """Read JSON files from a filesystem directory."""
        results: List[Tuple[str, List[Dict]]] = []
        if not input_dir or not os.path.exists(input_dir):
            return results
        for item in os.listdir(input_dir):
            if item.startswith(".") or not item.endswith(".json"):
                continue
            src = os.path.join(input_dir, item)
            if not os.path.isfile(src):
                continue
            try:
                with open(src, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                results.append((item, data))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not read %s: %s", src, e)
        return results

    def _load_outputs_from_backend(self, action_name: str) -> Tuple[List[Any], List[str]]:
        """Load all target data for a node from storage backend.

        Returns:
            Tuple of (flattened records, list of relative_path strings).
        """
        try:
            target_files = self.storage_backend.list_target_files(action_name)
        except Exception as e:
            logger.warning("Failed to list target files for %s: %s", action_name, e, exc_info=True)
            return [], []
        outputs: List[Any] = []
        for relative_path in target_files:
            try:
                data = self.storage_backend.read_target(action_name, relative_path)
                if isinstance(data, list):
                    outputs.extend(data)
                else:
                    outputs.append(data)
            except Exception as e:
                logger.warning(
                    "Failed to read backend target %s/%s: %s", action_name, relative_path, e
                )
        return outputs, list(target_files)

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
        current_agent = self.execution_order[idx]
        agent_config = self.agent_configs.get(current_agent, {})
        dependencies = agent_config.get("dependencies", [])
        previous_agent_type = self.execution_order[idx - 1] if idx > 0 else None

        # Start node (no dependencies and no implicit predecessor):
        # use manifest or data source resolver
        if not dependencies and not previous_agent_type:
            manifest_dirs = self._resolve_upstream_from_manifest()
            if manifest_dirs:
                return manifest_dirs
            from agent_actions.input.loaders.data_source import resolve_start_node_data_source

            result = resolve_start_node_data_source(
                self.agent_folder, self.data_source_config, current_agent
            )
            return [str(d) for d in result.directories]

        # Check for explicitly declared dependencies (DAG/Diamond)
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

    def setup_correlation_wrapper(self, idx: int) -> Optional[Callable]:
        """
        Create a correlation-aware setup_directories wrapper if needed.

        Args:
            idx: Index of the agent

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
