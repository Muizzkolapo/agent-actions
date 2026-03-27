"""Graph algorithms for dependency resolution."""

from __future__ import annotations

from collections import deque
from typing import TypeVar

T = TypeVar("T")


def topological_sort(dependencies: dict[T, list[T]]) -> list[T]:
    """Topologically sort a dependency graph, returning nodes in processing order.

    Raises:
        DataValidationError: If input is invalid.
        WorkflowError: If a cyclic dependency is detected.
    """
    if not isinstance(dependencies, dict):
        from agent_actions.errors import DataValidationError  # type: ignore[unreachable]

        message = (
            f"Invalid type for dependencies: expected dictionary, got {type(dependencies).__name__}"
        )
        raise DataValidationError(message, context={"operation": "topological_sort"})
    all_nodes = set(dependencies.keys())
    for dependent_nodes in dependencies.values():
        all_nodes.update(dependent_nodes)
    in_degree: dict[T, int] = {node: 0 for node in all_nodes}
    for _node, dependent_nodes in dependencies.items():
        for dep_node in dependent_nodes:
            in_degree[dep_node] += 1
    queue = deque([node for node, degree in in_degree.items() if degree == 0])
    sorted_nodes: list[T] = []
    while queue:
        current = queue.popleft()
        sorted_nodes.append(current)
        if current in dependencies:
            for neighbor in dependencies[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
    if len(sorted_nodes) != len(all_nodes):
        from agent_actions.errors import WorkflowError

        cycle_nodes: set[T] = all_nodes - set(sorted_nodes)
        message = "Cyclic dependency detected in the workflow"
        raise WorkflowError(
            message,
            context={
                "cycle_nodes": list(cycle_nodes),
                "sorted_nodes": sorted_nodes,
                "all_nodes": list(all_nodes),
                "operation": "dependency_resolution",
            },
        )
    return sorted_nodes[::-1]
