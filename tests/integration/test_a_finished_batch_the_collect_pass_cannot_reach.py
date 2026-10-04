"""A run whose collect pass cannot reach the provider about a finished batch comes back for it.

The pass asks the provider about each batch before reading it, and a batch it cannot ask
about is left where it is. Completed, the action is not run again, and nothing reads
that batch afterwards: its records are never answered.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    REPO,
    WORKFLOW,
    _answered,
    _batch_ids,
    _project,
    _stored_rows,
)

# `agac`, cut off from the provider about the batches of the files in UNREACHABLE once
# its collect pass starts: the poll before the pass has already found them finished.
_AGAC_OUT_OF_REACH = """
import os, sys
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

names = set(filter(None, os.environ.get("UNREACHABLE", "").split(",")))
cut_off = set()

collect = BatchProcessingService.process_all_batch_results
def collecting(self, output_directory, agent_config=None, action_name=None):
    jobs = self._registry_manager_factory(action_name).get_all_jobs()
    cut_off.update(entry.batch_id for name, entry in jobs.items() if name in names)
    return collect(self, output_directory, agent_config=agent_config, action_name=action_name)
BatchProcessingService.process_all_batch_results = collecting

fetch_status = AgacBatchClient._fetch_status
def out_of_reach(self, batch_id):
    if batch_id in cut_off:
        raise ConnectionError("the provider could not be reached")
    return fetch_status(self, batch_id)
AgacBatchClient._fetch_status = out_of_reach

from agent_actions.cli.main import main
sys.argv[0] = "agac"
sys.exit(main())
"""


def _agac(project: Path, *args: str, unreachable: str = "") -> SimpleNamespace:
    result = subprocess.run(
        [sys.executable, "-c", _AGAC_OUT_OF_REACH, "run", "-a", WORKFLOW, "-u", "tools", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
            "PYTHONPATH": str(REPO),
            "UNREACHABLE": unreachable,
        },
    )
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    status = json.loads((io_dir / ".agent_status.json").read_text())[CLI_ACTION]["status"]
    return SimpleNamespace(
        code=result.returncode, output=result.stdout + result.stderr, status=status
    )


def _runs(project: Path, unreachable: str) -> SimpleNamespace:
    submitted = _agac(project, "--fresh")
    assert submitted.status == "batch_submitted", submitted.output
    sent = _batch_ids(project)
    cut_off = _agac(project, unreachable=unreachable)
    after = _agac(project)
    return SimpleNamespace(project=project, sent=sent, cut_off=cut_off, after=after)


class TestTwoOfThreeFilesOutOfReach:
    """a_pages.json is read; the provider cannot be reached about the other two."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("two") / "project", ("a", "b", "c"))
        return _runs(project, unreachable="b_pages.json,c_pages.json")

    def test_the_run_that_could_not_reach_them_waits_for_them(self, runs):
        assert runs.cut_off.code == 0, runs.cut_off.output
        assert runs.cut_off.status == "batch_submitted"

    def test_the_run_after_it_answers_every_record_of_every_file(self, runs):
        assert runs.after.code == 0, runs.after.output
        assert runs.after.status == "completed"
        assert _stored_rows(runs.project) == _answered("a", "b", "c")

    def test_their_batches_are_collected_not_sent_again(self, runs):
        assert _batch_ids(runs.project) == runs.sent


class TestEveryFileOutOfReach:
    """No file read is the same case, not a failure: nothing about the batches is wrong."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("every") / "project")
        return _runs(project, unreachable="a_pages.json,b_pages.json")

    def test_the_run_that_could_not_reach_any_waits_for_them(self, runs):
        assert runs.cut_off.code == 0, runs.cut_off.output
        assert runs.cut_off.status == "batch_submitted"

    def test_the_run_after_it_answers_every_record(self, runs):
        assert runs.after.status == "completed", runs.after.output
        assert _stored_rows(runs.project) == _answered("a", "b")
        assert _batch_ids(runs.project) == runs.sent
