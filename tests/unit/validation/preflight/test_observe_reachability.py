"""Preflight tests for observe field reachability.

Verifies that the static analyzer catches cases where an action observes
a field from an action that runs AFTER its declared dependency — meaning
the record snapshot won't carry that field at runtime.

Based on real qanalabs-quiz-maker failure: validate_final_question depended
on write_scenario_question but observed review_question_quality.issues (which
runs after write_scenario_question). Runtime error: "field not found."
"""


from agent_actions.validation.static_analyzer.observe_reachability import (
    check_observe_reachability,
)


def _build_actions(action_list: list[dict]) -> dict[str, dict]:
    """Convert a list of action dicts to the {name: config} format."""
    return {a["name"]: a for a in action_list}


class TestObserveReachabilityErrors:
    """Cases where preflight should ERROR — observe field unreachable from dependency."""

    def test_observe_from_action_after_dependency(self):
        """Real case: observe review_question_quality.issues but depend on write_scenario_question."""
        actions = _build_actions(
            [
                {"name": "write_scenario_question", "dependencies": []},
                {"name": "review_question_quality", "dependencies": ["write_scenario_question"]},
                {"name": "rewrite_failed_question", "dependencies": ["review_question_quality"]},
                {
                    "name": "validate_final_question",
                    "dependencies": ["write_scenario_question"],
                    "context_scope": {"observe": ["review_question_quality.issues"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 1
        assert "review_question_quality" in errors[0]
        assert "write_scenario_question" in errors[0]
        assert "validate_final_question" in errors[0]

    def test_observe_multiple_unreachable_fields(self):
        """Multiple observe fields from actions after dependency — one error per field."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {"name": "action_b", "dependencies": ["action_a"]},
                {"name": "action_c", "dependencies": ["action_b"]},
                {
                    "name": "action_d",
                    "dependencies": ["action_a"],
                    "context_scope": {"observe": ["action_b.field1", "action_c.field2"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 2
        assert any("action_b" in e for e in errors)
        assert any("action_c" in e for e in errors)

    def test_observe_from_parallel_branch_not_in_dep_chain(self):
        """Observe an action on a parallel branch not transitively before dependency."""
        actions = _build_actions(
            [
                {"name": "root", "dependencies": []},
                {"name": "branch_a", "dependencies": ["root"]},
                {"name": "branch_b", "dependencies": ["root"]},
                {
                    "name": "consumer",
                    "dependencies": ["branch_a"],
                    "context_scope": {"observe": ["branch_b.field"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 1
        assert "branch_b" in errors[0]


class TestObserveReachabilityPassing:
    """Cases where preflight should pass — observe fields are reachable."""

    def test_observe_from_action_before_dependency(self):
        """Normal case: observe field from action earlier in chain."""
        actions = _build_actions(
            [
                {"name": "write_scenario_question", "dependencies": []},
                {"name": "review_question_quality", "dependencies": ["write_scenario_question"]},
                {"name": "rewrite_failed_question", "dependencies": ["review_question_quality"]},
                {
                    "name": "validate_final_question",
                    "dependencies": ["rewrite_failed_question"],
                    "context_scope": {"observe": ["review_question_quality.issues"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 0

    def test_observe_own_dependency(self):
        """Observing your own dependency is always valid."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {
                    "name": "action_b",
                    "dependencies": ["action_a"],
                    "context_scope": {"observe": ["action_a.field"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 0

    def test_observe_wildcard_from_reachable_action(self):
        """Wildcard observe (action.*) from reachable action passes."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {"name": "action_b", "dependencies": ["action_a"]},
                {
                    "name": "action_c",
                    "dependencies": ["action_b"],
                    "context_scope": {"observe": ["action_a.*"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 0

    def test_seed_and_staging_references_skipped(self):
        """Seed data and staging references are not actions — skip them."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {
                    "name": "action_b",
                    "dependencies": ["action_a"],
                    "context_scope": {
                        "observe": ["seed.syllabus", "source.input_file", "action_a.x"]
                    },
                },
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 0

    def test_multiple_dependencies_latest_used(self):
        """With multiple deps, observe only needs to be before the LATEST one."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {"name": "action_b", "dependencies": ["action_a"]},
                {"name": "action_c", "dependencies": ["action_b"]},
                {
                    "name": "action_d",
                    "dependencies": ["action_a", "action_c"],
                    "context_scope": {"observe": ["action_b.field"]},
                },
            ]
        )

        errors = check_observe_reachability(actions)

        # action_b is before action_c (latest dep), so it's reachable
        assert len(errors) == 0

    def test_no_observe_no_errors(self):
        """Actions without context_scope.observe produce no errors."""
        actions = _build_actions(
            [
                {"name": "action_a", "dependencies": []},
                {"name": "action_b", "dependencies": ["action_a"]},
            ]
        )

        errors = check_observe_reachability(actions)

        assert len(errors) == 0
