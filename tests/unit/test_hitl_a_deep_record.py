"""The HITL provider takes a record nested deeper than the JSON codec can recurse (1487).

The client decoded its context, and the server fingerprinted, redacted and served it, with
the recursive codec and recursive walks, so a review over such a record failed with a bare
``RecursionError``. The review page's own ``JSON.stringify`` has the same kind of limit.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from flask import jsonify

from agent_actions.llm.providers.hitl.client import HitlClient
from agent_actions.llm.providers.hitl.server import HitlServer
from agent_actions.utils import deep_json

DEPTH = 20_000
LEAF = "leaf at the bottom"
TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "agent_actions"
    / "llm"
    / "providers"
    / "hitl"
    / "templates"
    / "approval.html"
)


def _deep_list(depth: int = DEPTH) -> list:
    value: list | str = LEAF
    for _ in range(depth):
        value = [value]
    return value  # type: ignore[return-value]


def _deep_dict_with_secret(depth: int = DEPTH) -> dict:
    value: dict = {"api_key": "sk-live-secret", "note": LEAF}
    for _ in range(depth):
        value = {"inner": value}
    return value


def _depth_and_leaf(node) -> tuple[int, object]:
    depth = 0
    while isinstance(node, list) and len(node) == 1:
        node = node[0]
        depth += 1
    return depth, node


def _server(context_data) -> HitlServer:
    return HitlServer(port=3097, instructions="Review", context_data=context_data, timeout=1)


def test_the_client_hands_the_server_a_deep_context_decoded():
    context = deep_json.dumps([{"source": {"deep": _deep_list()}}])
    with patch("agent_actions.llm.providers.hitl.client.HitlServer") as server_class:
        server_class.return_value = Mock(start_and_wait=Mock(return_value={"hitl_status": "x"}))

        HitlClient.invoke({"name": "review", "hitl": {"port": 3097}}, context)

    (record,) = server_class.call_args.kwargs["context_data"]
    assert _depth_and_leaf(record["source"]["deep"]) == (DEPTH, LEAF)


def test_the_server_serves_a_deep_context_to_the_review_page():
    server = _server([{"source": {"deep": _deep_list()}}, {"source": {"deep": "flat"}}])

    response = server.app.test_client().get("/api/context")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    served = deep_json.loads(response.get_data())["data"]
    assert [_depth_and_leaf(r["source"]["deep"]) for r in served] == [(DEPTH, LEAF), (0, "flat")]


def test_a_secret_key_nested_deep_is_still_redacted():
    server = _server([_deep_dict_with_secret()])

    served = deep_json.loads(server.app.test_client().get("/api/context").get_data())["data"]

    node = served[0]
    for _ in range(DEPTH):
        node = node["inner"]
    assert node == {"api_key": "***", "note": LEAF}


def test_the_fingerprint_of_a_deep_context_tells_it_from_another():
    deep = _server([_deep_list()])._data_fingerprint
    deeper = _server([_deep_list(DEPTH + 1)])._data_fingerprint

    assert deep != deeper


def test_an_ordinary_context_is_served_and_fingerprinted_as_before():
    """The page reads what ``jsonify`` gave it, keys in the same order, and the fingerprint
    is unchanged, so a review state saved before still matches."""
    context = [{"b": 1, "a": {"auth_token": "t", "z": [1.5, None, True]}, "é": "ü"}]
    server = _server(context)

    served = server.app.test_client().get("/api/context")
    with server.app.test_request_context():
        expected = jsonify(
            {
                "_envelope": True,
                "data": [{**context[0], "a": {"auth_token": "***", "z": [1.5, None, True]}}],
            }
        )

    assert served.mimetype == expected.mimetype
    assert json.dumps(json.loads(served.get_data())) == json.dumps(json.loads(expected.get_data()))
    legacy = json.dumps(context, sort_keys=True, default=str)
    assert server._data_fingerprint == hashlib.sha256(legacy.encode()).hexdigest()[:16]


def _js_function(source: str, name: str) -> str:
    """The text of ``function name(...) {...}`` in *source*, skipping strings and comments."""
    start = source.index(f"function {name}(")
    index = source.index("{", start)
    depth = 0
    while True:
        char = source[index]
        if char in "'\"":
            index += 1
            while source[index] != char:
                index += 2 if source[index] == "\\" else 1
        elif source.startswith("/*", index):
            index = source.index("*/", index) + 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page's script")
def test_the_review_page_shows_a_value_too_deep_for_json_stringify():
    page = TEMPLATE.read_text(encoding="utf-8")
    names = ["esc", "syntaxHighlight"] + re.findall(r"function (jsonText\w*)\(", page)
    script = (
        "\n".join(_js_function(page, name) for name in names)
        + f"""
var value = "{LEAF}";
for (var i = 0; i < {DEPTH}; i++) value = [value];
var html = syntaxHighlight(value);
var text = html.replace(/<[^>]*>/g, "").replace(/&quot;/g, '"');
var shallow = {{b: [1, -2.5, true, null, "x\\"y"], a: {{}}, c: [[]], "é": "ü"}};
process.stdout.write(JSON.stringify({{
    text: text,
    shallow: syntaxHighlight(shallow) === syntaxHighlight(JSON.stringify(shallow, null, 2)),
    compact: jsonTextWithoutRecursion(shallow) === JSON.stringify(shallow),
}}));
"""
    )

    ran = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)

    assert ran.returncode == 0, ran.stderr[-2000:]
    shown = json.loads(ran.stdout)
    assert shown["text"] == "[" * DEPTH + json.dumps(LEAF) + "]" * DEPTH
    assert shown["shallow"] is True
    assert shown["compact"] is True


def test_a_review_saved_over_a_deep_context_is_restored_by_the_next_server(tmp_path):
    state_file = tmp_path / ".hitl_reviews_x.json"
    context = [{"deep": _deep_list()}, {"deep": "flat"}]
    first = HitlServer(
        port=3097, instructions="Review", context_data=context, timeout=1, state_file=state_file
    )
    saved = first.app.test_client().post(
        "/api/review-record", json={"index": 0, "hitl_status": "approved"}
    )
    assert saved.status_code == 200

    second = HitlServer(
        port=3097, instructions="Review", context_data=context, timeout=1, state_file=state_file
    )

    assert second.record_reviews == [{"hitl_status": "approved", "user_comment": ""}, None]
