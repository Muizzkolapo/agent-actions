# pylint: disable=duplicate-code
"""Dependency validator for pre-flight validation.

Validates agent dependencies, detecting circular dependencies and missing
references before workflow execution begins.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)


class DependencyValidator(BaseValidator):
    """Validates agent dependencies for circular references and missing agents.

    This validator builds a dependency graph from workflow configuration
    and detects issues like:
    - Circular dependencies (A -> B -> C -> A)
    - Missing dependency references
    - Self-dependencies

    Attributes:
        issues: List of ValidationIssue objects found during validation
    """

    def __init__(self) -> None:
        super().__init__()
        self.issues: List[ValidationIssue] = []

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Validate dependencies in workflow configuration.

        Args:
            data: Dictionary containing:
                - 'workflow_config': The workflow configuration dict
                - 'agents': Dict mapping agent names to their configs
            config: Optional config with:
                - 'agent_name': Optional specific agent to validate

        Returns:
            bool: True if all dependencies are valid, False otherwise
        """
        self.clear_errors()
        self.clear_warnings()
        self.issues = []

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary.")
            return False

        workflow_config = data.get("workflow_config", {})
        agents = data.get("agents", {})

        if not agents:
            # Try to extract agents from workflow_config
            agents = self._extract_agents_from_config(workflow_config)

        if not agents:
            return True  # No agents to validate

        # Build dependency graph
        graph = self._build_dependency_graph(agents)

        # Check for circular dependencies
        cycles = self._detect_cycles(graph)
        if cycles:
            for cycle in cycles:
                cycle_str = " -> ".join(cycle)
                self.add_error(f"Circular dependency detected: {cycle_str}")
                self.issues.append(
                    PreFlightErrorFormatter.create_dependency_issue(
                        message="Circular dependency detected",
                        cycle_path=cycle,
                    )
                )

        # Check for missing dependencies
        missing = self._find_missing_dependencies(agents, graph)
        if missing:
            for agent, missing_deps in missing.items():
                for dep in missing_deps:
                    self.add_error(f"Agent '{agent}' depends on unknown agent '{dep}'")
                self.issues.append(
                    ValidationIssue(
                        message=f"Missing dependency references in '{agent}'",
                        issue_type="error",
                        category="dependency",
                        missing_refs=missing_deps,
                        available_refs=list(agents.keys()),
                        hint="Add the missing agent(s) to your workflow or remove the dependency.",
                        agent_name=agent,
                    )
                )

        # Check for self-dependencies
        self_deps = self._find_self_dependencies(graph)
        if self_deps:
            for agent in self_deps:
                self.add_warning(f"Agent '{agent}' depends on itself")
                self.issues.append(
                    ValidationIssue(
                        message=f"Agent '{agent}' has a self-dependency",
                        issue_type="warning",
                        category="dependency",
                        hint="Remove the self-dependency unless it's intentional.",
                        agent_name=agent,
                    )
                )

        return not self.has_errors()

    def validate_workflow(
        self,
        workflow_config: Dict[str, Any],
        agents: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Convenience method to validate workflow dependencies.

        Args:
            workflow_config: Workflow configuration dictionary
            agents: Optional pre-extracted agents dict

        Returns:
            bool: True if dependencies are valid
        """
        data = {
            "workflow_config": workflow_config,
            "agents": agents or {},
        }
        return self.validate(data)

    def _extract_agents_from_config(
        self, workflow_config: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Extract agent configurations from workflow config.

        Args:
            workflow_config: Workflow configuration

        Returns:
            Dict mapping agent names to their configurations
        """
        agents = {}

        # Try different locations where agents might be defined
        if "agents" in workflow_config:
            for agent in workflow_config["agents"]:
                if isinstance(agent, dict):
                    name = agent.get("name") or agent.get("agent_type")
                    if name:
                        agents[name] = agent
                elif isinstance(agent, str):
                    agents[agent] = {}

        if "actions" in workflow_config:
            for action in workflow_config["actions"]:
                if isinstance(action, dict):
                    name = action.get("name") or action.get("agent_type")
                    if name:
                        agents[name] = action

        return agents

    def _build_dependency_graph(self, agents: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
        """Build dependency graph from agent configurations.

        Args:
            agents: Dict mapping agent names to their configs

        Returns:
            Dict mapping each agent to list of its dependencies
        """
        graph = {}

        for name, config in agents.items():
            dependencies = []

            # Check 'depends_on' field
            if depends_on := config.get("depends_on"):
                if isinstance(depends_on, str):
                    dependencies.append(depends_on)
                elif isinstance(depends_on, list):
                    dependencies.extend(depends_on)

            # Check 'dependencies' field
            if deps := config.get("dependencies"):
                if isinstance(deps, str):
                    dependencies.append(deps)
                elif isinstance(deps, list):
                    dependencies.extend(deps)

            # Check 'upstream' field (alternate name)
            if upstream := config.get("upstream"):
                if isinstance(upstream, str):
                    dependencies.append(upstream)
                elif isinstance(upstream, list):
                    dependencies.extend(upstream)

            graph[name] = list(set(dependencies))  # Deduplicate

        return graph

    def _detect_cycles(self, graph: Dict[str, List[str]]) -> List[List[str]]:
        """Detect circular dependencies using DFS.

        Args:
            graph: Dependency graph

        Returns:
            List of cycles, where each cycle is a list of agent names
        """
        cycles = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for node in graph:
            if node not in visited:
                dfs(node)

        return cycles

    def _find_missing_dependencies(
        self,
        agents: Dict[str, Dict[str, Any]],
        graph: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        """Find dependencies that reference non-existent agents.

        Args:
            agents: Known agents
            graph: Dependency graph

        Returns:
            Dict mapping agent names to their missing dependencies
        """
        missing = {}
        agent_names = set(agents.keys())

        for agent, dependencies in graph.items():
            unknown_deps = [d for d in dependencies if d not in agent_names]
            if unknown_deps:
                missing[agent] = unknown_deps

        return missing

    def _find_self_dependencies(self, graph: Dict[str, List[str]]) -> List[str]:
        """Find agents that depend on themselves.

        Args:
            graph: Dependency graph

        Returns:
            List of agent names with self-dependencies
        """
        return [agent for agent, deps in graph.items() if agent in deps]

    def get_dependency_order(self, graph: Dict[str, List[str]]) -> Tuple[List[str], bool]:
        """Get topological sort of agents (execution order).

        Args:
            graph: Dependency graph

        Returns:
            Tuple of (ordered list of agent names, success boolean)
            If there are cycles, returns partial order and False
        """
        in_degree = {node: 0 for node in graph}
        for deps in graph.values():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 1

        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for dep in graph.get(node, []):
                if dep in in_degree:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        success = len(result) == len(graph)
        return result, success

    def get_issues(self) -> List[ValidationIssue]:
        """Get the list of validation issues found.

        Returns:
            List of ValidationIssue objects
        """
        return self.issues
