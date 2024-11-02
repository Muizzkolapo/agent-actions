"""
Module containing utility classes and functions for data aggregation, transformation, file operations, and string processing.
"""

import uuid
from collections import deque
from agent_actions.logging_setup import setup_logging

# Initialize logger
logger = setup_logging()

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
        unique_id = str(uuid.uuid4())
        logger.info(f"Generated unique ID: {unique_id}")
        return unique_id

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
        logger.info("Starting topological sort")
        logger.debug(f"Dependencies graph: {dependencies}")

        # Calculate in-degrees
        in_degree = {node: 0 for node in dependencies}
        for node, dependent_nodes in dependencies.items():
            for dependent_node in dependent_nodes:
                in_degree[dependent_node] += 1

        logger.debug(f"Initial in-degrees: {in_degree}")

        # Initialize queue with nodes having zero in-degree
        queue = deque([node for node in in_degree if in_degree[node] == 0])
        sorted_nodes = []

        logger.info(f"Nodes with no dependencies (starting points): {list(queue)}")

        while queue:
            current_node = queue.popleft()
            sorted_nodes.append(current_node)
            logger.debug(f"Processing node: {current_node}")

            for neighbor in dependencies[current_node]:
                in_degree[neighbor] -= 1
                logger.debug(f"Decremented in-degree of node {neighbor}: now {in_degree[neighbor]}")
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    logger.debug(f"Node {neighbor} has no remaining dependencies, added to queue")

        # Check for cycles
        if len(sorted_nodes) != len(dependencies):
            logger.error("Cycle detected in dependencies graph")
            raise ValueError("There is a cycle in the dependencies")

        logger.info("Topological sort completed successfully")
        logger.debug(f"Topologically sorted order: {sorted_nodes[::-1]}")

        return sorted_nodes[::-1]
