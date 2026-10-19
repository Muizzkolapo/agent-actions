"""Every reader of a staged JSON document drops a leading UTF-8 byte order mark (1537)."""

from __future__ import annotations

import json

import pytest

from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.input.loaders.json import JsonLoader

ROWS = [{"title": "a"}, {"title": "b"}]
MARKED = "\ufeff" + json.dumps(ROWS)


@pytest.fixture
def marked_file(tmp_path):
    path = tmp_path / "rows.json"
    path.write_bytes(MARKED.encode("utf-8"))
    return path


def test_file_reader_reads_a_marked_json_file(marked_file):
    assert FileReader(str(marked_file)).read() == ROWS


def test_json_loader_reads_a_marked_json_file(marked_file):
    loader = JsonLoader({}, "first")

    assert loader.process(None, str(marked_file)) == ROWS
    assert loader.load_data(str(marked_file)) == ROWS


def test_json_loader_reads_a_marked_json_string():
    assert JsonLoader({}, "first").process(MARKED) == ROWS
