"""Preflight does not warn that an optional observe field may be null.

An explicit field of an upstream a guard can skip drew `'<source>.<field>' may be null
at runtime`, and the only way to silence it was a wildcard. A field marked optional says
the action expects that null, so the warning is not given; the same field without the
mark is still warned about. Optional means the field may be absent on a record, not
that it may be misspelt: a reference to an action or field that does not exist is still
an error.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)

SUFFIX = "review.rejected_text?"
MAPPING = {"field": "review.rejected_text", "optional": True, "default": ""}
REQUIRED = "review.rejected_text"


def _action(name, *, fields=None, guard=None, dependencies=None, observe=None):
    action = {"name": name, "prompt": f"Process {name}"}
    if fields is not None:
        action["schema"] = {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
        }
    if guard:
        action["guard"] = guard
    if dependencies:
        action["dependencies"] = dependencies
    action["context_scope"] = {"observe": observe or ["source.*"]}
    return action


def _skip_workflow(entry, review_fields=("rejected_text",)):
    return {
        "actions": [
            _action("spec", fields=["spec_text"]),
            _action(
                "review",
                fields=None if review_fields is None else list(review_fields),
                guard={"condition": "source.round > 1", "on_false": "skip"},
                dependencies=["spec"],
                observe=["spec.spec_text"],
            ),
            _action("retry", dependencies=["review"], observe=["spec.spec_text", entry]),
        ]
    }


def _null_warnings(result) -> list[str]:
    return [w.message for w in result.warnings if "may be null at runtime" in w.message]


class TestAFieldOfASkipGuardedUpstream:
    @pytest.mark.parametrize("entry", [SUFFIX, MAPPING], ids=["suffix", "mapping"])
    def test_an_optional_field_is_not_warned_about(self, entry):
        """Verification 7.3, at the analyzer `agac inspect` and `agac run` share."""
        result = WorkflowStaticAnalyzer(_skip_workflow(entry)).analyze()

        assert _null_warnings(result) == []
        assert result.errors == []

    def test_the_same_field_without_the_mark_is_still_warned_about(self):
        result = WorkflowStaticAnalyzer(_skip_workflow(REQUIRED)).analyze()

        (message,) = _null_warnings(result)
        assert message.startswith("'review.rejected_text' may be null at runtime.")

    def test_the_warning_names_the_optional_form_as_a_way_out(self):
        result = WorkflowStaticAnalyzer(_skip_workflow(REQUIRED)).analyze()

        (warning,) = [w for w in result.warnings if "may be null at runtime" in w.message]
        assert "'review.rejected_text?'" in warning.hint

    def test_only_the_optional_one_of_two_fields_is_spared(self):
        workflow = _skip_workflow(SUFFIX, review_fields=("rejected_text", "score"))
        workflow["actions"][2]["context_scope"]["observe"].append("review.score")

        result = WorkflowStaticAnalyzer(workflow).analyze()

        (message,) = _null_warnings(result)
        assert message.startswith("'review.score' may be null at runtime.")


class TestAFieldOfAFilterGuardedUpstreamAtAFanIn:
    def _workflow(self, entry):
        return {
            "actions": [
                _action("spec", fields=["spec_text"]),
                _action(
                    "review",
                    fields=["rejected_text"],
                    guard={"condition": "source.round > 1", "on_false": "filter"},
                    dependencies=["spec"],
                    observe=["spec.spec_text"],
                ),
                _action(
                    "score", fields=["points"], dependencies=["spec"], observe=["spec.spec_text"]
                ),
                _action("retry", dependencies=["review", "score"], observe=[entry, "score.points"]),
            ]
        }

    @staticmethod
    def _hazards(result) -> list[str]:
        return [w.message for w in result.warnings if "via alternate dependency" in w.message]

    @pytest.mark.parametrize("entry", [SUFFIX, MAPPING], ids=["suffix", "mapping"])
    def test_an_optional_field_is_not_warned_about(self, entry):
        result = WorkflowStaticAnalyzer(self._workflow(entry)).analyze()

        assert self._hazards(result) == []

    def test_the_same_field_without_the_mark_is_still_warned_about(self):
        result = WorkflowStaticAnalyzer(self._workflow(REQUIRED)).analyze()

        assert len(self._hazards(result)) == 1


class TestOptionalIsNotMisspelt:
    @pytest.mark.parametrize(
        "entry",
        ["review.rejected_txt?", {"field": "review.rejected_txt", "optional": True}],
        ids=["suffix", "mapping"],
    )
    def test_a_field_the_upstream_schema_does_not_declare_is_still_an_error(self, entry):
        result = WorkflowStaticAnalyzer(_skip_workflow(entry)).analyze()

        messages = [e.message for e in result.errors]
        assert any("rejected_txt" in m and "review" in m for m in messages), messages
        assert not any("?" in m for m in messages), messages

    def test_the_error_is_the_one_the_field_draws_without_the_mark(self):
        optional = WorkflowStaticAnalyzer(_skip_workflow("review.rejected_txt?")).analyze()
        required = WorkflowStaticAnalyzer(_skip_workflow("review.rejected_txt")).analyze()

        assert [e.message for e in optional.errors] == [e.message for e in required.errors]

    def test_an_action_that_does_not_exist_is_still_an_error(self):
        optional = WorkflowStaticAnalyzer(_skip_workflow("reviw.rejected_text?")).analyze()
        required = WorkflowStaticAnalyzer(_skip_workflow("reviw.rejected_text")).analyze()

        assert optional.errors
        assert [e.message for e in optional.errors] == [e.message for e in required.errors]

    def test_an_upstream_with_no_declared_schema_is_judged_as_it_is_without_the_mark(self):
        optional = WorkflowStaticAnalyzer(_skip_workflow(SUFFIX, review_fields=None)).analyze()
        required = WorkflowStaticAnalyzer(_skip_workflow(REQUIRED, review_fields=None)).analyze()

        assert [e.message for e in optional.errors] == [e.message for e in required.errors]
        assert _null_warnings(optional) == []

    def test_an_optional_wildcard_is_an_error_naming_the_entry(self):
        result = WorkflowStaticAnalyzer(_skip_workflow("review.*?")).analyze()

        assert any("review.*?" in e.message and "wildcard" in e.message for e in result.errors)
