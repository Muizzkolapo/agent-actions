"""An edit to an upstream action, as `agac run` and `agac retry` meet it.

Two tool actions over six staged records: `flatten`, and `enrich`, which reads what
`flatten` writes. The edit gives `flatten` a guard that filters the first page, so the
next plain run resets it and it writes five rows.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
    _stored_guids,
    chained,  # noqa: F401
    project,  # noqa: F401
)


def _filter_the_first_page(project):  # noqa: F811
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    edited = config.read_text().replace(
        "    impl: flatten_pages\n",
        "    impl: flatten_pages\n"
        '    guard: { condition: \'source.page_content != "page 0"\', on_false: "filter" }\n',
    )
    assert edited != config.read_text(), "the fixture's config no longer has the line to edit"
    config.write_text(edited)


def _raw_rows(project, action):  # noqa: F811
    backend = _backend(project)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


def test_the_action_below_holds_what_the_edited_action_holds_now(chained):  # noqa: F811
    _filter_the_first_page(chained)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert len(_stored_guids(chained, ACTION)) == RECORDS - 1
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_run_with_nothing_edited_runs_neither(chained):  # noqa: F811
    """Rows whole, not their content: a tool reproduces the same content byte for byte,
    and only what a run stamps on a row shows that it was written again."""
    before = {action: _raw_rows(chained, action) for action in (ACTION, SECOND)}

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert {action: _raw_rows(chained, action) for action in (ACTION, SECOND)} == before


def test_a_repair_after_the_edit_touches_only_the_record_it_named(chained):  # noqa: F811
    """A repair answers the record it named. Resetting the edited action under it, and
    what reads it, clears every other record's disposition with nothing run to replace
    them, so the other failure can no longer be found."""
    named, other = _record_ids(chained, SECOND)[-2:]
    _fail(chained, named, SECOND)
    _fail(chained, other, SECOND)
    _filter_the_first_page(chained)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--from", SECOND, "--record", named])

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, SECOND) == "success"
    assert _disposition(chained, other, SECOND) == "failed"
    assert len(_record_ids(chained, ACTION)) == RECORDS, "the edited action lost its records"


def test_the_plain_run_after_that_repair_still_finds_the_edit(chained):  # noqa: F811
    named = _record_ids(chained, SECOND)[-1]
    _fail(chained, named, SECOND)
    _filter_the_first_page(chained)
    assert CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", named]).exit_code == 0

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert len(_stored_guids(chained, ACTION)) == RECORDS - 1
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_repair_of_the_edited_action_leaves_the_edit_for_the_plain_run(chained):  # noqa: F811
    """The repair completes the edited action on the one record it named. Stamped as
    answered under the new config, the other five keep rows the old config wrote, and
    the plain run calls both actions already complete."""
    named = _record_ids(chained, ACTION)[-1]
    _fail(chained, named)
    _filter_the_first_page(chained)
    assert CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", named]).exit_code == 0

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert len(_stored_guids(chained, ACTION)) == RECORDS - 1
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)
