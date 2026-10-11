"""One batch file that the guard skips whole does not make the action a passthrough.

When preparation leaves nothing to send for a file, the run writes that file itself and
a node-level `passthrough` row, "All records tombstoned". The row is the resume marker
for an action that holds nothing. Written whatever the action's other files hold, and
never cleared while the action holds rows, it printed as the action's state on an
action that read `completed` with answers stored.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    WORKFLOW,
    _agac,
    _project,
    _store,
    _stored_rows,
)

_SKIPS_EVERY_PAGE_OF_A = (
    '    guard: { condition: \'source.page_content == "Page b1." OR source.page_content == '
    '"Page b2."\', on_false: skip }\n'
)


def _guard_turning_away_file_a(project: Path, behaviour: str = "skip") -> None:
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    assert "    expect: { repair: none }\n" in text
    guard = _SKIPS_EVERY_PAGE_OF_A.replace("on_false: skip", f"on_false: {behaviour}")
    config.write_text(text.replace("    expect: { repair: none }\n", guard))


def _node_rows(project: Path) -> list[tuple[str, str]]:
    con = _store(project)
    try:
        return con.execute(
            "select disposition, coalesce(reason, '') from record_disposition "
            "where action_name = ? and record_id = '__node__'",
            (CLI_ACTION,),
        ).fetchall()
    finally:
        con.close()


class TestAFileTheGuardSkipsWholeBesideAFileThatIsAnswered:
    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("skipped") / "project")
        _guard_turning_away_file_a(project)
        submitted = _agac(project, "--fresh")
        collected = [_agac(project)]
        while collected[-1].status == "batch_submitted" and len(collected) < 3:
            collected.append(_agac(project))
        shown = run_agac(project, "dispositions", "-a", WORKFLOW)
        return SimpleNamespace(
            project=project,
            submitted=submitted,
            collected=collected,
            shown=shown.stdout + shown.stderr,
        )

    def test_the_action_completes_with_the_other_file_answered(self, runs):
        assert runs.collected[-1].code == 0, runs.collected[-1].output
        assert runs.collected[-1].status == "completed", runs.collected[-1].output
        answered = {
            name: [state for _, state in rows] for name, rows in _stored_rows(runs.project).items()
        }
        assert answered["b_pages.json"] == ["processed", "processed"]

    def test_no_node_level_row_is_left_beside_the_answers(self, runs):
        """The action holds answers, so a row saying it holds none is a false state."""
        assert _node_rows(runs.project) == []

    def test_dispositions_names_no_action_level_state(self, runs):
        assert "Action-level state" not in runs.shown, runs.shown
        assert "All records tombstoned" not in runs.shown, runs.shown


class TestAnActionThatHoldsNoAnswerKeepsTheMarker:
    """Control: the row is the resume marker for an action that holds nothing, so it must
    survive where every record of every file was filtered and no row was stored."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("nothing") / "project", ("a",))
        _guard_turning_away_file_a(project, "filter")
        submitted = _agac(project, "--fresh")
        return SimpleNamespace(project=project, submitted=submitted)

    def test_an_action_that_holds_no_answer_is_skipped_and_keeps_its_row(self, runs):
        assert runs.submitted.status == "skipped", runs.submitted.output
        assert _node_rows(runs.project) == [("passthrough", "All records tombstoned")]


class TestAResumedRunWhoseOnlyRecordLeftToSendIsSkipped:
    """The collect pass is stopped at the second file and the runs after it resume.

    `a_pages.json` is collected and `b_pages.json` is not. The guard skips Page a1 only,
    so when the action is resumed the one record of the first file left to look at is the
    skipped one, and the file is written with nothing to send.
    """

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("resumed") / "project")
        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "    expect: { repair: none }\n",
                "    guard: { condition: 'source.page_content != \"Page a1.\"', on_false: skip }\n",
            )
        )
        submitted = _agac(project, "--fresh")
        stopped = _agac(project, STOP_AT="b_pages.json")
        resumed = [_agac(project)]
        while resumed[-1].status == "batch_submitted" and len(resumed) < 3:
            resumed.append(_agac(project))
        return SimpleNamespace(
            project=project, submitted=submitted, stopped=stopped, resumed=resumed
        )

    def test_the_action_ends_completed_with_every_page_but_the_skipped_one_answered(self, runs):
        assert runs.resumed[-1].status == "completed", runs.resumed[-1].output
        assert _stored_rows(runs.project) == {
            "a_pages.json": [("a1", "guard_skipped"), ("a2", "processed")],
            "b_pages.json": [("b1", "processed"), ("b2", "processed")],
        }

    def test_no_node_level_row_is_left_beside_the_answers(self, runs):
        assert _node_rows(runs.project) == []
