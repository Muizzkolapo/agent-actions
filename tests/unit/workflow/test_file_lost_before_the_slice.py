"""A file lost from the walk must make the action's record count unknown (625).

610 made a completed action's stamp carry what the run processed, so a later
limit at or above that count can be shown to leave the record set whole. The
count is summed only from chunks that reach the slice — but a file can fail
before its slice and the action still completes, because a per-file failure is
never inferred to be fatal to the action. Those records are never counted, the
stamp still says ``truncated: False``, and a later limit below the true total
reads as one that could not have bitten. The action is skipped and its short
output is vouched for, which is the direction 610 exists to exclude.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_actions.utils.limits import record_indices_to_process, slice_observation
from agent_actions.workflow.runner_file_processing import process_directory_files

ACTION = "flatten"


class _Backend:
    """A weak-referenceable stand-in; the observation registry keys on identity."""


def _records(count: int) -> list[dict[str, str]]:
    return [{"source_guid": f"g{i}"} for i in range(count)]


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)


def _walk(tmp_path, backend, per_file):
    """Run the directory walk over two files, delegating each to *per_file*."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("a.json", "b.json"):
        (input_dir / name).write_text(json.dumps([{"id": name}]))
    output = tmp_path / "output"
    output.mkdir()

    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner._should_skip_item.return_value = False
    runner._process_single_file.side_effect = per_file

    params = MagicMock()
    params.action_config = {}
    params.action_name = ACTION
    params.strategy = MagicMock()
    params.idx = 0
    params.file_type_filter = None

    return process_directory_files(runner, input_dir, output, str(input_dir), params, set())


class TestAFileLostFromTheWalk:
    def test_a_file_that_fails_leaves_the_action_count_unknown(self, tmp_path):
        """The failed file's records were never counted, so the total is short —
        and a short total is the one error that reads as 'a smaller limit could
        not have bitten'."""
        backend = _Backend()
        calls = {"n": 0}

        def per_file(_params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("unreadable input")
            record_indices_to_process(_records(4), {}, ACTION, storage_backend=backend)

        _found, processed, _errors = _walk(tmp_path, backend, per_file)

        assert processed == 1, "the walk tolerates the failure and completes"
        assert slice_observation(backend, ACTION) is None

    def test_a_file_that_fails_after_the_others_still_poisons(self, tmp_path):
        """Order must not matter: the records are missing either way."""
        backend = _Backend()
        calls = {"n": 0}

        def per_file(_params):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("unreadable input")
            record_indices_to_process(_records(4), {}, ACTION, storage_backend=backend)

        _walk(tmp_path, backend, per_file)

        assert slice_observation(backend, ACTION) is None

    def test_a_clean_walk_keeps_its_count(self, tmp_path):
        """The guard must not cost a run that lost nothing its precision."""
        backend = _Backend()

        def per_file(_params):
            record_indices_to_process(_records(3), {}, ACTION, storage_backend=backend)

        _walk(tmp_path, backend, per_file)

        assert slice_observation(backend, ACTION) == (6, False)
