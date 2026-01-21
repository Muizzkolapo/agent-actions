import unittest
import logging
from unittest.mock import MagicMock, patch
from agent_actions.prompt.context.scope import ContextScopeProcessor

# Configure logging to see the debug info
logging.basicConfig(level=logging.INFO)


class TestContextScopeLogic(unittest.TestCase):
    def setUp(self):
        self.agent_name = "test_agent"
        self.agent_config = {}

    def test_flat_source_merging(self):
        """Test if flat source item is merged into root field_context."""
        contents = {"existing_key": "valid"}
        source_item = {"title": "Effective Java", "isbn": "9780134685991", "source_guid": "123"}

        # Mock ContextScopeProcessor behavior by calling it with source_content fallback
        # (This bypasses SourceDataLoader but exercises the EXACT SAME merging logic strings 314-328)

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents,
            agent_name=self.agent_name,
            agent_config=self.agent_config,
            source_content=source_item,  # Passing directly as fallback triggers same logic
        )

        print(f"\n[Flat Test] Keys: {list(field_context.keys())}")
        self.assertIn("title", field_context)
        self.assertEqual(field_context["title"], "Effective Java")
        self.assertIn("source", field_context)

    def test_wrapped_source_merging(self):
        """Test if wrapped source content is unwrapped into root."""
        contents = {"existing_key": "valid"}
        source_item = {"content": {"title": "Effective Java", "isbn": "123"}, "source_guid": "123"}

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents,
            agent_name=self.agent_name,
            agent_config=self.agent_config,
            source_content=source_item,
        )

        print(f"\n[Wrapped Test] Keys: {list(field_context.keys())}")
        self.assertIn("title", field_context)
        self.assertEqual(field_context["title"], "Effective Java")

    @patch("agent_actions.input_loading.loaders.source_data.SourceDataLoader")
    @patch("agent_actions.state_management.path_manager.PathManager")
    def test_source_loader_integration(self, mock_pm, mock_loader_cls):
        """Test full integration with SourceDataLoader logic (lines 250-312)."""
        contents = {"bisac_valid": True}
        current_item = {"source_guid": "guid_123"}
        file_path = "/path/to/file.json"

        # Setup mock loader
        mock_loader_instance = mock_loader_cls.return_value
        # Source data returned by loader (flat list of items)
        mock_loader_instance.load_source_data.return_value = [
            {"title": "Real Source Title", "source_guid": "guid_123", "isbn": "111"}
        ]

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents,
            agent_name=self.agent_name,
            agent_config=self.agent_config,
            current_item=current_item,
            file_path=file_path,
        )

        print(f"\n[Loader Test] Keys: {list(field_context.keys())}")
        self.assertIn("title", field_context)
        self.assertEqual(field_context["title"], "Real Source Title")
        self.assertIn("source", field_context)


if __name__ == "__main__":
    unittest.main()
