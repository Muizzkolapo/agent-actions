"""Two staged files that map to one stored name refuse the walk (1243).

Both modes store a staged file as ``batch_output_name(relative_path)``, which
replaces its suffix with ``.json``. ``page.csv`` and ``page.json`` are two inputs
under one stored name, so one silently overwrites the other. The walk refuses
before processing any file, naming both.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.runner_file_processing import process_directory_files

ACTION = "extract"


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


def _params(tmp_path, file_type_filter=None):
    params = MagicMock()
    params.action_config = {}
    params.action_name = ACTION
    params.strategy = MagicMock()
    params.idx = 0
    params.file_type_filter = file_type_filter
    params.output_directory = str(tmp_path / "output")
    params.upstream_data_dirs = []
    return params


def _staging(tmp_path, names):
    input_dir = tmp_path / "staging"
    for name in names:
        target = input_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps([{"id": name}]))
    (tmp_path / "output").mkdir(exist_ok=True)
    return input_dir


def _walk(tmp_path, names, file_type_filter=None):
    input_dir = _staging(tmp_path, names)
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = None
    processed = []
    runner._process_single_file.side_effect = lambda fp: processed.append(fp)
    result = None
    error = None
    try:
        result = process_directory_files(
            runner,
            input_dir,
            tmp_path / "output",
            str(input_dir),
            _params(tmp_path, file_type_filter),
            set(),
        )
    except ConfigurationError as e:
        error = e
    return result, error, processed


@pytest.mark.parametrize(
    "first, second",
    [("page.csv", "page.json"), ("sub/page.csv", "sub/page.json"), ("a.txt", "a.csv")],
)
def test_two_inputs_under_one_stored_name_refuse_the_walk_naming_both(tmp_path, first, second):
    _, error, processed = _walk(tmp_path, [first, second, "other.json"])

    assert error is not None
    message = str(error)
    assert first in message
    assert second in message
    stored = first.rsplit(".", 1)[0] + ".json"
    assert stored in message
    assert processed == [], "no file may be processed once the walk is refused"


def test_inputs_with_distinct_stored_names_are_all_processed(tmp_path):
    result, error, processed = _walk(tmp_path, ["page.csv", "sub/page.json", "other.json"])

    assert error is None
    assert result[1] == 3
    assert len(processed) == 3


def test_a_file_the_suffix_filter_leaves_out_does_not_collide(tmp_path):
    result, error, processed = _walk(tmp_path, ["page.csv", "page.json"], file_type_filter={"json"})

    assert error is None
    assert result[1] == 1
    assert len(processed) == 1
