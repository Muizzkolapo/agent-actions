"""
Module containing utility classes and functions for data aggregation, transformation, file operations, and string processing.
"""

import logging
import uuid
from collections import deque
from agent_actions.logging_setup import setup_logging
logger = setup_logging()

# Set up logging
logger = logging.getLogger(__name__)



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

        Parameters:
            dependencies (dict): A dictionary representing the dependency graph where each key is a node and the value is a list of nodes it depends on.

        Returns:
            list: A list of nodes in topologically sorted order.

        Raises:
            ValueError: If there is a cycle in the dependencies.
        """
        in_degree = {node: 0 for node in dependencies}
        for node in dependencies:
            for dependent_node in dependencies[node]:
                in_degree[dependent_node] += 1

        queue = deque([node for node in in_degree if in_degree[node] == 0])
        sorted_nodes = []

        while queue:
            current_node = queue.popleft()
            sorted_nodes.append(current_node)
            for neighbor in dependencies[current_node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) != len(dependencies):
            raise ValueError("There is a cycle in the dependencies")

        return sorted_nodes[::-1]
