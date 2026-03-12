"""CLI integration tests for the inspect commands."""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli


@pytest.fixture
def cli_runner():
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()


class TestInspectDependenciesCommand:
    """Tests for the inspect dependencies CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "dependencies", "--help"])

        assert result.exit_code == 0
        assert "Analyze workflow dependencies" in result.output
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_dependencies_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "dependencies"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestInspectGraphCommand:
    """Tests for the inspect graph CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "graph", "--help"])

        assert result.exit_code == 0
        assert "dependency graph" in result.output.lower()
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_graph_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "graph"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestInspectActionCommand:
    """Tests for the inspect action CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "action", "--help"])

        assert result.exit_code == 0
        assert "details for a specific action" in result.output.lower()
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_action_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "action", "test_action"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_action_requires_action_name(self, cli_runner):
        """Test that action name argument is required."""
        result = cli_runner.invoke(cli, ["inspect", "action", "-a", "test_workflow"])

        assert result.exit_code != 0
        assert "Missing argument" in result.output or "required" in result.output.lower()


class TestInspectCommandGroup:
    """Tests for the inspect command group structure."""

    def test_inspect_is_a_group(self, cli_runner):
        """Test that inspect is a command group."""
        result = cli_runner.invoke(cli, ["inspect"])

        # Should show usage/help for the group
        assert result.exit_code == 0 or "Usage:" in result.output

    def test_inspect_group_help(self, cli_runner):
        """Test that inspect group help is displayed."""
        result = cli_runner.invoke(cli, ["inspect", "--help"])

        assert result.exit_code == 0
        assert "dependencies" in result.output
        assert "graph" in result.output
        assert "action" in result.output
        assert "Inspect workflow structure" in result.output


class TestBaseInspectCommandHelpers:
    """Unit tests for BaseInspectCommand helper methods."""

    def test_get_action_type_source(self):
        """Test action type for source actions (no inputs)."""
        from agent_actions.cli.inspect import BaseInspectCommand

        assert BaseInspectCommand._get_action_type([], []) == "Source"

    def test_get_action_type_transform(self):
        """Test action type for single-input transform."""
        from agent_actions.cli.inspect import BaseInspectCommand

        assert BaseInspectCommand._get_action_type(["a"], []) == "Transform"

    def test_get_action_type_transform_with_context(self):
        """Test action type for transform with context."""
        from agent_actions.cli.inspect import BaseInspectCommand

        assert BaseInspectCommand._get_action_type(["a"], ["b"]) == "Transform + Context"

    def test_get_action_type_merge(self):
        """Test action type for merge (multiple inputs)."""
        from agent_actions.cli.inspect import BaseInspectCommand

        assert BaseInspectCommand._get_action_type(["a", "b"], []) == "Merge"

    def test_get_action_type_merge_with_context(self):
        """Test action type for merge with context."""
        from agent_actions.cli.inspect import BaseInspectCommand

        assert BaseInspectCommand._get_action_type(["a", "b"], ["c"]) == "Merge + Context"

    def test_get_output_fields_inline_schema(self):
        """Test extracting fields from inline schema."""
        from agent_actions.cli.inspect import BaseInspectCommand

        config = {"schema": {"field1": "string", "field2": "int"}}
        fields = BaseInspectCommand._get_output_fields(config)
        assert set(fields) == {"field1", "field2"}

    def test_get_output_fields_properties_schema(self):
        """Test extracting fields from JSON Schema format."""
        from agent_actions.cli.inspect import BaseInspectCommand

        config = {"schema": {"properties": {"name": {}, "value": {}}}}
        fields = BaseInspectCommand._get_output_fields(config)
        assert set(fields) == {"name", "value"}

    def test_get_output_fields_no_schema(self):
        """Test empty result when no schema defined."""
        from agent_actions.cli.inspect import BaseInspectCommand

        config = {}
        fields = BaseInspectCommand._get_output_fields(config)
        assert fields == []

    def test_get_input_fields_from_context_scope(self):
        """Test extracting input fields from context_scope."""
        from agent_actions.cli.inspect import BaseInspectCommand

        config = {
            "context_scope": {
                "observe": ["action1.field1", "action2.*"],
                "passthrough": ["action3.data"],
            }
        }
        fields = BaseInspectCommand._get_input_fields(config)
        assert "action1.field1 (observe)" in fields
        assert "action2.* (observe)" in fields
        assert "action3.data (passthrough)" in fields
