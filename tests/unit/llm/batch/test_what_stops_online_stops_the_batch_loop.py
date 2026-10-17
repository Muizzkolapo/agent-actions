"""Past the preflight's sample, batch stops the action on what online stops it for.

The preflight renders only the first few records. Behind them, preparing a record can
raise what online stops the action on while preparing it: an incomplete configuration,
or a render error no variable explains. Batch failed that record alone and sent the
rest. What online fails alone still fails alone.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import (
    ConfigurationError,
    RecordContextError,
    TemplateVariableError,
    is_action_fatal,
)
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import (
    _PREFLIGHT_SAMPLE_SIZE,
    BatchTaskPreparator,
)
from agent_actions.processing.prepared_task import GuardStatus
from agent_actions.prompt.service import PromptPreparationService

ROWS = _PREFLIGHT_SAMPLE_SIZE + 3
LATE = f"g{ROWS - 1}"


def _raised_by_render(template: str, context: dict) -> Exception:
    try:
        PromptPreparationService._render_prompt_template(
            template, context, agent_name="summarize", mode="batch"
        )
    except Exception as e:
        return e
    raise AssertionError("the render did not fail")


def _prepare(late_raises: Exception):
    """Prepare ROWS records; only the last, past the preflight's sample, raises."""

    def prepare(row, *_args, **_kwargs):
        if row["source_guid"] == LATE:
            raise late_raises
        return MagicMock(
            guard_status=GuardStatus.PASSED,
            passthrough_fields={},
            llm_context={},
            formatted_prompt="p",
        )

    preparer = MagicMock()
    preparer.prepare.side_effect = prepare
    provider = MagicMock()
    provider.prepare_tasks.side_effect = lambda tasks, _config: tasks
    data = [{"target_id": f"t{i}", "source_guid": f"g{i}"} for i in range(ROWS)]
    with (
        patch(
            "agent_actions.llm.batch.processing.preparator.get_task_preparer",
            return_value=preparer,
        ),
        patch.object(BatchTaskPreparator, "_validate_config", return_value=None),
        patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt"),
    ):
        return BatchTaskPreparator().prepare_tasks(
            {"agent_type": "summarize", "name": "summarize"}, data, provider
        )


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            ConfigurationError("the action's configuration is incomplete"),
            id="an_incomplete_configuration",
        ),
        pytest.param(
            _raised_by_render("{{ s.words // s.pages }}", {"s": {"words": 1, "pages": 0}}),
            id="a_render_error_no_variable_explains",
        ),
    ],
)
def test_it_stops_the_action(error):
    assert isinstance(error, (ConfigurationError, TemplateVariableError))

    with pytest.raises(type(error)) as raised:
        _prepare(error)

    assert raised.value is error
    assert is_action_fatal(raised.value)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(RecordContextError("declared fields ['body'] not found"), id="context"),
        pytest.param(
            _raised_by_render("{{ s.body }}", {"s": {"title": "p"}}), id="a_missing_variable"
        ),
        pytest.param(ValueError("a tool's answer this record provoked"), id="anything_else"),
    ],
)
def test_what_online_fails_alone_fails_alone(error):
    prepared = _prepare(error)

    assert prepared.stats.error_items == 1
    assert len(prepared.tasks) == ROWS - 1
    (late,) = [e for e in prepared.context_map.values() if e["source_guid"] == LATE]
    assert BatchContextMetadata.get_filter_status(late) == FilterStatus.FAILED
