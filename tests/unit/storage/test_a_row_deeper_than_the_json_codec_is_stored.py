"""The store keeps a row nested deeper than the JSON codec recurses, and still reads it back.

``DEPTH`` is far past the C codec's limit on any interpreter (about 1000 on Python 3.11),
and past SQLite's own JSON depth limit of 1000.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

DEPTH = 100_000


def _nested(depth: int) -> list:
    node: list = ["leaf"]
    for _ in range(depth - 1):
        node = [node]
    return node


def _depth(node) -> int:
    depth = 0
    while isinstance(node, list):
        node = node[0]
        depth += 1
    return depth


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    yield b
    b.close()


def _source_row(guid: str, **extra) -> dict:
    return {"source_guid": guid, "content": {"source": {"page": guid, **extra}}}


class TestADeepRow:
    def test_a_target_row_is_written_and_read_back_whole(self, backend):
        row = {
            "source_guid": "G0",
            "_state": "processed",
            "content": {"source": {"deep": _nested(DEPTH)}, "act": {"v": 1}},
        }

        backend.write_target("act", "f.json", [row], is_first_action=True)
        (back,) = backend.read_target("act", "f.json")

        assert _depth(back["content"]["source"]["deep"]) == DEPTH
        assert back["content"]["act"] == {"v": 1}

    def test_a_source_row_is_written_and_read_back_whole(self, backend):
        backend.write_source("pages", [_source_row("G0", deep=_nested(DEPTH))])

        (back,) = backend.read_source("pages")

        assert _depth(back["content"]["source"]["deep"]) == DEPTH

    def test_a_repeat_chain_is_found_beside_a_row_sqlite_cannot_parse(self, backend):
        backend.write_source(
            "pages",
            [
                _source_row("DEEP", deep=_nested(DEPTH)),
                _source_row("PLAIN"),
                {**_source_row("REPEAT"), "repeat_of_source_guid": "PLAIN"},
            ],
        )

        assert backend.records_share_a_repeat_chain(["PLAIN"])
        assert backend.records_share_a_repeat_chain(["REPEAT"])
        assert not backend.records_share_a_repeat_chain(["DEEP"])

    def test_a_deep_row_that_is_itself_a_repeat_is_found(self, backend):
        backend.write_source(
            "pages",
            [
                _source_row("FIRST"),
                {**_source_row("DEEP", deep=_nested(DEPTH)), "repeat_of_source_guid": "FIRST"},
            ],
        )

        assert backend.records_share_a_repeat_chain(["DEEP"])
        assert backend.records_share_a_repeat_chain(["FIRST"])
        assert not backend.records_share_a_repeat_chain(["SOMEONE_ELSE"])
