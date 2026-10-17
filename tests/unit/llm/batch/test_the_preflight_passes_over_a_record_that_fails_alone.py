"""The batch preflight passes over a record whose own context cannot render, as online does.

Online fails such a record and goes on with the rest: a field it observes is missing, a
value is nested past the render depth, or the template names a variable this record lacks.
Each says nothing about the template, so the preflight tries the next row and leaves the
run to fail that record alone. What online stops the action for, the preflight still
stops on: a malformed template, a render error no variable explains, anything declared
fatal to the action, and an incomplete configuration.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import (
    ConfigurationError,
    RecordContextError,
    TemplateVariableError,
    mark_action_fatal,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus
from agent_actions.prompt.service import PromptPreparationService

DEEP_DEPTH = 20_000


def _deep() -> list:
    node: list = ["leaf"]
    for _ in range(DEEP_DEPTH - 1):
        node = [node]
    return node


def _raised_by(render) -> Exception:
    try:
        render()
    except Exception as e:
        return e
    raise AssertionError("the render did not fail")


def _render(template: str, context: dict):
    return lambda: PromptPreparationService._render_prompt_template(
        template, context, agent_name="summarize", mode="batch"
    )


def _preflight(head_raises: Exception) -> int:
    """Run the preflight over two records, the first failing with *head_raises*.

    Returns how many it prepared.
    """
    preparer = MagicMock()
    preparer.prepare.side_effect = [head_raises, MagicMock(guard_status=GuardStatus.PASSED)]
    with patch(
        "agent_actions.llm.batch.processing.preparator.get_task_preparer", return_value=preparer
    ):
        BatchTaskPreparator()._run_preflight_validation(
            {"name": "summarize", "prompt": "{{ extract.body }}"},
            [
                {"target_id": "t-a1", "source_guid": "a1"},
                {"target_id": "t-a2", "source_guid": "a2"},
            ],
        )
    return preparer.prepare.call_count


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            RecordContextError("[RECORD NAMESPACE] 'extract': declared fields ['body'] not found."),
            id="an_observed_field_is_missing",
        ),
        pytest.param(
            _raised_by(_render("{{ source.deep }}", {"source": {"deep": _deep()}})),
            id="a_value_is_nested_past_the_render_depth",
        ),
        pytest.param(
            _raised_by(_render("{{ extract.body }}", {"extract": {"title": "p0"}})),
            id="the_template_names_a_variable_this_record_lacks",
        ),
    ],
)
def test_a_record_that_fails_alone_does_not_end_the_preflight(error):
    assert _preflight(error) == 2


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            _raised_by(_render("{{ extract.body ", {"extract": {"body": "b"}})),
            id="a_malformed_template",
        ),
        pytest.param(
            _raised_by(
                _render("{% macro f() %}{{ f() }}{% endmacro %}{{ f() }}", {"source": {"p": [[1]]}})
            ),
            id="a_render_error_no_variable_explains",
        ),
        pytest.param(
            mark_action_fatal(RecordContextError("declared fatal to the action")),
            id="an_error_declared_fatal_to_the_action",
        ),
        pytest.param(
            ConfigurationError("the action's configuration is incomplete"),
            id="an_incomplete_configuration",
        ),
    ],
)
def test_what_online_stops_the_action_for_still_stops_the_preflight(error):
    with pytest.raises(type(error)):
        _preflight(error)


def test_the_raised_errors_are_what_the_render_raises():
    """The parameters above are the render's own errors, not stand-ins for them."""
    deep = _raised_by(_render("{{ source.deep }}", {"source": {"deep": _deep()}}))
    missing = _raised_by(_render("{{ extract.body }}", {"extract": {"title": "p0"}}))
    malformed = _raised_by(_render("{{ extract.body ", {"extract": {"body": "b"}}))
    assert isinstance(deep, RecordContextError) and "nested" in str(deep)
    assert isinstance(missing, TemplateVariableError) and missing.missing_variables
    assert isinstance(malformed, TemplateVariableError) and not malformed.missing_variables
