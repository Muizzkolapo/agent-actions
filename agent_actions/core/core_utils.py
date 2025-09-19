"""
Module containing utility classes and functions for data processing and workflow management.
"""

import os
import uuid
from collections import deque
from typing import Dict, List, Any, Set, TypeVar

# Type variables for generics
T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


class Utils:
    """
    A class containing miscellaneous utility functions.
    """

    @staticmethod
    def generate_id() -> str:
        """
        Generate a unique identifier.

        Returns:
            A UUID4 unique identifier as a string.
        """
        return str(uuid.uuid4())

    @staticmethod
    def topological_sort(dependencies: Dict[T, List[T]]) -> List[T]:
        """
        Perform a topological sort on a dependency graph.

        Args:
            dependencies: A dictionary where each key is a node and the value is a list of nodes
                          that the key depends on.

        Returns:
            A list of nodes in topologically sorted order (reversed order for correct processing).

        Raises:
            ValueError: If the dependencies input is invalid or a cyclic dependency is detected.
        """
        if not isinstance(dependencies, dict):
            raise ValueError("Dependencies must be a dictionary")

        # Initialize in-degree count for all nodes (including dependencies)
        all_nodes = set(dependencies.keys())
        for dependent_nodes in dependencies.values():
            all_nodes.update(dependent_nodes)

        in_degree: Dict[T, int] = {node: 0 for node in all_nodes}
        for node, dependent_nodes in dependencies.items():
            for dep_node in dependent_nodes:
                in_degree[dep_node] += 1

        # Start with nodes having zero in-degree
        queue = deque([node for node, degree in in_degree.items() if degree == 0])
        sorted_nodes: List[T] = []

        while queue:
            current = queue.popleft()
            sorted_nodes.append(current)

            # Only process neighbors if this node has dependencies in the original dict
            if current in dependencies:
                for neighbor in dependencies[current]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        if len(sorted_nodes) != len(all_nodes):
            cycle_nodes: Set[T] = all_nodes - set(sorted_nodes)
            raise ValueError(f"Cyclic dependency detected in the workflow: {list(cycle_nodes)}")

        # Reverse the sorted order for correct processing order
        return sorted_nodes[::-1]

    @staticmethod
    def filter_dictionary(data: Dict[K, V], keys_to_remove: List[K]) -> Dict[K, V]:
        """
        Return a new dictionary with the specified keys removed.

        Args:
            data: The original dictionary.
            keys_to_remove: A list of keys to remove.

        Returns:
            A new dictionary without the specified keys.
        """
        return {key: value for key, value in data.items() if key not in keys_to_remove}

    @staticmethod
    def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        Safely retrieve a value from a dictionary, returning a default if the key doesn't exist.

        Args:
            data: Dictionary to retrieve the value from.
            key: Key to look up.
            default: Default value if key is not found.

        Returns:
            The value associated with the key or the default.
        """
        return data.get(key, default)

    @staticmethod
    def ensure_directory(path: str) -> str:
        """
        Ensure a directory exists by creating it if necessary.

        Args:
            path: The path to the directory.

        Returns:
            The path to the directory.
        """
        os.makedirs(path, exist_ok=True)
        return path
