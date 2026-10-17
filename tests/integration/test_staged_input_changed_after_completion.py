"""A completed workflow meets staged input that changed since it completed."""

import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_an_upstream_edit_reruns_what_reads_it import _raw_rows
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _backend,
    chained,  # noqa: F401
    project,  # noqa: F401
)


def _staging(project):  # noqa: F811
    return project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"


def _stored_files(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return sorted(backend.list_target_files(action))
    finally:
        backend.close()


def test_a_file_added_after_completion_reaches_every_action(chained):  # noqa: F811
    _staging(chained).joinpath("more.json").write_text(json.dumps([{"page_content": "page new"}]))

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    for action in (ACTION, SECOND):
        assert len(_stored_files(chained, action)) == 2, action
        assert len(_raw_rows(chained, action)) == RECORDS + 1, action


def test_a_replaced_file_leaves_no_rows_from_the_one_removed(chained):  # noqa: F811
    _staging(chained).joinpath("pages.json").unlink()
    _staging(chained).joinpath("other.json").write_text(json.dumps([{"page_content": "page x"}]))

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    for action in (ACTION, SECOND):
        assert len(_stored_files(chained, action)) == 1, action
        assert len(_raw_rows(chained, action)) == 1, action


def test_untouched_staging_runs_nothing_again(chained):  # noqa: F811
    before = {action: _raw_rows(chained, action) for action in (ACTION, SECOND)}

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert {action: _raw_rows(chained, action) for action in (ACTION, SECOND)} == before


def test_a_file_rewritten_under_the_same_name_is_read_again(chained):  # noqa: F811
    _staging(chained).joinpath("pages.json").write_text(
        json.dumps([{"page_content": "page rewritten"}])
    )

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    for action in (ACTION, SECOND):
        assert len(_raw_rows(chained, action)) == 1, action
