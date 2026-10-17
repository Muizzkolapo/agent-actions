"""A staging JSON file nested deeper than the JSON decoder recurses is loaded whole.

``DEPTH`` is far past the C decoder's limit on any interpreter (about 1000 on Python 3.11).
"""

import json

import pytest

from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.input.loaders.json import JsonLoader
from agent_actions.utils.atomic_write import atomic_json_write

DEPTH = 100_000


def _deep_document() -> str:
    return '[{"id": "p0", "deep": ' + "[" * DEPTH + '"leaf"' + "]" * DEPTH + "}]"


def _depth_and_leaf(node) -> tuple[int, object]:
    depth = 0
    while isinstance(node, list):
        node = node[0]
        depth += 1
    return depth, node


@pytest.fixture
def staged(tmp_path):
    path = tmp_path / "pages.json"
    path.write_text(_deep_document(), encoding="utf-8")
    return path


def test_the_file_reader_loads_it(staged):
    (record,) = FileReader(str(staged)).read()

    assert record["id"] == "p0"
    assert _depth_and_leaf(record["deep"]) == (DEPTH, "leaf")


def test_the_json_loader_loads_it_from_a_file_and_from_text(staged):
    loader = JsonLoader({}, "probe")

    from_file = loader.process(None, file_path=str(staged))
    from_text = loader.process(staged.read_text(encoding="utf-8"))

    for (record,) in (from_file, from_text):
        assert _depth_and_leaf(record["deep"]) == (DEPTH, "leaf")


def test_a_deep_document_is_still_refused_when_it_is_not_json(tmp_path):
    path = tmp_path / "pages.json"
    path.write_text('[{"deep": ' + "[" * DEPTH + "]" * (DEPTH - 1) + "}]", encoding="utf-8")

    with pytest.raises(Exception) as caught:
        FileReader(str(path)).read()

    assert not isinstance(caught.value, RecursionError)
    assert "recursion" not in str(caught.value).lower()


# Indented output grows with the square of the depth, so it is written less deep.
@pytest.mark.parametrize(
    "kwargs, depth",
    [({}, DEPTH), ({"indent": 2}, 3000), ({"indent": 4, "default": str}, 3000)],
)
def test_an_atomic_json_write_writes_it_and_it_reads_back(tmp_path, kwargs, depth):
    deep: list = ["leaf"]
    for _ in range(depth - 1):
        deep = [deep]
    value = [{"id": "p0", "deep": deep}]
    target = tmp_path / "out.json"

    atomic_json_write(target, value, **kwargs)

    (record,) = FileReader(str(target)).read()
    assert _depth_and_leaf(record["deep"]) == (depth, "leaf")


def test_an_atomic_json_write_of_an_ordinary_value_is_unchanged(tmp_path):
    value = {"b": [1, 2.5, None], "a": "café"}
    target = tmp_path / "out.json"

    atomic_json_write(target, value, indent=2)

    assert target.read_text(encoding="utf-8") == json.dumps(value, indent=2)
