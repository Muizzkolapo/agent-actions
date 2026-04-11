"""Tests for infer_dependencies handling of cross-workflow dict dependencies."""

from __future__ import annotations

from agent_actions.prompt.context.scope_inference import infer_dependencies


class TestInferDependenciesCrossWorkflow:
    """infer_dependencies filters out cross-workflow dict deps from raw configs."""

    def test_dict_deps_filtered_from_input_sources(self):
        config = {
            "dependencies": [
                "local_action",
                {"workflow": "upstream", "action": "remote"},
            ],
        }
        input_sources, context_sources = infer_dependencies(
            config, ["local_action"], "test_action"
        )
        assert input_sources == ["local_action"]
        assert context_sources == []

    def test_all_dict_deps_produces_empty_sources(self):
        config = {
            "dependencies": [{"workflow": "upstream"}],
        }
        input_sources, context_sources = infer_dependencies(config, [], "test_action")
        assert input_sources == []
        assert context_sources == []

    def test_string_only_deps_unchanged(self):
        config = {
            "dependencies": ["action_a"],
        }
        input_sources, context_sources = infer_dependencies(
            config, ["action_a"], "test_action"
        )
        assert input_sources == ["action_a"]

    def test_no_deps_unchanged(self):
        config = {}
        input_sources, context_sources = infer_dependencies(config, [], "test_action")
        assert input_sources == []
        assert context_sources == []
