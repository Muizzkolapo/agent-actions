# pylint: disable=duplicate-code
"""
Agent output management module.

Handles previous output loading, passthrough creation, and loop correlation.
Extracted from agent_workflow.py to consolidate output handling.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from rich.console import Console

from agent_actions.orchestration.artifact_linker import ArtifactLinker

logger = logging.getLogger(__name__)


@dataclass
class OutputManagerConfig:
    """Configuration for AgentOutputManager."""

    agent_folder: Path
    execution_order: List[str]
    agent_configs: Dict[str, Dict[str, Any]]
    agent_status: Dict[str, Dict[str, Any]]
    loop_correlator: Any
    console: Optional[Console] = None


class AgentOutputManager:
    """
    Manages agent output operations.

    Responsibilities:
    - Load previous agent outputs with metadata
    - Create passthrough outputs for skipped agents
    - Setup loop output correlation
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
        self.loop_correlator = config.loop_correlator
        self.console = config.console or Console()

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
            output_dir = self.agent_folder / "target" / f"node_{i}_{prev_agent_name}"

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

        Copies input files to output directory and creates skip marker.

        Args:
            idx: Index of the agent
            agent_type: Type/name of the agent
        """
        upstream_dirs = self.get_upstream_directories(idx)
        input_dir = upstream_dirs[0] if upstream_dirs else None
        output_dir = self.agent_folder / "target" / f"node_{idx}_{agent_type}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy input files to output
        if os.path.exists(input_dir):
            for item in os.listdir(input_dir):
                src = os.path.join(input_dir, item)
                dst = output_dir / item
                try:
                    shutil.copy2(src, dst)
                except (OSError, IOError, shutil.Error) as e:
                    logger.warning(
                        "Could not copy %s to %s: %s",
                        item,
                        dst,
                        e,
                        exc_info=True,
                        extra={
                            "source": src,
                            "destination": str(dst),
                            "operation": "passthrough_file_copy",
                        },
                    )

        # Create skip marker
        skip_marker = output_dir / ".agent_skipped"
        with open(skip_marker, "w", encoding="utf-8") as f:
            f.write(f"Agent {agent_type} skipped due to WHERE clause condition")

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

    def get_upstream_directories(self, idx: int) -> List[str]:  # pylint: disable=too-many-locals
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
            for dep_name in dependencies:
                # Find the index of the dependency
                if dep_name in self.execution_order:
                    dep_idx = self.execution_order.index(dep_name)
                    # Construct output path for that dependency
                    dep_output = self.agent_folder / "target" / f"node_{dep_idx}_{dep_name}"
                    upstream_dirs.append(str(dep_output))
                else:
                    logger.warning(
                        "Dependency %s for agent %s not found in execution order.",
                        dep_name,
                        current_agent,
                        extra={"agent": current_agent, "dependency": dep_name},
                    )
            if upstream_dirs:
                return upstream_dirs

        # Check if agent consumes loop outputs
        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent in loop_consumption_map:
            consumption_config = loop_consumption_map[current_agent]
            loop_sources = consumption_config["loop_agents"]
            pattern = consumption_config["pattern"]

            correlated_dir = self.loop_correlator.prepare_correlated_input(
                current_agent, loop_sources, idx
            )

            if correlated_dir:
                self.console.print(
                    f"[blue]🔗 Using correlated input for {current_agent} from "
                    f"{len(loop_sources)} loop sources (pattern: {pattern})[/blue]"
                )
                return [correlated_dir]

            self.console.print(
                f"[yellow]⚠️ Failed to correlate loop outputs for "
                f"{current_agent}, falling back to standard input[/yellow]"
            )

        # Standard case: use previous agent's output (Linear Chain Default)
        prev_agent = self.execution_order[idx - 1]
        return [str(self.agent_folder / "target" / f"node_{idx - 1}_{prev_agent}")]

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

        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent not in loop_consumption_map:
            return None

        consumption_config = loop_consumption_map[current_agent]
        loop_sources = consumption_config["loop_agents"]
        pattern = consumption_config["pattern"]

        def correlation_setup_directories(
            agent_folder, agent_config, previous_agent_type, agent_idx
        ):
            """Wrapper that uses correlated input for loop consumers."""
            correlated_dir = self.loop_correlator.prepare_correlated_input(
                current_agent, loop_sources, agent_idx
            )

            if correlated_dir:
                self.console.print(
                    f"[blue]🔗 Using correlated input for {current_agent} from "
                    f"{len(loop_sources)} loop sources (pattern: {pattern})[/blue]"
                )
                input_directory = correlated_dir
                # Setup output directory
                indexed_agent_type = f"node_{agent_idx}_{agent_config['agent_type']}"
                output_directory = Path(agent_folder) / "target" / indexed_agent_type
                output_directory.mkdir(parents=True, exist_ok=True)
                return (str(input_directory), str(output_directory))

            self.console.print(
                f"[yellow]⚠️ Failed to correlate loop outputs for "
                f"{current_agent}, falling back to standard input[/yellow]"
            )
            input_dir, _ = original_setup_directories(
                agent_folder, agent_config, previous_agent_type, agent_idx
            )
            input_directory = input_dir

            # Setup output directory
            indexed_agent_type = f"node_{agent_idx}_{agent_config['agent_type']}"
            output_directory = Path(agent_folder) / "target" / indexed_agent_type
            output_directory.mkdir(parents=True, exist_ok=True)

            return (str(input_directory), str(output_directory))

        return correlation_setup_directories
