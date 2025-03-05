"""
Module containing utility classes and functions for data processing and workflow management.
"""

import uuid
from collections import deque
from typing import Dict, List, Any, Set, TypeVar, Callable
import os

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
        Perform a topological sort on the dependencies graph.

        Args:
            dependencies: A dictionary representing the dependency graph where each key 
                         is a node and the value is a list of nodes it depends on.

        Returns:
            A list of nodes in topologically sorted order.

        Raises:
            ValueError: If there is a cycle in the dependencies or invalid input.
        """
        # Validate input
        if not isinstance(dependencies, dict):
            raise ValueError("Dependencies must be a dictionary")

        # Calculate in-degrees
        in_degree = {node: 0 for node in dependencies}
        for node, dependent_nodes in dependencies.items():
            for dependent_node in dependent_nodes:
                if dependent_node not in in_degree:
                    raise ValueError(f"Dependent node {dependent_node} not found in dependency graph")
                in_degree[dependent_node] += 1

        # Initialize queue with nodes having zero in-degree
        queue = deque([node for node in in_degree if in_degree[node] == 0])
        sorted_nodes = []

        while queue:
            current_node = queue.popleft()
            sorted_nodes.append(current_node)

            for neighbor in dependencies[current_node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(sorted_nodes) != len(dependencies):
            # Find nodes involved in cycles for better error reporting
            cycle_nodes = set(dependencies.keys()) - set(sorted_nodes)
            raise ValueError(f"Cyclic dependency detected in the workflow: {list(cycle_nodes)}")

        return sorted_nodes[::-1]  # Reverse for correct order

    @staticmethod
    def filter_dictionary(data: Dict[K, V], keys_to_remove: List[K]) -> Dict[K, V]:
        """
        Returns a new dictionary with the specified keys removed.

        Args:
            data: The original dictionary.
            keys_to_remove: A list of keys to remove from the dictionary.

        Returns:
            A new dictionary without the specified keys.
        """
        return {key: value for key, value in data.items() if key not in keys_to_remove}
        
    @staticmethod
    def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        Safely get a value from a dictionary, returning a default if the key doesn't exist.
        
        Args:
            data: Dictionary to get the value from
            key: Key to retrieve
            default: Default value to return if key is not found
            
        Returns:
            The value associated with the key, or the default value
        """
        return data.get(key, default)
        
    @staticmethod
    def ensure_directory(path: str) -> str:
        """
        Ensure a directory exists and return its path.
        
        Args:
            path: Path to the directory to ensure exists
            
        Returns:
            The path to the directory
        """
        os.makedirs(path, exist_ok=True)
        return path