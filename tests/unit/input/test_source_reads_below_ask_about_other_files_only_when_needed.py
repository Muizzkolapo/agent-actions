"""Whether other staged files may hold a field is asked only once a read is missing (1537)."""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging.field_validation import (
    validate_source_reads_below,
)

ROWS = [{"content": {"source": {"title": "a"}}, "source_guid": "g1"}]


def _configs(observe: str) -> dict:
    return {
        "first": {"name": "first", "dependencies": []},
        "second": {
            "name": "second",
            "dependencies": ["first"],
            "context_scope": {"observe": [observe]},
        },
    }


def test_it_is_not_asked_when_every_read_is_held():
    def never() -> bool:
        raise AssertionError("asked although no read is missing")

    validate_source_reads_below(
        ROWS, "staging/a.json", "first", _configs("source.title"), conclusive=never
    )


def test_it_is_asked_once_for_every_missing_read():
    asked: list[int] = []

    def once() -> bool:
        asked.append(1)
        return True

    configs = _configs("source.body")
    configs["third"] = {
        "name": "third",
        "dependencies": ["second"],
        "context_scope": {"observe": ["source.other"]},
    }
    with pytest.raises(ConfigValidationError, match="source.body"):
        validate_source_reads_below(ROWS, "staging/a.json", "first", configs, conclusive=once)
    assert asked == [1]
