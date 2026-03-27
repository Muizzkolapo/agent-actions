"""Tests for shared tools_resolver utility."""

from unittest.mock import patch

from agent_actions.utils.tools_resolver import resolve_tools_path


class TestToolsResolver:
    """Test resolve_tools_path() shared utility."""

    def test_legacy_format_list(self, tmp_path):
        """Test legacy tool_path format with list."""
        agent_config = {"tool_path": [str(tmp_path), "/other/path"], "prompt": "Test prompt"}

        resolved = resolve_tools_path(agent_config)
        assert resolved == str(tmp_path), f"Expected first path from list, got {resolved}"

    def test_legacy_format_string(self, tmp_path):
        """Test legacy tool_path format with string."""
        agent_config = {"tool_path": str(tmp_path), "prompt": "Test prompt"}

        resolved = resolve_tools_path(agent_config)
        assert resolved == str(tmp_path), f"Expected tool_path string, got {resolved}"

    def test_simple_format(self, tmp_path):
        """Test simple tools.path format."""
        agent_config = {"tools": {"path": str(tmp_path)}, "prompt": "Test prompt"}

        resolved = resolve_tools_path(agent_config)
        assert resolved == str(tmp_path), f"Expected tools.path value, got {resolved}"

    def test_openai_format(self, tmp_path):
        """Test OpenAI tool calling format."""
        # Create tool config file
        tool_config_path = tmp_path / "tool_config.yaml"
        tool_config_path.write_text(f"module_path: {tmp_path}")

        agent_config = {
            "tools": [{"type": "function", "function": {"file": str(tool_config_path)}}],
            "prompt": "Test prompt",
        }

        with patch(
            "agent_actions.utils.tools_resolver.find_project_root",
            return_value=tmp_path,
        ):
            resolved = resolve_tools_path(agent_config)
        assert resolved == str(tmp_path), f"Expected module_path from tool config, got {resolved}"

    def test_no_tools_configured(self):
        """Test that missing tools returns None."""
        agent_config = {"prompt": "Test prompt", "model_vendor": "openai"}

        resolved = resolve_tools_path(agent_config)
        assert resolved is None, f"Expected None when no tools configured, got {resolved}"

    def test_priority_order(self, tmp_path):
        """Test that tool_path takes priority over tools."""
        agent_config = {
            "tool_path": str(tmp_path / "priority"),
            "tools": {"path": str(tmp_path / "secondary")},
        }

        resolved = resolve_tools_path(agent_config)
        assert resolved == str(tmp_path / "priority"), (
            f"Expected tool_path to take priority, got {resolved}"
        )

    def test_empty_tool_path_list(self):
        """Test empty tool_path list returns None."""
        agent_config = {"tool_path": [], "prompt": "Test prompt"}

        resolved = resolve_tools_path(agent_config)
        assert resolved is None, f"Expected None for empty list, got {resolved}"
