"""
Module containing utility classes and functions for data processing and workflow management.
"""

import uuid
from collections import deque
from typing import Dict, List, Any, Set, TypeVar, Callable
import os
from agent_actions.core.exceptions import (
    WorkflowError, 
    ValidationError,
    ErrorCategory,
    DirectoryError
)
from agent_actions.core.error_utils import handle_errors, try_operation

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
    @handle_errors(error_category=ErrorCategory.WORKFLOW)
    def topological_sort(dependencies: Dict[T, List[T]]) -> List[T]:
        """
        Perform a topological sort on the dependencies graph.

        Args:
            dependencies: A dictionary representing the dependency graph where each key 
                         is a node and the value is a list of nodes it depends on.

        Returns:
            A list of nodes in topologically sorted order.

        Raises:
            WorkflowError: If there is a cycle in the dependencies.
        """
        # Validate input
        if not isinstance(dependencies, dict):
            raise ValidationError(
                message="Dependencies must be a dictionary",
                error_code="INVALID_DEPENDENCIES",
                details={"actual_type": type(dependencies).__name__}
            )
            
        # Calculate in-degrees
        in_degree = {node: 0 for node in dependencies}
        for node, dependent_nodes in dependencies.items():
            for dependent_node in dependent_nodes:
                if dependent_node not in in_degree:
                    raise WorkflowError(
                        message=f"Dependent node {dependent_node} not found in dependency graph",
                        error_code="UNKNOWN_DEPENDENCY",
                        workflow_name="topological_sort"
                    )
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
            raise WorkflowError(
                message="Cyclic dependency detected in the workflow",
                error_code="CYCLIC_DEPENDENCY",
                workflow_name="topological_sort",
                details={"cycle_nodes": list(cycle_nodes)}
            )

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
            
        Raises:
            DirectoryError: If the directory cannot be created
        """
        def _create_directory():
            os.makedirs(path, exist_ok=True)
            return path
            
        return try_operation(
            _create_directory,
            f"Failed to create directory: {path}",
            DirectoryError,
            directory=path
        )