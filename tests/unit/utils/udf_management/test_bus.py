"""Bus dict subclass: require() is strict, get()/[]/iteration stay tolerant."""

import pytest

from agent_actions.utils.udf_management.bus import Bus


def test_require_returns_value():
    assert Bus({"author": {"x": 1}}).require("author") == {"x": 1}


def test_require_raises_on_unknown():
    with pytest.raises(KeyError) as exc:
        Bus({"author": {}}).require("fb_author")
    assert "fb_author" in str(exc.value)


def test_require_error_lists_available_namespaces():
    # Distinct names (no substring overlap) pin the available-namespaces list; a
    # trivial `return self[ns]` — which the spec's own fixtures would pass — omits it.
    with pytest.raises(KeyError) as exc:
        Bus({"ground": {}, "writer": {}}).require("typo")
    msg = str(exc.value)
    assert "typo" in msg and "ground" in msg and "writer" in msg


def test_get_stays_tolerant():
    assert Bus({"author": {}}).get("missing") is None
    assert Bus({"author": {}}).get("missing", 5) == 5


def test_is_a_dict():
    b = Bus({"a": 1})
    assert b["a"] == 1 and "a" in b and dict(b) == {"a": 1}


def test_wrapping_does_not_leak_top_level_mutation():
    # Bus(original) is a top-level copy: a UDF rebinding a top-level key does not
    # leak back to the caller. Nested mutations still propagate (shared refs).
    original = {"author": {}}
    Bus(original)["injected"] = 1
    assert "injected" not in original
