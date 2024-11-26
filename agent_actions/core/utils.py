"""
Module containing utility classes and functions for data aggregation, transformation, file operations, and string processing.
"""

import uuid
from collections import deque

class Utils:
    """
    A class containing miscellaneous utility functions.
    """

    @staticmethod
    def generate_id():
        """
        Generate a unique identifier.

        Returns:
            str: A UUID4 unique identifier as a string.
        """
        return str(uuid.uuid4())

    @staticmethod
    def topological_sort(dependencies):
        """
        Perform a topological sort on the dependencies graph.
        Only includes active agents in the sort.
        
        Args:
            dependencies (dict): Dictionary of dependencies for active agents
            
        Returns:
            list: Sorted list of agent types in execution order
            
        Raises:
            ValueError: If a cycle is detected in dependencies
        """
        from collections import deque

        # Calculate in-degrees
        in_degree = {node: 0 for node in dependencies}
        for deps in dependencies.values():
            for dep in deps:
                in_degree[dep] = in_degree.get(dep, 0) + 1

        # Find nodes with no dependencies
        queue = deque([node for node, degree in in_degree.items() if degree == 0])
        sorted_nodes = []

        while queue:
            node = queue.popleft()
            sorted_nodes.append(node)
            
            for dep in dependencies.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(sorted_nodes) != len(dependencies):
            raise ValueError("Cycle detected in agent dependencies")

        return sorted_nodes
