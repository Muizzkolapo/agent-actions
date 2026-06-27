"""The bare `"secret"` key is redacted from /api/context responses.

The original redaction regex caught `_secret` (suffix), `auth_secret`, and
related credential patterns, but missed the bare key `"secret"` — common
in OAuth-style payloads (`{"client_id": ..., "secret": ...}`).
"""

from __future__ import annotations

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


def test_secret_in_compound_name_still_handled_by_suffix_rule():
    """Existing `_secret` suffix coverage must still pass — the new rule
    is additive, not replacing the suffix match."""
    out = _sanitize_context({"client_secret": "x"})
    assert out["client_secret"] == "***"


def test_benign_secret_prefix_not_redacted():
    """`secret_santa` is a benign name; the regression test for
    sanitize-redacts (test_sanitize_context_does_not_redact_benign_keys)
    already pins this — repeat here so the additive rule doesn't silently
    over-match."""
    out = _sanitize_context({"secret_santa": "bob"})
    assert out["secret_santa"] == "bob"
