"""Action output management for previous output loading and passthrough creation."""

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from rich.console import Console

from agent_actions.errors import ConfigurationError
from agent_actions.storage.backend import (
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.workflow.merge import merge_records_by_key

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class OutputManagerConfig:
    """Configuration for ActionOutputManager."""

    agent_folder: Path
    execution_order: list[str]
    action_configs: dict[str, dict[str, Any]]
    action_status: dict[str, dict[str, Any]]
    version_correlator: Any
    console: Console | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    data_source_config: str | dict[str, Any] | None = None


class ActionOutputManager:
    """Manages action output loading, passthrough creation, and version correlation."""

    def __init__(self, config: OutputManagerConfig):
        """Initialize output manager.

        Raises:
            ConfigurationError: If config.storage_backend is None
        """
        if config.storage_backend is None:
            raise ConfigurationError(
                "ActionOutputManager requires a storage_backend. "
                "Disposition tracking is not optional.",
                context={"component": "ActionOutputManager"},
            )
        self.agent_folder = config.agent_folder
        self.execution_order = config.execution_order
        self.action_configs = config.action_configs
        self.action_status = config.action_status
        self.version_correlator = config.version_correlator
        self.console = config.console or Console()
        self.storage_backend = config.storage_backend
        self.data_source_config = config.data_source_config
        self._version_consumption_map: dict | None = None
        self._version_consumption_lock = threading.Lock()

    def _load_json_files(self, json_files: list[Path], agent_output: dict[str, Any]) -> list[Any]:
        """Load data from JSON files."""
        outputs = []
        for json_file in json_files:
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        outputs.extend(data)
                    else:
                        outputs.append(data)
            except (OSError, ValueError, TypeError) as file_error:
                agent_output["errors"].append(f"Failed to read {json_file.name}: {file_error}")
        return outputs

    def _process_agent_output(self, output_dir: Path, prev_agent_name: str) -> dict[str, Any]:
        """Process output directory for a single action."""
        agent_output = {
            "data": [],
            "status": self.action_status.get(prev_agent_name, {}).get("status", "unknown"),
            "output_count": 0,
            "output_files": [],
            "has_data": False,
            "errors": [],
        }

        outputs, backend_files = self._load_outputs_from_backend(prev_agent_name)
        if backend_files:
            agent_output["output_files"] = backend_files

        if not outputs and output_dir.exists():
            json_files = list(output_dir.glob("*.json"))
            agent_output["output_files"] = [str(f.name) for f in json_files]
            if json_files:
                outputs = self._load_json_files(json_files, agent_output)

        agent_output["data"] = outputs
        agent_output["output_count"] = len(outputs)
        agent_output["has_data"] = len(outputs) > 0

        passthrough_rows = self.storage_backend.get_disposition(
            prev_agent_name,
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_PASSTHROUGH,
        )
        if passthrough_rows:
            agent_output["passthrough"] = True
            agent_output["passthrough_reason"] = passthrough_rows[0].get("reason", "")

        skip_rows = self.storage_backend.get_disposition(
            prev_agent_name,
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
        )
        if skip_rows:
            agent_output["skipped"] = True
            agent_output["skip_reason"] = skip_rows[0].get("reason", "")

        return agent_output

    def get_previous_outputs(self, current_idx: int) -> dict[str, Any]:
        """Return outputs from previously executed actions with metadata."""
        previous_outputs = {}

        for i in range(current_idx):
            prev_agent_name = self.execution_order[i]
            output_dir = self.agent_folder / "target" / prev_agent_name

            try:
                agent_output = self._process_agent_output(output_dir, prev_agent_name)
                previous_outputs[prev_agent_name] = agent_output["data"]
                previous_outputs[f"{prev_agent_name}_meta"] = agent_output

            except (OSError, ValueError, TypeError, KeyError) as e:
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
        """Create passthrough output for a skipped action."""
        upstream_dirs = self.get_upstream_directories(idx)
        agent_config = self.action_configs.get(agent_type, {})
        reduce_key = agent_config.get("reduce_key")

        # Collect data by relative_path from all upstream nodes
        data_by_path: dict[str, list[list[dict]]] = {}
        target_prefix = str(self.agent_folder / "target") + os.sep

        for input_dir in upstream_dirs:
            # Only query backend for paths under target/ (not staging/local dirs)
            if input_dir.startswith(target_prefix):
                action_name = Path(input_dir).name
                target_files = self._read_upstream_from_backend(action_name)
                if target_files:
                    for relative_path, data in target_files.items():
                        data_by_path.setdefault(relative_path, []).append(data)
                    continue

            for relative_path, data in self._read_upstream_from_filesystem(input_dir):
                data_by_path.setdefault(relative_path, []).append(data)

        for relative_path, data_sources in data_by_path.items():
            if len(data_sources) == 1:
                data = data_sources[0]
            else:
                all_records: list[Any] = []
                for source_data in data_sources:
                    all_records.extend(source_data)
                data = merge_records_by_key(all_records, reduce_key)
            self.storage_backend.write_target(agent_type, relative_path, data)

        if data_by_path:
            self.storage_backend.set_disposition(
                agent_type,
                NODE_LEVEL_RECORD_ID,
                DISPOSITION_PASSTHROUGH,
                reason=f"Action {agent_type} skipped — upstream data passed through",
            )
        else:
            self.storage_backend.set_disposition(
                agent_type,
                NODE_LEVEL_RECORD_ID,
                DISPOSITION_SKIPPED,
                reason=f"Action {agent_type} skipped due to WHERE clause condition",
            )

    def _read_upstream_from_backend(self, action_name: str) -> dict[str, list[dict]]:
        """Read all target files for a node from storage backend."""
        try:
            target_files = self.storage_backend.list_target_files(action_name)
        except Exception as e:
            logger.warning("Failed to list target files for %s: %s", action_name, e, exc_info=True)
            return {}
        result: dict[str, list[dict]] = {}
        for relative_path in target_files:
            try:
                result[relative_path] = self.storage_backend.read_target(action_name, relative_path)
            except Exception as e:
                logger.warning(
                    "Failed to read backend entry %s/%s: %s",
                    action_name,
                    relative_path,
                    e,
                    exc_info=True,
                )
        return result

    def _read_upstream_from_filesystem(self, input_dir: str) -> list[tuple[str, list[dict]]]:
        """Read JSON files from a filesystem directory."""
        results: list[tuple[str, list[dict]]] = []
        if not input_dir or not os.path.exists(input_dir):
            return results
        for item in os.listdir(input_dir):
            if item.startswith(".") or not item.endswith(".json"):
                continue
            src = os.path.join(input_dir, item)
            if not os.path.isfile(src):
                continue
            try:
                with open(src, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                results.append((item, data))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not read %s: %s", src, e, exc_info=True)
        return results

    def _load_outputs_from_backend(self, action_name: str) -> tuple[list[Any], list[str]]:
        """Load all target data for a node from storage backend."""
        try:
            target_files = self.storage_backend.list_target_files(action_name)
        except Exception as e:
            logger.warning("Failed to list target files for %s: %s", action_name, e, exc_info=True)
            return [], []
        outputs: list[Any] = []
        for relative_path in target_files:
            try:
                data = self.storage_backend.read_target(action_name, relative_path)
                if isinstance(data, list):
                    outputs.extend(data)
                else:
                    outputs.append(data)  # type: ignore[unreachable]
            except Exception as e:
                logger.warning(
                    "Failed to read backend target %s/%s: %s",
                    action_name,
                    relative_path,
                    e,
                    exc_info=True,
                )
        return outputs, list(target_files)

    def get_upstream_directories(self, idx: int) -> list[str]:
        """Return upstream data directories for an action, resolving dependencies."""
        current_agent = self.execution_order[idx]
        agent_config = self.action_configs.get(current_agent, {})
        dependencies = agent_config.get("dependencies", [])
        previous_agent_type = self.execution_order[idx - 1] if idx > 0 else None

        if not dependencies and not previous_agent_type:
            from agent_actions.input.loaders.data_source import resolve_start_node_data_source

            result = resolve_start_node_data_source(
                self.agent_folder, self.data_source_config, current_agent
            )
            return [str(d) for d in result.directories]

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

        if self._version_consumption_map is None:
            with self._version_consumption_lock:
                if self._version_consumption_map is None:
                    self._version_consumption_map = (
                        self.version_correlator.detect_explicit_version_consumption(
                            self.execution_order, self.action_configs
                        )
                    )

        if current_agent in self._version_consumption_map:
            consumption_config = self._version_consumption_map[current_agent]
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

        if idx <= 0:
            raise ConfigurationError(
                f"Action at idx={idx} has declared dependencies that could not be resolved "
                f"and has no upstream agent to fall back to.",
                context={
                    "agent": current_agent,
                    "idx": idx,
                    "execution_order": self.execution_order,
                    "operation": "resolve_input_dirs",
                },
            )
        prev_agent = self.execution_order[idx - 1]
        return [str(self.agent_folder / "target" / prev_agent)]

    def setup_correlation_wrapper(self, idx: int) -> Callable | None:
        """Create a correlation-aware setup_directories wrapper if needed."""
        current_agent = self.execution_order[idx]

        if self._version_consumption_map is None:
            with self._version_consumption_lock:
                if self._version_consumption_map is None:
                    self._version_consumption_map = (
                        self.version_correlator.detect_explicit_version_consumption(
                            self.execution_order, self.action_configs
                        )
                    )

        if current_agent not in self._version_consumption_map:
            return None

        consumption_config = self._version_consumption_map[current_agent]
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
                return ([str(input_directory)], str(output_directory))

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


# Backward-compatible alias
AgentOutputManager = ActionOutputManager
