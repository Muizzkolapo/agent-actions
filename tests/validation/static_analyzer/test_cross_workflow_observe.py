"""Tests for cross-workflow dependency handling in the static analyzer.

Cross-workflow dependencies use dict syntax: {"workflow": "X", "action": "Y"}.
Pydantic strips these before the static analyzer sees them. The analyzer must
recognize these action names and skip validation — they are resolved at runtime.

Regression tests for: specs/bugs/pending/bug_static_checker_blocks_cross_workflow.md
"""

from agent_actions.validation.static_analyzer import (
    ActionKind,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    OutputSchema,
    StaticTypeChecker,
    analyze_workflow,
)


class TestCrossWorkflowObserve:
    """Cross-workflow observe refs should not raise StaticTypeError."""

    def test_cross_workflow_observe_not_rejected(self):
        """observe ref to cross-workflow dep action should not raise StaticTypeError."""
        workflow_config = {
            "actions": [
                {
                    "name": "local_action",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "dependencies": [
                        "local_action",
                        {"workflow": "other_workflow", "action": "remote_action"},
                    ],
                    "context_scope": {
                        "observe": ["local_action.text", "remote_action.*"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Must not error on the cross-workflow ref
        action_errors = [e for e in result.errors if "remote_action" in e.message]
        assert len(action_errors) == 0, (
            f"Cross-workflow observe ref raised errors: {[e.message for e in action_errors]}"
        )

    def test_typo_in_observe_still_rejected(self):
        """observe ref to non-existent action (not a cross-workflow dep) still raises."""
        workflow_config = {
            "actions": [
                {
                    "name": "extractor",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "dependencies": ["extractor"],
                    "context_scope": {
                        "observe": ["extractor.text", "typo_action.field"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Typo should still be caught
        typo_errors = [e for e in result.errors if "typo_action" in e.message]
        assert len(typo_errors) >= 1, "Typo in observe ref was not caught"

    def test_cross_workflow_passthrough_not_rejected(self):
        """passthrough ref to cross-workflow dep should not raise."""
        workflow_config = {
            "actions": [
                {
                    "name": "consumer",
                    "dependencies": [
                        {"workflow": "other_workflow", "action": "remote_action"},
                    ],
                    "context_scope": {
                        "observe": ["source.*"],
                        "passthrough": ["remote_action.field_x"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        action_errors = [e for e in result.errors if "remote_action" in e.message]
        assert len(action_errors) == 0, (
            f"Cross-workflow passthrough ref raised errors: {[e.message for e in action_errors]}"
        )

    def test_mixed_local_and_cross_workflow_deps(self):
        """action with both local and cross-workflow deps validates correctly."""
        workflow_config = {
            "actions": [
                {
                    "name": "extract",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                },
                {
                    "name": "enrich",
                    "dependencies": [
                        "extract",
                        {"workflow": "external_wf", "action": "lookup"},
                    ],
                    "context_scope": {
                        "observe": [
                            "extract.summary",
                            "extract.score",
                            "lookup.*",
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Local refs validated, cross-workflow refs skipped
        lookup_errors = [e for e in result.errors if "lookup" in e.message]
        assert len(lookup_errors) == 0, (
            f"Cross-workflow ref 'lookup' raised errors: {[e.message for e in lookup_errors]}"
        )
        # Local field should still be valid
        extract_errors = [
            e for e in result.errors if "extract" in e.message and "non-existent" in e.message
        ]
        assert len(extract_errors) == 0

    def test_cross_workflow_with_invalid_local_field_still_caught(self):
        """Cross-workflow skip must not suppress errors on local actions."""
        workflow_config = {
            "actions": [
                {
                    "name": "extract",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "dependencies": [
                        "extract",
                        {"workflow": "other_wf", "action": "remote"},
                    ],
                    "context_scope": {
                        "observe": [
                            "extract.nonexistent_field",
                            "remote.*",
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Cross-workflow ref should be fine
        remote_errors = [e for e in result.errors if "remote" in e.message]
        assert len(remote_errors) == 0

        # But the bad local field ref should still error
        field_errors = [e for e in result.errors if "nonexistent_field" in e.message]
        assert len(field_errors) >= 1, "Invalid local field ref was not caught"

    def test_cross_workflow_wildcard_expansion_skipped(self):
        """Wildcard refs on cross-workflow deps should be kept as-is, not error."""
        workflow_config = {
            "actions": [
                {
                    "name": "consumer",
                    "dependencies": [
                        {"workflow": "other_wf", "action": "remote"},
                    ],
                    "context_scope": {
                        "observe": ["source.*", "remote.*"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        remote_errors = [e for e in result.errors if "remote" in e.message]
        assert len(remote_errors) == 0, (
            f"Cross-workflow wildcard raised errors: {[e.message for e in remote_errors]}"
        )

    def test_multiple_cross_workflow_deps(self):
        """Multiple cross-workflow deps from different workflows all skip."""
        workflow_config = {
            "actions": [
                {
                    "name": "aggregator",
                    "dependencies": [
                        {"workflow": "wf_a", "action": "action_a"},
                        {"workflow": "wf_b", "action": "action_b"},
                    ],
                    "context_scope": {
                        "observe": [
                            "source.*",
                            "action_a.*",
                            "action_b.field_x",
                        ],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        cross_errors = [
            e for e in result.errors if "action_a" in e.message or "action_b" in e.message
        ]
        assert len(cross_errors) == 0, (
            f"Multiple cross-workflow refs raised errors: {[e.message for e in cross_errors]}"
        )


class TestTypeCheckerCrossWorkflow:
    """Direct type checker tests with cross_workflow_actions set."""

    def _create_graph_with_agents(self, agents_config):
        """Helper to create a graph with specified agents."""
        graph = DataFlowGraph()
        graph.add_node(
            DataFlowNode(
                name="source",
                agent_kind=ActionKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )
        for agent in agents_config:
            reqs = []
            for ref_agent, ref_field in agent.get("refs", []):
                reqs.append(
                    InputRequirement(
                        source_agent=ref_agent,
                        field_path=ref_field,
                        location=agent.get("ref_location", "context_scope.observe"),
                        raw_reference=f"{ref_agent}.{ref_field}",
                    )
                )
            graph.add_node(
                DataFlowNode(
                    name=agent["name"],
                    agent_kind=agent.get("kind", ActionKind.LLM),
                    output_schema=OutputSchema(
                        schema_fields=agent.get("fields", set()),
                        is_schemaless=agent.get("schemaless", False),
                    ),
                    dependencies=agent.get("deps", set()),
                    input_requirements=reqs,
                )
            )
        graph.build_edges_from_requirements()
        return graph

    def test_cross_workflow_action_skipped_in_check(self):
        """Type checker skips cross-workflow actions instead of erroring."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "consumer",
                    "fields": {"output"},
                    "deps": {"source"},
                    "refs": [("remote_action", "field_x")],
                },
            ]
        )

        checker = StaticTypeChecker(graph, cross_workflow_actions={"remote_action"})
        result = checker.check_all()

        remote_errors = [e for e in result.errors if "remote_action" in e.message]
        assert len(remote_errors) == 0

    def test_non_cross_workflow_unknown_agent_still_errors(self):
        """Unknown agent NOT in cross_workflow_actions still raises error."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "consumer",
                    "fields": {"output"},
                    "deps": {"source"},
                    "refs": [("typo_agent", "field")],
                },
            ]
        )

        checker = StaticTypeChecker(graph, cross_workflow_actions={"other_action"})
        result = checker.check_all()

        typo_errors = [e for e in result.errors if "typo_agent" in e.message]
        assert len(typo_errors) >= 1

    def test_cross_workflow_not_flagged_as_implicit_dep(self):
        """Cross-workflow actions should not appear as 'implicit dependency' warnings."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "consumer",
                    "fields": {"output"},
                    "deps": {"source"},
                    "refs": [("remote_action", "field_x")],
                },
            ]
        )

        checker = StaticTypeChecker(graph, cross_workflow_actions={"remote_action"})
        warnings = checker.check_missing_dependencies()

        remote_warnings = [w for w in warnings if "remote_action" in w.message]
        assert len(remote_warnings) == 0, (
            f"Cross-workflow action flagged as implicit dep: {[w.message for w in remote_warnings]}"
        )

    def test_empty_cross_workflow_set_preserves_existing_behavior(self):
        """With no cross-workflow actions, existing error behavior is unchanged."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "consumer",
                    "fields": {"output"},
                    "deps": {"source"},
                    "refs": [("nonexistent", "field")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert any("nonexistent" in e.message for e in result.errors)
