"""An action that runs and finds no input file holds nothing (1240).

A reset clears what called an action's rows done and relies on the re-run to
write each file again. A run that finds no input file writes none, so the rows
it stored before stood, made from input that is gone, and its readers ran again
on them. Editing the action is what resets it; its readers are reset by that.
"""

import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _fail,
    _record_ids,
    chained,  # noqa: F401
    project,  # noqa: F401
)
from tests.integration.test_skipped_reader_drops_stale_rows import (
    MODES,
    RESET_ONLY,
    _add_guard_to,
    _node_reason,
    _rows,
    _run,
    _status,
)


def _input(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"


def _remove_the_input(root):
    _input(root).unlink()


@MODES
def test_an_action_whose_input_is_gone_keeps_no_rows_and_neither_does_its_reader(
    chained,  # noqa: F811
    mode,
):
    _remove_the_input(chained)
    _add_guard_to(chained, ACTION, RESET_ONLY)

    _run("-e", mode)

    assert _rows(chained, ACTION) == 0
    assert _rows(chained, SECOND) == 0
    assert _status(chained, ACTION) == "skipped"
    # The reader is skipped under it, not run on nothing.
    assert _status(chained, SECOND) == "skipped"
    assert _node_reason(chained, SECOND) == f"Upstream dependency '{ACTION}' skipped"


def test_preview_no_longer_serves_the_reader_rows(chained):  # noqa: F811
    _remove_the_input(chained)
    _add_guard_to(chained, ACTION, RESET_ONLY)
    _run()

    result = CliRunner().invoke(cli, ["preview", "-w", WORKFLOW, "-a", SECOND])

    assert f"No data found for action '{SECOND}'" in result.output, result.output


def test_a_first_run_with_nothing_to_read_skips_the_reader_instead_of_failing_it(
    chained,  # noqa: F811
):
    """The same walk on a fresh run. The reader used to fail looking for a directory
    its upstream never wrote."""
    _remove_the_input(chained)

    _run("--fresh")

    assert _status(chained, ACTION) == "skipped"
    assert _status(chained, SECOND) == "skipped"


def test_a_file_limit_does_not_keep_rows_of_input_that_is_gone(chained):  # noqa: F811
    """A file limit stops a walk only after it has taken a file, so a walk that found
    none under one left no file unopened whose rows it should keep."""
    _remove_the_input(chained)

    # A new limit is itself what resets the action.
    _run("--file-limit", "1")

    assert _rows(chained, ACTION) == 0
    assert _rows(chained, SECOND) == 0


def test_the_input_coming_back_brings_the_rows_back(chained):  # noqa: F811
    _remove_the_input(chained)
    _add_guard_to(chained, ACTION, RESET_ONLY)
    _run()

    _input(chained).write_text(json.dumps([{"page_content": f"page {i}"} for i in range(RECORDS)]))
    _run()

    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
    assert _status(chained, SECOND) == "completed"


def test_a_retry_of_a_record_whose_input_is_gone_keeps_the_rows(chained):  # noqa: F811
    """A repair touches only the records it names, so finding none of their files is
    no reason to delete the rest of the action's rows. Nor is it a repair of the record
    named, whose failure stands."""
    named = _record_ids(chained)[-1]
    _fail(chained, named)
    _remove_the_input(chained)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", named])

    assert result.exit_code == 0, result.output
    assert _status(chained, ACTION) == "completed_with_failures"
    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
