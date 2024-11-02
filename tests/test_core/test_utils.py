import unittest
from unittest.mock import patch
from agent_actions.core.utils import Utils

class TestUtils(unittest.TestCase):

    @patch('agent_actions.utils.logger')
    def test_generate_id(self, mock_logger):
        unique_id = Utils.generate_id()
        self.assertTrue(isinstance(unique_id, str))
        self.assertEqual(len(unique_id), 36)  # UUID4 string length
        mock_logger.info.assert_called_once_with(f"Generated unique ID: {unique_id}")

    @patch('agent_actions.utils.logger')
    def test_topological_sort_success(self, mock_logger):
        dependencies = {
            'A': ['B', 'C'],
            'B': ['D'],
            'C': ['D'],
            'D': []
        }
        sorted_nodes = Utils.topological_sort(dependencies)
        self.assertEqual(sorted_nodes, ['D', 'B', 'C', 'A'])

        # Check for the presence of logging calls
        mock_logger.info.assert_any_call("Starting topological sort")
        mock_logger.info.assert_any_call("Topological sort completed successfully")
        mock_logger.debug.assert_called_with(f"Topologically sorted order: {sorted_nodes[::-1]}")

    @patch('agent_actions.utils.logger')
    def test_topological_sort_with_cycle(self, mock_logger):
        dependencies = {
            'A': ['B'],
            'B': ['C'],
            'C': ['A']
        }
        with self.assertRaises(ValueError):
            Utils.topological_sort(dependencies)
        
        mock_logger.error.assert_called_once_with("Cycle detected in dependencies graph")

    @patch('agent_actions.utils.logger')
    def test_topological_sort_logging(self, mock_logger):
        # Test the logging behavior for a simple dependency graph
        dependencies = {
            'X': ['Y'],
            'Y': []
        }
        Utils.topological_sort(dependencies)

        mock_logger.debug.assert_any_call("Dependencies graph: {'X': ['Y'], 'Y': []}")
        mock_logger.debug.assert_any_call("Initial in-degrees: {'X': 0, 'Y': 1}")
        mock_logger.info.assert_any_call("Nodes with no dependencies (starting points): ['X']")
        mock_logger.debug.assert_any_call("Processing node: X")
        mock_logger.debug.assert_any_call("Decremented in-degree of node Y: now 0")
        mock_logger.debug.assert_any_call("Node Y has no remaining dependencies, added to queue")

if __name__ == '__main__':
    unittest.main()
