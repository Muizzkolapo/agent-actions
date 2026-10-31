"""The bare `"secret"` key is redacted from /api/context responses.

The original redaction regex caught `_secret` (suffix), `auth_secret`, and
related credential patterns, but missed the bare key `"secret"` — common
in OAuth-style payloads (`{"client_id": ..., "secret": ...}`).
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers.hitl.server import _sanitize_context


def test_bare_secret_key_is_redacted():
    out = _sanitize_context({"secret": "shhh", "other": "ok"})
    assert out["secret"] == "***"
    assert out["other"] == "ok"


def test_nested_secret_key_is_redacted():
    out = _sanitize_context({"config": {"secret": "shhh", "name": "ok"}})
    assert out["config"]["secret"] == "***"
    assert out["config"]["name"] == "ok"


def test_secret_key_in_list_is_redacted():
    out = _sanitize_context([{"secret": "x"}, {"y": 2}])
    assert out[0]["secret"] == "***"
    assert out[1]["y"] == 2


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [("client_secret", "x", "***"), ("secret_santa", "bob", "bob")],
    ids=["compound-name-redacted", "benign-prefix-kept"],
)
def test_the_bare_key_rule_neither_replaces_the_suffix_rule_nor_over_matches(key, value, expected):
    out = _sanitize_context({key: value})
    assert out[key] == expected
