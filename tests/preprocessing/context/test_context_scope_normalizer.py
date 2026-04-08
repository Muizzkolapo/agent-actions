"""
Tests for the context_scope_normalizer module.

Verifies that:
1. List directives (observe, passthrough, drop, drops) have version base name
   references expanded to concrete versioned references
2. Dict directives (seed_path) are preserved as-is (never expanded)
3. normalize_all_agent_configs normalizes context_scope in-place
"""

from agent_actions.input.context.normalizer import (
    DIRECTIVE_REGISTRY,
    _build_version_base_name_map,
    _expand_list_directive,
    normalize_all_agent_configs,
    normalize_context_scope,
)


class TestDirectiveRegistry:
    """Test the directive registry configuration."""

    def test_list_directives_are_marked_for_expansion(self):
        assert DIRECTIVE_REGISTRY["observe"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["observe"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["passthrough"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["passthrough"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["drop"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["drop"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["drops"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["drops"]["expand_versions"] is True

    def test_dict_directives_are_not_expanded(self):
        assert DIRECTIVE_REGISTRY["seed_path"]["type"] == "dict"
        assert DIRECTIVE_REGISTRY["seed_path"]["expand_versions"] is False


class TestNormalizeContextScope:
    """Test the normalize_context_scope function."""

    def test_expands_wildcard_to_concrete_versioned_refs(self):
        context_scope = {"observe": ["loop_action.*"]}
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["observe"] == ["loop_action_1.*", "loop_action_2.*"]

    def test_expands_specific_field_to_concrete_versioned_refs(self):
        context_scope = {"observe": ["loop_action.score"]}
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["observe"] == ["loop_action_1.score", "loop_action_2.score"]

    def test_preserves_seed_path_dict(self):
        context_scope = {
            "seed_path": {"exam_syllabus": "syllabus.json", "grading_rubric": "rubric.json"}
        }
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["seed_path"] == {
            "exam_syllabus": "syllabus.json",
            "grading_rubric": "rubric.json",
        }

    def test_handles_mixed_directives(self):
        context_scope = {
            "seed_path": {"exam_syllabus": "syllabus.json"},
            "observe": ["loop_action.*", "other_action.field1"],
            "passthrough": ["loop_action.*"],
            "drop": ["unwanted_field"],
        }
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["seed_path"] == {"exam_syllabus": "syllabus.json"}
        assert result["observe"] == [
            "loop_action_1.*",
            "loop_action_2.*",
            "other_action.field1",
        ]
        assert result["passthrough"] == ["loop_action_1.*", "loop_action_2.*"]
        assert result["drop"] == ["unwanted_field"]

    def test_handles_none_context_scope(self):
        result = normalize_context_scope(None, {})
        assert result == {}

    def test_handles_empty_context_scope(self):
        result = normalize_context_scope({}, {})
        assert result == {}

    def test_preserves_non_versioned_references(self):
        context_scope = {"observe": ["regular_action.field1"]}
        version_base_map = {"loop_action": ["loop_action_1"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["observe"] == ["regular_action.field1"]

    def test_handles_unknown_directives(self):
        context_scope = {"unknown_directive": {"foo": "bar"}}
        version_base_map = {"loop_action": ["loop_action_1"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["unknown_directive"] == {"foo": "bar"}


class TestExpandListDirective:
    """Test the _expand_list_directive helper function."""

    def test_expands_wildcard_to_concrete_refs(self):
        field_refs = ["action.*"]
        version_base_map = {"action": ["action_1", "action_2"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["action_1.*", "action_2.*"]

    def test_expands_specific_field_to_concrete_refs(self):
        field_refs = ["action.score"]
        version_base_map = {"action": ["action_1", "action_2"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["action_1.score", "action_2.score"]

    def test_preserves_non_versioned_references(self):
        field_refs = ["regular_action.*"]
        version_base_map = {"loop_action": ["loop_action_1"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["regular_action.*"]

    def test_handles_mixed_references(self):
        field_refs = ["loop.*", "regular.field", "plain_field"]
        version_base_map = {"loop": ["loop_1", "loop_2"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["loop_1.*", "loop_2.*", "regular.field", "plain_field"]


class TestBuildVersionBaseNameMap:
    """Test the _build_version_base_name_map helper function."""

    def test_builds_map_from_versioned_agents(self):
        agent_configs = {
            "action_1": {
                "is_versioned_agent": True,
                "version_base_name": "action",
                "version_number": 1,
            },
            "action_2": {
                "is_versioned_agent": True,
                "version_base_name": "action",
                "version_number": 2,
            },
            "regular": {},
        }

        result = _build_version_base_name_map(agent_configs)

        assert result == {"action": ["action_1", "action_2"]}

    def test_handles_multiple_version_groups(self):
        agent_configs = {
            "loop_a_1": {"is_versioned_agent": True, "version_base_name": "loop_a"},
            "loop_a_2": {"is_versioned_agent": True, "version_base_name": "loop_a"},
            "loop_b_1": {"is_versioned_agent": True, "version_base_name": "loop_b"},
        }

        result = _build_version_base_name_map(agent_configs)

        assert result == {"loop_a": ["loop_a_1", "loop_a_2"], "loop_b": ["loop_b_1"]}


class TestNormalizeAllAgentConfigs:
    """Test the normalize_all_agent_configs function."""

    def test_normalizes_context_scope_in_place(self):
        agent_configs = {
            "loop_1": {
                "is_versioned_agent": True,
                "version_base_name": "loop",
                "version_number": 1,
            },
            "consumer": {
                "context_scope": {"observe": ["loop.*"], "seed_path": {"key": "value.json"}}
            },
        }

        normalize_all_agent_configs(agent_configs)

        assert agent_configs["consumer"]["context_scope"] == {
            "observe": ["loop_1.*"],
            "seed_path": {"key": "value.json"},
        }
        assert "context_scope_expanded" not in agent_configs["consumer"]

    def test_normalizes_agents_without_context_scope_to_empty_dict(self):
        agent_configs = {"action_a": {}, "action_b": {"dependencies": ["action_a"]}}

        normalize_all_agent_configs(agent_configs)

        assert agent_configs["action_a"]["context_scope"] == {}
        assert agent_configs["action_b"]["context_scope"] == {}

    def test_does_not_mutate_original_list(self):
        original_observe = ["loop.*"]
        agent_configs = {
            "loop_1": {"is_versioned_agent": True, "version_base_name": "loop"},
            "consumer": {"context_scope": {"observe": original_observe}},
        }

        normalize_all_agent_configs(agent_configs)

        assert original_observe == ["loop.*"]
        assert agent_configs["consumer"]["context_scope"]["observe"] == ["loop_1.*"]


class TestSeedPathPreservation:
    def test_seed_path_not_destroyed_by_version_expansion(self):
        agent_configs = {
            "extract_1": {
                "is_versioned_agent": True,
                "version_base_name": "extract",
                "version_number": 1,
            },
            "extract_2": {
                "is_versioned_agent": True,
                "version_base_name": "extract",
                "version_number": 2,
            },
            "consumer": {
                "context_scope": {
                    "seed_path": {
                        "exam_syllabus": "syllabus.json",
                        "grading_rubric": "rubric.json",
                    },
                    "observe": ["extract.*"],
                }
            },
        }

        normalize_all_agent_configs(agent_configs)

        assert agent_configs["consumer"]["context_scope"]["seed_path"] == {
            "exam_syllabus": "syllabus.json",
            "grading_rubric": "rubric.json",
        }
        assert agent_configs["consumer"]["context_scope"]["observe"] == [
            "extract_1.*",
            "extract_2.*",
        ]
