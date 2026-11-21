"""Staging does not refuse an optional observe of a `source` field no staged row holds.

A read of a field no record holds fails every record, so staging refuses the run before
any record is sent. A field observed as optional fails none of them: it resolves to its
default, in the observe and in a prompt that reads it.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging.field_validation import (
    validate_staged_source_reads,
)

ROWS = [{"content": {"source": {"title": "a"}}, "source_guid": "g1"}]


def _configs(scope: dict, prompt: str = "Summarise {{ source.title }}") -> dict:
    return {
        "first": {"name": "first", "dependencies": []},
        "second": {
            "name": "second",
            "dependencies": ["first"],
            "prompt": prompt,
            "context_scope": scope,
        },
    }


def _validate(configs: dict) -> None:
    validate_staged_source_reads(ROWS, "staging/a.json", "first", configs, conclusive=lambda: True)


def test_an_optional_field_no_row_holds_is_not_refused_and_not_warned_about(caplog):
    scope = {"observe": ["source.title", "source.body"], "optional": {"source.body": None}}

    with caplog.at_level(logging.WARNING):
        _validate(_configs(scope))

    assert "source.body" not in caplog.text


def test_a_prompt_reading_the_optional_field_is_not_refused_either():
    scope = {"observe": ["source.title", "source.body"], "optional": {"source.body": ""}}

    _validate(_configs(scope, prompt="{{ source.title }}: {{ source.body }}"))


def test_the_same_field_without_the_mark_is_still_refused():
    with pytest.raises(ConfigValidationError, match="observes source.body"):
        _validate(_configs({"observe": ["source.title", "source.body"]}))


def test_a_required_field_beside_the_optional_one_is_still_refused():
    scope = {
        "observe": ["source.title", "source.body", "source.author"],
        "optional": {"source.body": None},
    }

    with pytest.raises(ConfigValidationError) as raised:
        _validate(_configs(scope))

    assert "source.author" in str(raised.value)
    assert "source.body" not in str(raised.value)
