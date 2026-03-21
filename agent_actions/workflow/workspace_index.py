"""Workspace index for building and traversing workflow dependency graphs."""

import logging
from collections import defaultdict, deque
from pathlib import Path

import yaml

from agent_actions.errors import WorkflowError

logger = logging.getLogger(__name__)


class WorkspaceIndex:
    """Indexes workflows in a workspace to build dependency graphs for downstream execution."""

    def __init__(self, workflows_root: Path):
        """Initialize the workspace index."""
        self.workflows_root = Path(workflows_root)
        self.dependency_graph: dict[str, list[str]] = {}
        self.reverse_dependency_graph: dict[str, set[str]] = defaultdict(set)

    def scan_workspace(self) -> None:
        """Scan all agent_config/*.yml files to build dependency graphs."""
        if self.dependency_graph:  # Already scanned
            return

        if not self.workflows_root.exists():
            logger.warning("Workflows root does not exist: %s", self.workflows_root)
            return

        for workflow_dir in self.workflows_root.iterdir():
            if not workflow_dir.is_dir():
                continue

            config_dir = workflow_dir / "agent_config"
            if not config_dir.exists():
                continue

            workflow_name = workflow_dir.name
            config_file = config_dir / f"{workflow_name}.yml"

            if not config_file.exists():
                yml_files = sorted(config_dir.glob("*.yml"))
                if yml_files:
                    config_file = yml_files[0]
                    workflow_name = config_file.stem
                else:
                    continue

            self._load_workflow_deps(workflow_name, config_file)

        self._build_reverse_dag()
        logger.info("Scanned %d workflows", len(self.dependency_graph))

    def _load_workflow_deps(self, workflow_name: str, config_file: Path) -> None:
        """Load workflow dependencies from config file."""
        try:
            with open(config_file, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if config is None:
                self.dependency_graph[workflow_name] = []
                return

            # Extract workflow-level dependencies from actions
            workflow_deps = []
            for action in config.get("actions", []):
                if not isinstance(action, dict):
                    continue
                for dep in action.get("dependencies", []):
                    if isinstance(dep, dict) and "workflow" in dep:
                        upstream = dep["workflow"]
                        if upstream not in workflow_deps:
                            workflow_deps.append(upstream)

            self.dependency_graph[workflow_name] = workflow_deps

        except (yaml.YAMLError, OSError) as e:
            logger.warning("Failed to load %s: %s", workflow_name, e)
            self.dependency_graph[workflow_name] = []

    def _build_reverse_dag(self) -> None:
        """Build reverse dependency graph by inverting edges."""
        self.reverse_dependency_graph = defaultdict(set)
        for workflow, dependencies in self.dependency_graph.items():
            for dep in dependencies:
                self.reverse_dependency_graph[dep].add(workflow)

    def topological_sort_downstream(self, start_workflow: str) -> list[str]:
        """
        Return all downstream workflows in topological execution order.

        Args:
            start_workflow: The workflow whose downstream should be sorted.

        Returns:
            List of workflow names in execution order.

        Raises:
            WorkflowError: If a cyclic dependency is detected.
        """
        if not self.dependency_graph:
            self.scan_workspace()

        # Find all reachable downstream workflows (BFS)
        reachable: set[str] = set()
        queue = deque(self.reverse_dependency_graph.get(start_workflow, []))
        while queue:
            node = queue.popleft()
            if node not in reachable:
                reachable.add(node)
                queue.extend(self.reverse_dependency_graph.get(node, []))

        if not reachable:
            return []

        # Kahn's algorithm for topological sort
        in_degree: dict[str, int] = {node: 0 for node in reachable}
        for node in reachable:
            for dep in self.dependency_graph.get(node, []):
                if dep in reachable:
                    in_degree[node] += 1

        queue = deque([n for n in reachable if in_degree[n] == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for dependent in self.reverse_dependency_graph.get(node, []):
                if dependent in reachable:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        if len(result) != len(reachable):
            cycle_nodes = reachable - set(result)
            raise WorkflowError(
                "Cyclic dependency detected in downstream workflows",
                context={
                    "cycle_nodes": list(cycle_nodes),
                    "start_workflow": start_workflow,
                    "operation": "downstream_dependency_resolution",
                },
            )

        return result
