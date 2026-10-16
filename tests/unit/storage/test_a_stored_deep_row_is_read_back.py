"""A stored row nested hundreds of levels deep is read back, and the cache stays sealed.

Rows read from a target are cached after reconstruction, and each read hands out a copy so
a caller cannot change what the next one sees. `copy.deepcopy` recurses once per level and
fails on a row about 500 levels deep, so a downstream action could not read the rows of the
action above it.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

DEPTH = 700


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _depth(node: list) -> int:
    depth = 0
    while node:
        node = node[0]
        depth += 1
    return depth


def _innermost(node: list) -> list:
    while node:
        node = node[0]
    return node


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    b.write_target(
        "act",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": {"source": {"deep": _nested(DEPTH)}, "act": {"v": 1}},
            }
        ],
        is_first_action=True,
    )
    yield b
    b.close()


class TestReadingADeepStoredRow:
    def test_the_row_comes_back_whole(self, backend):
        rows = backend.read_target("act", "f.json")

        assert _depth(rows[0]["content"]["source"]["deep"]) == DEPTH

    def test_a_caller_changing_what_it_read_does_not_change_the_next_read(self, backend):
        first = backend.read_target("act", "f.json")
        _innermost(first[0]["content"]["source"]["deep"]).append("changed")
        first[0]["content"]["act"]["v"] = 99

        second = backend.read_target("act", "f.json")

        assert _innermost(second[0]["content"]["source"]["deep"]) == []
        assert second[0]["content"]["act"]["v"] == 1
