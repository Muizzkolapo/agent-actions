"""Tests for schema-level cross-validation (tool impl, workflow invariants)."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, ActionKind, WorkflowConfig


def _workflow(**overrides):
    """Helper to build a minimal valid workflow dict."""
    base = {
        "name": "test-wf",
        "description": "test workflow",
        "version": "1.0",
        "actions": [
            {"name": "step1", "intent": "do something", "kind": "llm"},
        ],
    }
    base.update(overrides)
    return base


class TestToolActionValidation:
    def test_tool_without_impl_raises(self):
        with pytest.raises(ValidationError, match="impl"):
            ActionConfig(name="t", intent="tool action", kind=ActionKind.TOOL)

    def test_tool_with_impl_passes(self):
        action = ActionConfig(
            name="t", intent="tool action", kind=ActionKind.TOOL, impl="my_module.func"
        )
        assert action.impl == "my_module.func"

    def test_llm_without_impl_passes(self):
        action = ActionConfig(name="t", intent="llm action", kind=ActionKind.LLM)
        assert action.impl is None


class TestWorkflowInvariants:
    def test_duplicate_action_names_raises(self):
        with pytest.raises(ValidationError, match="Duplicate action names"):
            WorkflowConfig(
                **_workflow(
                    actions=[
                        {"name": "dup", "intent": "a", "kind": "llm"},
                        {"name": "dup", "intent": "b", "kind": "llm"},
                    ]
                )
            )

    def test_dangling_dependency_raises(self):
        with pytest.raises(ValidationError, match="Dangling dependency"):
            WorkflowConfig(
                **_workflow(
                    actions=[
                        {
                            "name": "step1",
                            "intent": "a",
                            "kind": "llm",
                            "dependencies": ["nonexistent"],
                        },
                    ]
                )
            )

    def test_valid_workflow_passes(self):
        wf = WorkflowConfig(
            **_workflow(
                actions=[
                    {"name": "step1", "intent": "a", "kind": "llm"},
                    {
                        "name": "step2",
                        "intent": "b",
                        "kind": "llm",
                        "dependencies": ["step1"],
                    },
                ]
            )
        )
        assert len(wf.actions) == 2


class TestCircularDependencyDetection:
    @pytest.mark.parametrize(
        ("dependencies", "match"),
        [
            pytest.param({"A": ["A"]}, r"A -> A", id="self"),
            pytest.param({"A": ["B"], "B": ["A"]}, r"A -> B -> A", id="two_node"),
            pytest.param(
                {"A": ["B"], "B": ["C"], "C": ["A"]}, r"A -> B -> C -> A", id="three_node"
            ),
            # A is acyclic; the B -> C -> B cycle is still found
            pytest.param(
                {"A": [], "B": ["A", "C"], "C": ["B"]}, r"B -> C -> B", id="cycle_beside_acyclic"
            ),
        ],
    )
    def test_cycle_raises_with_path(self, dependencies, match):
        actions = [
            {"name": name, "intent": name.lower(), "kind": "llm", "dependencies": deps}
            for name, deps in dependencies.items()
        ]
        with pytest.raises(ValidationError, match=match):
            WorkflowConfig(**_workflow(actions=actions))

    def test_diamond_dag_no_false_positive(self):
        """Diamond shape (A->B, A->C, B->D, C->D) is valid — no cycle."""
        wf = WorkflowConfig(
            **_workflow(
                actions=[
                    {"name": "A", "intent": "a", "kind": "llm"},
                    {
                        "name": "B",
                        "intent": "b",
                        "kind": "llm",
                        "dependencies": ["A"],
                    },
                    {
                        "name": "C",
                        "intent": "c",
                        "kind": "llm",
                        "dependencies": ["A"],
                    },
                    {
                        "name": "D",
                        "intent": "d",
                        "kind": "llm",
                        "dependencies": ["B", "C"],
                    },
                ]
            )
        )
        assert len(wf.actions) == 4

    def test_deep_chain_no_recursion_error(self):
        """A 1500-node linear chain must not hit RecursionError."""
        n = 1500
        actions = [{"name": "n0", "intent": "a", "kind": "llm"}]
        for i in range(1, n):
            actions.append(
                {
                    "name": f"n{i}",
                    "intent": "a",
                    "kind": "llm",
                    "dependencies": [f"n{i - 1}"],
                }
            )
        wf = WorkflowConfig(**_workflow(actions=actions))
        assert len(wf.actions) == n
