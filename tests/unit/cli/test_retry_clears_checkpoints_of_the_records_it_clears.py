"""A retry clears the checkpoint rows of the records it clears, and no others.

It cleared every checkpoint row of each action it ran. A record whose `success` it kept
then had its row carried from the stored file, which an edit had made stale (1277), or,
with no file stored, was asked and paid for again (1316).
"""

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.storage.backend import DISPOSITION_FAILED, DISPOSITION_SUCCESS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "enrich"
PATH = "pages.json"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _checkpointed(backend) -> set[str]:
    return {row["source_guid"] for row in backend.read_checkpoint_records(ACTION, PATH)}


def test_a_kept_success_keeps_its_checkpoint_row(backend):
    backend.save_checkpoint_records(
        ACTION, PATH, [{"source_guid": "sg-ok", "v": 1}, {"source_guid": "sg-bad", "v": 2}]
    )
    backend.set_disposition(ACTION, "sg-ok", DISPOSITION_SUCCESS)
    backend.set_disposition(ACTION, "sg-bad", DISPOSITION_FAILED, reason="boom")

    RetryCommand(RetryCommandArgs(agent="wf"))._clear_for_the_rerun(
        backend, [ACTION], {"sg-bad"}, repairing={"sg-bad"}
    )

    assert _checkpointed(backend) == {"sg-ok"}
    assert [r["record_id"] for r in backend.get_disposition(ACTION)] == ["sg-ok"]


def test_a_record_repaired_below_the_start_loses_its_row_there(backend):
    backend.save_checkpoint_records(ACTION, PATH, [{"source_guid": "sg-below", "v": 1}])

    RetryCommand(RetryCommandArgs(agent="wf"))._clear_for_the_rerun(
        backend, [ACTION], set(), repairing={"sg-below"}
    )

    assert _checkpointed(backend) == set()
