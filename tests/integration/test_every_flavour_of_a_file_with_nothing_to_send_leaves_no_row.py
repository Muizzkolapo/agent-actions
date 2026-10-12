"""A file with nothing to send leaves no node-level row on an action that holds rows.

The first tests drove one flavour, a guard skipping a whole file beside an answered one.
A row is written for each way a file can have nothing to send, and the check that clears
it runs for the action, so these pin the others: a file the guard filters whole, and an
action none of whose files has anything to send.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    WORKFLOW,
    _agac,
    _project,
    _stored_rows,
)
from tests.integration.test_a_file_of_guard_skips_is_not_the_actions_state import (
    _guard_turning_away_file_a,
    _node_rows,
)


def _run_to_the_end(project):
    runs = [_agac(project, "--fresh")]
    while runs[-1].status == "batch_submitted" and len(runs) < 4:
        runs.append(_agac(project))
    return runs


class TestAFileTheGuardFiltersWholeBesideAnAnsweredFile:
    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("filtered") / "project")
        _guard_turning_away_file_a(project, "filter")
        return SimpleNamespace(project=project, runs=_run_to_the_end(project))

    def test_the_action_completes_with_the_other_file_answered(self, runs):
        assert runs.runs[-1].status == "completed", runs.runs[-1].output
        assert _stored_rows(runs.project)["b_pages.json"] == [
            ("b1", "processed"),
            ("b2", "processed"),
        ]

    def test_no_node_level_row_is_left(self, runs):
        assert _node_rows(runs.project) == []


class TestAnActionWhoseEveryFileTheGuardSkips:
    """Every file is written with its tombstones, so the action holds rows."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("allskipped") / "project")
        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(
            config.read_text().replace(
                "    expect: { repair: none }\n",
                "    guard: { condition: 'source.page_content == \"Page zz.\"', on_false: skip }\n",
            )
        )
        return SimpleNamespace(project=project, runs=_run_to_the_end(project))

    def test_the_action_completes_holding_every_tombstone(self, runs):
        assert runs.runs[-1].status == "completed", runs.runs[-1].output
        assert _stored_rows(runs.project) == {
            "a_pages.json": [("a1", "guard_skipped"), ("a2", "guard_skipped")],
            "b_pages.json": [("b1", "guard_skipped"), ("b2", "guard_skipped")],
        }

    def test_no_node_level_row_is_left(self, runs):
        assert _node_rows(runs.project) == []
