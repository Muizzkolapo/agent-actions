"""Tests for cross-workflow dependency handling in ActionConfig and WorkflowConfig."""

from __future__ import annotations

from agent_actions.config.schema import ActionConfig, ActionKind, WorkflowConfig


class TestActionConfigCrossWorkflowDeps:
    """ActionConfig accepts dict deps at validation and strips them post-validation."""

    def test_string_deps_preserved(self):
        cfg = ActionConfig(name="a", intent="test", dependencies=["action_a", "action_b"])
        assert cfg.dependencies == ["action_a", "action_b"]

    def test_dict_deps_stripped(self):
        cfg = ActionConfig(
            name="a",
            intent="test",
            dependencies=[{"workflow": "upstream", "action": "x"}],
        )
        assert cfg.dependencies == []

    def test_mixed_deps_keep_strings_only(self):
        cfg = ActionConfig(
            name="a",
            intent="test",
            dependencies=[
                "local_action",
                {"workflow": "upstream", "action": "remote_action"},
                "another_local",
            ],
        )
        assert cfg.dependencies == ["local_action", "another_local"]

    def test_model_dump_has_no_dicts(self):
        cfg = ActionConfig(
            name="a",
            intent="test",
            dependencies=["local", {"workflow": "X"}],
        )
        dumped = cfg.model_dump()
        assert dumped["dependencies"] == ["local"]
        assert all(isinstance(d, str) for d in dumped["dependencies"])


class TestWorkflowConfigCrossWorkflowDeps:
    """WorkflowConfig validates without error when actions have cross-workflow deps."""

    def test_workflow_with_cross_workflow_deps_validates(self):
        wf = WorkflowConfig(
            name="test_wf",
            description="test",
            actions=[
                ActionConfig(
                    name="consume_upstream",
                    intent="test",
                    kind=ActionKind.TOOL,
                    impl="process",
                    dependencies=[{"workflow": "other_wf", "action": "produce"}],
                ),
            ],
        )
        assert len(wf.actions) == 1
        assert wf.actions[0].dependencies == []

    def test_workflow_invariants_ignore_stripped_cross_deps(self):
        """Cross-workflow deps are stripped before validate_workflow_invariants runs,
        so they don't trigger 'dangling dependency' errors."""
        wf = WorkflowConfig(
            name="test_wf",
            description="test",
            actions=[
                ActionConfig(
                    name="first",
                    intent="produces data",
                    kind=ActionKind.TOOL,
                    impl="produce",
                ),
                ActionConfig(
                    name="second",
                    intent="consumes",
                    kind=ActionKind.TOOL,
                    impl="consume",
                    dependencies=[
                        "first",
                        {"workflow": "external_wf", "action": "external_action"},
                    ],
                ),
            ],
        )
        # Should not raise — "first" exists, dict dep is stripped
        assert wf.actions[1].dependencies == ["first"]
