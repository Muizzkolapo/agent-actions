"""
Tests for context_scope expansion at orchestration level.

Note: As of the context scope normalization RFC, context_scope expansion
now happens at config load time via context_scope_normalizer.py (called by
ConfigManager.determine_execution_order()). The ActionLevelOrchestrator
no longer mutates context_scope - it stays raw while context_scope_expanded
contains the version-expanded version.

These tests verify that:
1. context_scope is preserved as raw (not mutated) in ActionLevelOrchestrator
2. Dependencies are still expanded to version variants
3. The normalizer properly creates context_scope_expanded
"""

import pytest
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator
from agent_actions.input.context.normalizer import (
    normalize_context_scope,
    normalize_all_agent_configs,
    _build_version_base_name_map,
)


class TestContextScopeExpansion:
    """Test context_scope expansion for version references."""

    def test_wildcard_version_reference_expands_to_field_prefix_pattern(self):
        """Test that wildcard references to version base names become field prefix patterns.

        Note: context_scope expansion now happens via normalize_all_agent_configs()
        at config load time. This test verifies both:
        1. ActionLevelOrchestrator preserves raw context_scope
        2. The normalizer creates correct context_scope_expanded
        """
        # Setup: Versioned action extract_raw_qa with 3 iterations
        # Consumer action flatten_questions depends on versions and references it in context_scope
        execution_order = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]

        agent_configs = {
            "extract_raw_qa_1": {
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 1,
            },
            "extract_raw_qa_2": {
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 2,
            },
            "extract_raw_qa_3": {
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "version_number": 3,
            },
            "flatten_questions": {
                "dependencies": ["extract_raw_qa"],  # Will be expanded to version variants
                "context_scope": {
                    "observe": ["extract_raw_qa.*"]  # Raw, not expanded here
                },
            },
        }

        # First, apply normalization (as ConfigManager would do)
        normalize_all_agent_configs(agent_configs, execution_order)

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)

        # Act: Compute execution levels (triggers dependency expansion only)
        levels = orchestrator.compute_execution_levels()

        # Assert: Dependencies should be expanded to version variants
        assert agent_configs["flatten_questions"]["dependencies"] == [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
        ]

        # Assert: Raw context_scope should be preserved
        assert agent_configs["flatten_questions"]["context_scope"] == {
            "observe": ["extract_raw_qa.*"]  # Raw, preserved
        }

        # Assert: context_scope_expanded should have field prefix pattern
        assert agent_configs["flatten_questions"]["context_scope_expanded"] == {
            "observe": ["extract_raw_qa_"]  # Field prefix pattern
        }

        # Assert: Execution levels should be correct
        assert len(levels) == 2
        assert set(levels[0]) == {"extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"}
        assert levels[1] == ["flatten_questions"]

    def test_specific_field_version_reference_not_expanded(self):
        """Test that specific field references to version base names are kept as-is."""
        execution_order = ["loop_action_1", "loop_action_2", "consumer"]

        agent_configs = {
            "loop_action_1": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 1,
            },
            "loop_action_2": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 2,
            },
            "consumer": {
                "dependencies": ["loop_action"],
                "context_scope": {
                    "observe": ["loop_action.specific_field"]  # Specific field, not wildcard
                },
            },
        }

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        orchestrator.compute_execution_levels()

        # Specific field references should be kept as-is (not expanded to field prefix)
        assert agent_configs["consumer"]["context_scope"] == {
            "observe": ["loop_action.specific_field"]
        }

    def test_non_version_references_unchanged(self):
        """Test that non-version references in context_scope are unchanged."""
        execution_order = ["action_A", "action_B", "action_C"]

        agent_configs = {
            "action_A": {},
            "action_B": {"dependencies": ["action_A"]},
            "action_C": {
                "dependencies": ["action_A"],
                "context_scope": {"observe": ["action_A.*", "action_B.field1"]},
            },
        }

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        orchestrator.compute_execution_levels()

        # Non-version references should remain unchanged
        assert agent_configs["action_C"]["context_scope"] == {
            "observe": ["action_A.*", "action_B.field1"]
        }

    def test_mixed_version_and_regular_references(self):
        """Test context_scope with both version and regular action references.

        Note: context_scope expansion now happens via normalize_all_agent_configs().
        Raw context_scope is preserved, expanded version in context_scope_expanded.
        """
        execution_order = [
            "loop_action_1",
            "loop_action_2",
            "regular_action",
            "consumer",
        ]

        agent_configs = {
            "loop_action_1": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 1,
            },
            "loop_action_2": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 2,
            },
            "regular_action": {},
            "consumer": {
                "dependencies": ["loop_action", "regular_action"],
                "context_scope": {
                    "observe": ["loop_action.*", "regular_action.field1"],
                    "passthrough": ["regular_action.field2"],
                },
            },
        }

        # Apply normalization (as ConfigManager would do)
        normalize_all_agent_configs(agent_configs, execution_order)

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        orchestrator.compute_execution_levels()

        # Raw context_scope should be preserved
        assert agent_configs["consumer"]["context_scope"] == {
            "observe": ["loop_action.*", "regular_action.field1"],
            "passthrough": ["regular_action.field2"],
        }

        # Version reference should expand in context_scope_expanded
        expected_expanded = {
            "observe": ["loop_action_", "regular_action.field1"],
            "passthrough": ["regular_action.field2"],
        }
        assert agent_configs["consumer"]["context_scope_expanded"] == expected_expanded

    def test_no_context_scope_no_expansion(self):
        """Test that actions without context_scope are not affected."""
        execution_order = ["loop_action_1", "loop_action_2", "consumer"]

        agent_configs = {
            "loop_action_1": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 1,
            },
            "loop_action_2": {
                "is_versioned_agent": True,
                "version_base_name": "loop_action",
                "version_number": 2,
            },
            "consumer": {
                "dependencies": ["loop_action"]
                # No context_scope
            },
        }

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        orchestrator.compute_execution_levels()

        # Should not add context_scope if it didn't exist
        assert "context_scope" not in agent_configs["consumer"]
