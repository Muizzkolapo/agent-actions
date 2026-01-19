"""
Tests for context_scope expansion at orchestration level.

Verifies that loop base name references in context_scope are expanded
to field prefix patterns during execution level computation.
"""

import pytest
from agent_actions.orchestration.action_level_executor import ActionLevelOrchestrator


class TestContextScopeExpansion:
    """Test context_scope expansion for loop references."""

    def test_wildcard_loop_reference_expands_to_field_prefix_pattern(self):
        """Test that wildcard references to loop base names become field prefix patterns."""
        # Setup: Loop action extract_raw_qa with 3 iterations
        # Consumer action flatten_questions depends on loop and references it in context_scope
        execution_order = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]

        agent_configs = {
            "extract_raw_qa_1": {
                "is_loop_agent": True,
                "loop_base_name": "extract_raw_qa",
                "loop_iteration": 1,
            },
            "extract_raw_qa_2": {
                "is_loop_agent": True,
                "loop_base_name": "extract_raw_qa",
                "loop_iteration": 2,
            },
            "extract_raw_qa_3": {
                "is_loop_agent": True,
                "loop_base_name": "extract_raw_qa",
                "loop_iteration": 3,
            },
            "flatten_questions": {
                "dependencies": ["extract_raw_qa"],  # Will be expanded to loop variants
                "context_scope": {
                    "observe": ["extract_raw_qa.*"]  # Should expand to "extract_raw_qa_"
                },
            },
        }

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)

        # Act: Compute execution levels (triggers expansion)
        levels = orchestrator.compute_execution_levels()

        # Assert: Dependencies should be expanded to loop variants
        assert agent_configs["flatten_questions"]["dependencies"] == [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
        ]

        # Assert: Context scope should have field prefix pattern
        assert agent_configs["flatten_questions"]["context_scope"] == {
            "observe": ["extract_raw_qa_"]  # Field prefix pattern
        }

        # Assert: Execution levels should be correct
        assert len(levels) == 2
        assert set(levels[0]) == {"extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"}
        assert levels[1] == ["flatten_questions"]

    def test_specific_field_loop_reference_not_expanded(self):
        """Test that specific field references to loop base names are kept as-is."""
        execution_order = ["loop_action_1", "loop_action_2", "consumer"]

        agent_configs = {
            "loop_action_1": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 1,
            },
            "loop_action_2": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 2,
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

    def test_non_loop_references_unchanged(self):
        """Test that non-loop references in context_scope are unchanged."""
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

        # Non-loop references should remain unchanged
        assert agent_configs["action_C"]["context_scope"] == {
            "observe": ["action_A.*", "action_B.field1"]
        }

    def test_mixed_loop_and_regular_references(self):
        """Test context_scope with both loop and regular action references."""
        execution_order = [
            "loop_action_1",
            "loop_action_2",
            "regular_action",
            "consumer",
        ]

        agent_configs = {
            "loop_action_1": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 1,
            },
            "loop_action_2": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 2,
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

        orchestrator = ActionLevelOrchestrator(execution_order, agent_configs)
        orchestrator.compute_execution_levels()

        # Loop reference should expand, regular references unchanged
        expected_context_scope = {
            "observe": ["loop_action_", "regular_action.field1"],
            "passthrough": ["regular_action.field2"],
        }
        assert agent_configs["consumer"]["context_scope"] == expected_context_scope

    def test_no_context_scope_no_expansion(self):
        """Test that actions without context_scope are not affected."""
        execution_order = ["loop_action_1", "loop_action_2", "consumer"]

        agent_configs = {
            "loop_action_1": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 1,
            },
            "loop_action_2": {
                "is_loop_agent": True,
                "loop_base_name": "loop_action",
                "loop_iteration": 2,
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
