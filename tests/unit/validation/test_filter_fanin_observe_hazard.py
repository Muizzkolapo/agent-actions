"""Tests for _check_filter_fanin_observe_hazard() preflight warnings.

Validates that preflight warns when a downstream fan-in action observes specific
fields from an upstream action with guard.on_false: "filter", and an alternate
dependency path exists that can deliver the same record with a null namespace.
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


# ── Marker for filtering hazard warnings ──────────────────────────────

_FILTER_FANIN_MARKER = 'on_false: "filter"'


def _filter_fanin_warnings(result):
    """Extract only filter+fan-in hazard warnings from a validation result."""
    return [w for w in result.warnings if _FILTER_FANIN_MARKER in w.message]


class TestFilterFaninObserveHazard:
    """Preflight warns on filter+fan-in null namespace hazard."""

    def test_fanin_with_filter_guard_warns(self):
        """Classic qana_quiz pattern: filter-guarded action + alternate dep path."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "assign_option_layout",
                schema_fields=["answer_letter", "longest_option"],
                guard={"condition": "approved == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "auto_review_quality",
                schema_fields=["telegraph_score"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "write_scenario_question",
                depends_on=["assign_option_layout", "auto_review_quality"],
                observe=[
                    "assign_option_layout.answer_letter",
                    "auto_review_quality.telegraph_score",
                ],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1
        assert "assign_option_layout" in warnings[0].message
        assert "write_scenario_question" in warnings[0].message

    def test_single_dep_no_fanin_no_warning(self):
        """Filter-guarded action as sole dependency -> no fan-in, no warning."""
        workflow = _make_workflow(
            _llm_action(
                "review",
                schema_fields=["score"],
                guard={"condition": "score >= 6", "on_false": "filter"},
            ),
            _llm_action(
                "downstream",
                depends_on=["review"],
                observe=["review.score"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        assert len(_filter_fanin_warnings(result)) == 0

    def test_wildcard_observe_no_warning(self):
        """Wildcard refs to filter-guarded action at fan-in -> no warning (null-safe)."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.*", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        assert len(_filter_fanin_warnings(result)) == 0

    def test_one_warning_per_pair_not_per_field(self):
        """Multiple field refs to same filter-guarded action -> one warning per pair."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a", "field_b", "field_c"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_x"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filtered_action", "other_dep"],
                observe=[
                    "filtered_action.field_a",
                    "filtered_action.field_b",
                    "filtered_action.field_c",
                    "other_dep.field_x",
                ],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1

    def test_skip_guard_does_not_trigger_filter_fanin_warning(self):
        """Skip-guarded action at fan-in -> handled by _check_guard_skipped_observe_refs, not here."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "skip_action",
                schema_fields=["field_a"],
                guard={"condition": "ok == true", "on_false": "skip"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["skip_action", "other_dep"],
                observe=["skip_action.field_a", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        assert len(_filter_fanin_warnings(result)) == 0

    def test_string_guard_defaults_to_filter_warns_at_fanin(self):
        """String-style guard defaults to filter -> warns at fan-in."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a"],
                guard="score >= 6",
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.field_a", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1

    def test_warning_location_references_consumer(self):
        """Warning location points to the consumer, referenced_agent to the filtered action."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.field_a", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1
        assert warnings[0].location.agent_name == "consumer"
        assert warnings[0].referenced_agent == "filtered_action"

    def test_warning_hint_includes_remediation(self):
        """Warning hint includes all three remediation options."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.field_a", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1
        hint = warnings[0].hint
        assert "guard" in hint  # add a matching guard
        assert "skip" in hint  # change to on_false=skip
        assert "filtered_action.*" in hint  # use wildcard

    def test_no_guard_at_fanin_no_warning(self):
        """Fan-in with no guard on either dep -> no warning."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "dep_a",
                schema_fields=["field_a"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "dep_b",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["dep_a", "dep_b"],
                observe=["dep_a.field_a", "dep_b.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        assert len(_filter_fanin_warnings(result)) == 0

    def test_multiple_filter_guarded_deps_warn_each(self):
        """Two filter-guarded deps at fan-in -> one warning per pair."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filter_a",
                schema_fields=["fa"],
                guard={"condition": "x == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "filter_b",
                schema_fields=["fb"],
                guard={"condition": "y == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer",
                depends_on=["filter_a", "filter_b"],
                observe=["filter_a.fa", "filter_b.fb"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 2
        warned_sources = {w.referenced_agent for w in warnings}
        assert warned_sources == {"filter_a", "filter_b"}

    def test_mixed_wildcard_and_specific_warns_for_specific_only(self):
        """Mixed refs: wildcard safe, specific field triggers warning."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a", "field_b"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_x"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "consumer_wildcard",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.*", "other_dep.field_x"],
            ),
            _llm_action(
                "consumer_specific",
                depends_on=["filtered_action", "other_dep"],
                observe=["filtered_action.field_a", "other_dep.field_x"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        consumer_names = {w.location.agent_name for w in warnings}
        assert "consumer_specific" in consumer_names
        assert "consumer_wildcard" not in consumer_names

    def test_deps_inferred_from_context_scope(self):
        """Dependencies inferred from observe refs (no explicit depends_on) still detect fan-in."""
        workflow = _make_workflow(
            _llm_action("source_action", schema_fields=["data"]),
            _llm_action(
                "filtered_action",
                schema_fields=["field_a"],
                guard={"condition": "ok == true", "on_false": "filter"},
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            _llm_action(
                "other_dep",
                schema_fields=["field_b"],
                depends_on=["source_action"],
                observe=["source_action.data"],
            ),
            # No explicit depends_on — deps inferred from observe refs
            _llm_action(
                "consumer",
                observe=["filtered_action.field_a", "other_dep.field_b"],
            ),
        )

        result = WorkflowStaticAnalyzer(workflow).analyze()

        warnings = _filter_fanin_warnings(result)
        assert len(warnings) == 1

    def test_existing_guard_skip_tests_unaffected(self):
        """Existing skip-guard warnings still work — no regression."""
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

        # No filter-fanin warning (single dep, not fan-in)
        assert len(_filter_fanin_warnings(result)) == 0
