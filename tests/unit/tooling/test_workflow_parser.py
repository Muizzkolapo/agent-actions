"""I-6: Coverage of WorkflowParser.parse_workflow() — happy path and None on malformed input."""

import pytest
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

    @pytest.mark.parametrize(
        "content",
        ["key: {not: valid: yaml: [", "", "   \n\n  \n", "- item1\n- item2\n"],
        ids=["invalid-yaml", "empty", "whitespace", "non-mapping"],
    )
    def test_unusable_content_returns_none(self, tmp_path, content):
        yml = tmp_path / "workflow.yml"
        yml.write_text(content)
        result = WorkflowParser.parse_workflow(str(yml))
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = WorkflowParser.parse_workflow(str(tmp_path / "nonexistent.yml"))
        assert result is None
