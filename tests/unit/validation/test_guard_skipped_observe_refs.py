"""Tests for _check_guard_skipped_observe_refs() preflight warnings.

Validates that preflight warns when context_scope.observe references a specific
field from an action with guard.on_false: "skip".  The entire namespace is null
when the guard skips, so specific field access crashes at runtime.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _make_workflow(*actions):
    """Build a minimal workflow config from action dicts."""
    return {"actions": list(actions)}


def _llm_action(name, *, schema_fields=None, guard=None, depends_on=None, observe=None):
    """Build an LLM action config."""
    action = {"name": name, "prompt": f"Process {name}"}
    if schema_fields:
        action["schema"] = {
            "type": "object",
            "properties": {f: {"type": "string"} for f in schema_fields},
        }
    if guard:
        action["guard"] = guard
    if depends_on:
        action["depends_on"] = depends_on
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


class TestGuardSkippedObserveRefs:
    """Preflight warns when observing specific field from skip-guarded action."""

    def test_observe_specific_field_from_skip_guarded_warns(self):
        """Observing action.field where action has on_false: skip -> warns."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [w for w in result.warnings if "may be null" in w.message]
        assert len(skip_warnings) == 1
        assert "review.hitl_status" in skip_warnings[0].message
        assert 'on_false: "skip"' in skip_warnings[0].message

    def test_observe_wildcard_from_skip_guarded_no_warning(self):
        """Observing action.* where action has on_false: skip -> no warning."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.*"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 0

    def test_observe_specific_field_from_filter_guarded_no_warning(self):
        """Observing action.field where action has on_false: filter -> no warning.

        Filter removes individual records but the namespace still exists.
        """
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 0

    def test_observe_specific_field_from_non_guarded_no_warning(self):
        """Observing action.field where action has no guard -> no warning."""
        workflow = _make_workflow(
            _llm_action("review", schema_fields=["hitl_status"]),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 0

    def test_string_guard_defaults_to_filter_no_skip_warning(self):
        """String-style guard defaults to filter, not skip -> no skip warning."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard="score >= 6",
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 0

    def test_multiple_fields_from_skip_guarded_each_warn(self):
        """Multiple specific field refs to same skip-guarded action -> one warning each."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status", "reviewer_notes"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status", "review.reviewer_notes"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 2
        warned_fields = {w.referenced_field for w in skip_warnings}
        assert warned_fields == {"hitl_status", "reviewer_notes"}

    def test_warning_includes_wildcard_hint(self):
        """Warning hint suggests using wildcard instead."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 1
        assert skip_warnings[0].hint is not None
        assert "review.*" in skip_warnings[0].hint

    def test_warning_location_references_consumer(self):
        """Warning location points to the consumer action, not the guarded one."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert skip_warnings[0].location.agent_name == "downstream"
        assert skip_warnings[0].referenced_agent == "review"

    def test_llm_consumer_also_warns(self):
        """LLM (non-tool) consumer observing skip-guarded field also warns.

        Unlike the existing _check_guard_nullable_fields which only checks tool
        actions, this check applies to ALL downstream actions.
        """
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "summarizer",
                schema_fields=["summary"],
                depends_on=["review"],
                observe=["review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 1

    def test_mixed_wildcard_and_specific_only_warns_for_specific(self):
        """Mixed refs: wildcard safe, specific field warns."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["hitl_status", "notes"],
                guard={"condition": "needs_review == true", "on_false": "skip"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.*", "review.hitl_status"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        skip_warnings = [
            w
            for w in result.warnings
            if "may be null" in w.message and 'on_false: "skip"' in w.message
        ]
        assert len(skip_warnings) == 1
        assert "hitl_status" in skip_warnings[0].message
