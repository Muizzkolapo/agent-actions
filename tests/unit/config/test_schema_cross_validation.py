"""Tests for schema-level cross-validation (tool impl, workflow invariants)."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, ActionKind, WorkflowConfigV2


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
            WorkflowConfigV2(
                **_workflow(
                    actions=[
                        {"name": "dup", "intent": "a", "kind": "llm"},
                        {"name": "dup", "intent": "b", "kind": "llm"},
                    ]
                )
            )

    def test_dangling_dependency_raises(self):
        with pytest.raises(ValidationError, match="Dangling dependency"):
            WorkflowConfigV2(
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
        wf = WorkflowConfigV2(
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
