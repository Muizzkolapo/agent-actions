"""I-6: Coverage of WorkflowParser.parse_workflow() — happy path and None on malformed input."""

import yaml

from agent_actions.tooling.docs.parser import WorkflowParser


class TestWorkflowParserHappyPath:
    """parse_workflow returns a dict on valid YAML."""

    def test_minimal_workflow(self, tmp_path):
        yml = tmp_path / "workflow.yml"
        yml.write_text("name: test_wf\ndescription: A simple workflow\nactions: []\n")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is not None
        assert isinstance(result, dict)
        assert result["name"] == "test_wf"

    def test_workflow_with_actions(self, tmp_path):
        yml = tmp_path / "workflow.yml"
        content = {
            "name": "wf_with_actions",
            "description": "Has actions",
            "actions": [
                {
                    "name": "step_a",
                    "intent": "Do step A",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3",
                }
            ],
        }
        yml.write_text(yaml.dump(content))
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is not None
        assert "step_a" in result["actions"]

    def test_result_has_expected_top_level_keys(self, tmp_path):
        yml = tmp_path / "workflow.yml"
        yml.write_text("name: wf\nactions: []\n")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is not None
        for key in ("name", "description", "path", "version", "actions", "defaults"):
            assert key in result, f"Missing key: {key}"

    def test_path_stored_in_result(self, tmp_path):
        yml = tmp_path / "workflow.yml"
        yml.write_text("name: wf\nactions: []\n")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is not None
        assert result["path"] == str(yml)


class TestWorkflowParserMalformedInput:
    """parse_workflow returns None on malformed or missing YAML."""

    def test_invalid_yaml_returns_none(self, tmp_path):
        yml = tmp_path / "bad.yml"
        yml.write_text("key: {not: valid: yaml: [")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = WorkflowParser.parse_workflow(str(tmp_path / "nonexistent.yml"))
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        yml = tmp_path / "empty.yml"
        yml.write_text("")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is None

    def test_whitespace_only_file_returns_none(self, tmp_path):
        yml = tmp_path / "blank.yml"
        yml.write_text("   \n\n  \n")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is None

    def test_non_mapping_file_returns_none(self, tmp_path):
        yml = tmp_path / "list.yml"
        yml.write_text("- item1\n- item2\n")
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is None
