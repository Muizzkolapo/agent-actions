"""
Tests for the context_scope_normalizer module.

Verifies that:
1. List directives (observe, passthrough, drop, drops) have loop references expanded
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
        """Verify that list directives have expand_versions=True."""
        assert DIRECTIVE_REGISTRY["observe"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["observe"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["passthrough"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["passthrough"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["drop"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["drop"]["expand_versions"] is True

        assert DIRECTIVE_REGISTRY["drops"]["type"] == "list"
        assert DIRECTIVE_REGISTRY["drops"]["expand_versions"] is True

    def test_dict_directives_are_not_expanded(self):
        """Verify that dict directives like seed_path have expand_versions=False."""
        assert DIRECTIVE_REGISTRY["seed_path"]["type"] == "dict"
        assert DIRECTIVE_REGISTRY["seed_path"]["expand_versions"] is False


class TestNormalizeContextScope:
    """Test the normalize_context_scope function."""

    def test_expands_loop_references_in_observe(self):
        """Test that wildcard loop references in observe are expanded."""
        context_scope = {"observe": ["loop_action.*"]}
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        assert result["observe"] == ["loop_action_"]

    def test_preserves_seed_path_dict(self):
        """Test that seed_path dict directive is preserved as-is."""
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
        """Test normalization with both list and dict directives."""
        context_scope = {
            "seed_path": {"exam_syllabus": "syllabus.json"},
            "observe": ["loop_action.*", "other_action.field1"],
            "passthrough": ["loop_action.*"],
            "drop": ["unwanted_field"],
        }
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        # seed_path preserved
        assert result["seed_path"] == {"exam_syllabus": "syllabus.json"}
        # List directives expanded
        assert result["observe"] == ["loop_action_", "other_action.field1"]
        assert result["passthrough"] == ["loop_action_"]
        # drop without loop ref unchanged
        assert result["drop"] == ["unwanted_field"]

    def test_handles_none_context_scope(self):
        """Test that None context_scope returns None."""
        result = normalize_context_scope(None, {})
        assert result is None

    def test_handles_empty_context_scope(self):
        """Test that empty context_scope returns empty dict."""
        result = normalize_context_scope({}, {})
        assert result == {}

    def test_preserves_specific_field_references(self):
        """Test that specific field references are not converted to patterns."""
        context_scope = {"observe": ["loop_action.specific_field"]}
        version_base_map = {"loop_action": ["loop_action_1", "loop_action_2"]}

        result = normalize_context_scope(context_scope, version_base_map)

        # Specific field references kept as-is
        assert result["observe"] == ["loop_action.specific_field"]

    def test_handles_unknown_directives(self):
        """Test that unknown directives are preserved as-is."""
        context_scope = {"unknown_directive": {"foo": "bar"}}
        version_base_map = {"loop_action": ["loop_action_1"]}

        result = normalize_context_scope(context_scope, version_base_map)

        # Unknown directive preserved
        assert result["unknown_directive"] == {"foo": "bar"}


class TestExpandListDirective:
    """Test the _expand_list_directive helper function."""

    def test_expands_wildcard_to_field_prefix(self):
        """Test wildcard expansion to field prefix pattern."""
        field_refs = ["action.*"]
        version_base_map = {"action": ["action_1", "action_2"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["action_"]

    def test_preserves_non_loop_references(self):
        """Test that non-loop references are preserved."""
        field_refs = ["regular_action.*"]
        version_base_map = {"loop_action": ["loop_action_1"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["regular_action.*"]

    def test_handles_mixed_references(self):
        """Test mix of loop and non-loop references."""
        field_refs = ["loop.*", "regular.field", "plain_field"]
        version_base_map = {"loop": ["loop_1", "loop_2"]}

        result = _expand_list_directive(field_refs, version_base_map)

        assert result == ["loop_", "regular.field", "plain_field"]


class TestBuildLoopBaseNameMap:
    """Test the _build_version_base_name_map helper function."""

    def test_builds_map_from_loop_agents(self):
        """Test building loop base name map from agent configs."""
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
        execution_order = ["action_1", "action_2", "regular"]

        result = _build_version_base_name_map(agent_configs, execution_order)

        assert result == {"action": ["action_1", "action_2"]}

    def test_handles_multiple_loop_groups(self):
        """Test with multiple distinct loop groups."""
        agent_configs = {
            "loop_a_1": {"is_versioned_agent": True, "version_base_name": "loop_a"},
            "loop_a_2": {"is_versioned_agent": True, "version_base_name": "loop_a"},
            "loop_b_1": {"is_versioned_agent": True, "version_base_name": "loop_b"},
        }
        execution_order = ["loop_a_1", "loop_a_2", "loop_b_1"]

        result = _build_version_base_name_map(agent_configs, execution_order)

        assert result == {"loop_a": ["loop_a_1", "loop_a_2"], "loop_b": ["loop_b_1"]}


class TestNormalizeAllAgentConfigs:
    """Test the normalize_all_agent_configs function."""

    def test_normalizes_context_scope_in_place(self):
        """Test that context_scope is normalized in-place (no separate expanded key)."""
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
        execution_order = ["loop_1", "consumer"]

        normalize_all_agent_configs(agent_configs, execution_order)

        # context_scope should be overwritten with expanded form
        assert agent_configs["consumer"]["context_scope"] == {
            "observe": ["loop_"],  # Expanded
            "seed_path": {"key": "value.json"},  # Preserved
        }

        # No separate expanded key
        assert "context_scope_expanded" not in agent_configs["consumer"]

    def test_skips_agents_without_context_scope(self):
        """Test that agents without context_scope are skipped."""
        agent_configs = {"action_a": {}, "action_b": {"dependencies": ["action_a"]}}
        execution_order = ["action_a", "action_b"]

        normalize_all_agent_configs(agent_configs, execution_order)

        assert "context_scope" not in agent_configs["action_a"]
        assert "context_scope" not in agent_configs["action_b"]

    def test_does_not_mutate_original_list(self):
        """Test that the original list object passed in is not mutated."""
        original_observe = ["loop.*"]
        agent_configs = {
            "loop_1": {"is_versioned_agent": True, "version_base_name": "loop"},
            "consumer": {"context_scope": {"observe": original_observe}},
        }
        execution_order = ["loop_1", "consumer"]

        normalize_all_agent_configs(agent_configs, execution_order)

        # The original list object should not be mutated (normalizer creates a new list)
        assert original_observe == ["loop.*"]
        # context_scope should have the expanded form
        assert agent_configs["consumer"]["context_scope"]["observe"] == ["loop_"]


class TestSeedPathPreservation:
    """Test that seed_path is correctly preserved during normalization.

    Ensures seed_path from defaults is not destroyed when actions define
    their own context_scope.
    """

    def test_seed_path_not_destroyed_by_loop_expansion(self):
        """Verify seed_path survives when context_scope has loop references."""
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
        execution_order = ["extract_1", "extract_2", "consumer"]

        normalize_all_agent_configs(agent_configs, execution_order)

        # seed_path must survive in normalized context_scope
        assert agent_configs["consumer"]["context_scope"]["seed_path"] == {
            "exam_syllabus": "syllabus.json",
            "grading_rubric": "rubric.json",
        }

        # observe should be expanded in-place
        assert agent_configs["consumer"]["context_scope"]["observe"] == ["extract_"]
