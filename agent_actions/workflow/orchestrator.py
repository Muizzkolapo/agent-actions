"""Cross-workflow orchestration for chained pipeline execution.

Discovers workflow dependency graphs from ``upstream`` declarations in
workflow configs and executes workflow chains based on ``--downstream``
or ``--upstream`` CLI flags.
"""

import logging
from collections import deque
from pathlib import Path
from typing import Literal

import yaml

from agent_actions.errors import ConfigurationError, WorkflowError
from agent_actions.utils.graph_utils import topological_sort

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """Discovers and resolves cross-workflow dependency chains.

    Scans ``agent_config/*.yml`` for ``upstream`` declarations, builds a
    workflow-level DAG, and resolves execution plans for downstream/upstream
    traversal.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._graph: dict[str, list[str]] | None = None
        self._reverse_graph: dict[str, list[str]] | None = None

    @property
    def graph(self) -> dict[str, list[str]]:
        """Workflow DAG: ``{workflow: [upstream_workflows]}``."""
        if self._graph is None:
            self._graph, self._reverse_graph = self._discover_workflow_graph()
        return self._graph

    @property
    def reverse_graph(self) -> dict[str, list[str]]:
        """Reverse DAG: ``{workflow: [downstream_workflows]}``."""
        if self._reverse_graph is None:
            self._graph, self._reverse_graph = self._discover_workflow_graph()
        return self._reverse_graph

    def _discover_workflow_graph(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Scan workflow config files and build the workflow dependency graph.

        Supports two project layouts:
        - Flat: ``agent_config/*.yml`` (all configs in one directory)
        - Per-workflow: ``agent_workflow/*/agent_config/*.yml`` (each workflow in its own directory)

        Returns:
            Tuple of (forward_graph, reverse_graph) where:
            - forward_graph: ``{workflow: [upstream_workflows]}``
            - reverse_graph: ``{workflow: [downstream_workflows]}``
        """
        config_files = self._find_all_config_files()
        if not config_files:
            return {}, {}

        graph: dict[str, list[str]] = {}
        reverse: dict[str, list[str]] = {}

        for config_path in sorted(config_files):
            workflow_name, upstream_workflows = self._parse_upstream_from_config(config_path)
            if workflow_name is None:
                continue

            graph.setdefault(workflow_name, [])
            reverse.setdefault(workflow_name, [])

            for upstream_name in upstream_workflows:
                graph[workflow_name].append(upstream_name)
                graph.setdefault(upstream_name, [])
                reverse.setdefault(upstream_name, [])
                reverse[upstream_name].append(workflow_name)

        return graph, reverse

    def _find_all_config_files(self) -> list[Path]:
        """Collect all workflow config files from supported project layouts."""
        config_files: list[Path] = []

        # Layout 1: flat — agent_config/*.yml
        flat_dir = self.project_root / "agent_config"
        if flat_dir.is_dir():
            config_files.extend(flat_dir.glob("*.yml"))
            config_files.extend(flat_dir.glob("*.yaml"))

        # Layout 2: per-workflow — agent_workflow/*/agent_config/*.yml
        agent_workflow_dir = self.project_root / "agent_workflow"
        if agent_workflow_dir.is_dir():
            for workflow_dir in agent_workflow_dir.iterdir():
                if workflow_dir.is_dir():
                    nested_config = workflow_dir / "agent_config"
                    if nested_config.is_dir():
                        config_files.extend(nested_config.glob("*.yml"))
                        config_files.extend(nested_config.glob("*.yaml"))

        return config_files

    def _parse_upstream_from_config(self, config_path: Path) -> tuple[str | None, list[str]]:
        """Extract workflow name and upstream workflow names from a config file.

        Performs lightweight YAML parsing — only reads ``name`` and ``upstream``
        fields, does not run the full config pipeline.

        Returns:
            Tuple of (workflow_name, [upstream_workflow_names]).
            Returns (None, []) if the file is not a valid workflow config.
        """
        try:
            raw = yaml.safe_load(config_path.read_text())
        except (yaml.YAMLError, OSError):
            logger.debug("Skipping unreadable config file: %s", config_path)
            return None, []

        if not isinstance(raw, dict):
            return None, []

        workflow_name = raw.get("name")
        if not workflow_name:
            # Fallback: use filename stem (old-style configs)
            workflow_name = config_path.stem

        upstream_refs = raw.get("upstream")
        if not upstream_refs or not isinstance(upstream_refs, list):
            return workflow_name, []

        upstream_workflows = []
        for ref in upstream_refs:
            if isinstance(ref, dict) and "workflow" in ref:
                upstream_workflows.append(ref["workflow"])

        return workflow_name, upstream_workflows

    def resolve_execution_plan(
        self, target: str, direction: Literal["downstream", "upstream", "full"]
    ) -> list[str]:
        """Resolve the ordered list of workflows to execute.

        Args:
            target: The workflow the user explicitly invoked.
            direction: One of ``"downstream"``, ``"upstream"``, or ``"full"``.

        Returns:
            Ordered list of workflow names to execute.

        Raises:
            ConfigurationError: If the target workflow is not found in the graph.
            WorkflowError: If a cycle is detected in the workflow DAG.
        """
        if target not in self.graph:
            raise ConfigurationError(
                f"Workflow '{target}' not found in agent_config/. "
                f"Available workflows: {sorted(self.graph.keys())}",
                context={"operation": "resolve_execution_plan", "target": target},
            )

        if direction == "downstream":
            relevant = self._collect_descendants(target)
        elif direction == "upstream":
            relevant = self._collect_ancestors(target)
        elif direction == "full":
            ancestors = self._collect_ancestors(target)
            descendants = self._collect_descendants(target)
            relevant = ancestors | descendants
        else:
            raise ValueError(f"Invalid direction: {direction}")

        # Build sub-graph for relevant workflows and topo-sort
        sub_graph = {w: [d for d in self.graph.get(w, []) if d in relevant] for w in relevant}

        try:
            ordered = topological_sort(sub_graph)
        except WorkflowError as e:
            raise WorkflowError(
                f"Circular dependency detected in workflow chain involving '{target}'",
                context={
                    "operation": "resolve_execution_plan",
                    "target": target,
                    "direction": direction,
                    **(e.context if hasattr(e, "context") and isinstance(e.context, dict) else {}),
                },
            ) from e

        return ordered

    def _collect_descendants(self, target: str) -> set[str]:
        """BFS forward from target to find all downstream workflows."""
        visited: set[str] = {target}
        queue: deque[str] = deque([target])
        while queue:
            current = queue.popleft()
            for downstream in self.reverse_graph.get(current, []):
                if downstream not in visited:
                    visited.add(downstream)
                    queue.append(downstream)
        return visited

    def _collect_ancestors(self, target: str) -> set[str]:
        """BFS backward from target to find all upstream workflows."""
        visited: set[str] = {target}
        queue: deque[str] = deque([target])
        while queue:
            current = queue.popleft()
            for upstream in self.graph.get(current, []):
                if upstream not in visited:
                    visited.add(upstream)
                    queue.append(upstream)
        return visited

    def _find_workflow_config(self, workflow_name: str) -> Path | None:
        """Find the config file for a specific workflow across all config locations."""
        config_files = self._find_all_config_files()
        for config_path in config_files:
            if config_path.stem == workflow_name:
                return config_path
        return None

    def validate_upstream_refs(self, workflow_name: str, upstream_refs: list[dict]) -> None:
        """Validate that upstream workflow references are resolvable.

        Checks:
        - Referenced workflow configs exist
        - Referenced actions exist in the upstream workflow

        Args:
            workflow_name: Name of the workflow declaring the upstream refs.
            upstream_refs: List of upstream ref dicts with ``workflow`` and ``actions`` keys.

        Raises:
            ConfigurationError: If validation fails.
        """
        for ref in upstream_refs:
            upstream_workflow = ref.get("workflow")
            upstream_actions = ref.get("actions", [])

            if not upstream_workflow:
                continue

            # Check upstream workflow config exists
            upstream_path = self._find_workflow_config(upstream_workflow)
            if upstream_path is None:
                raise ConfigurationError(
                    f"Upstream workflow '{upstream_workflow}' referenced by "
                    f"'{workflow_name}' not found in project",
                    context={
                        "operation": "validate_upstream_refs",
                        "workflow": workflow_name,
                        "missing_workflow": upstream_workflow,
                    },
                )

            # Check referenced actions exist in upstream workflow
            if upstream_actions:
                try:
                    raw = yaml.safe_load(upstream_path.read_text())
                except Exception as e:
                    raise ConfigurationError(
                        f"Failed to parse upstream workflow config '{upstream_workflow}'",
                        context={
                            "operation": "validate_upstream_refs",
                            "config_path": str(upstream_path),
                        },
                        cause=e,
                    ) from e

                if isinstance(raw, dict) and "actions" in raw:
                    available_actions: set[str] = {
                        a["name"] for a in raw["actions"] if isinstance(a, dict) and "name" in a
                    }
                    missing = set(upstream_actions) - available_actions
                    if missing:
                        raise ConfigurationError(
                            f"Actions {sorted(missing)} not found in upstream workflow "
                            f"'{upstream_workflow}'. Available actions: {sorted(available_actions)}",
                            context={
                                "operation": "validate_upstream_refs",
                                "workflow": workflow_name,
                                "upstream_workflow": upstream_workflow,
                                "missing_actions": sorted(missing),
                            },
                        )
