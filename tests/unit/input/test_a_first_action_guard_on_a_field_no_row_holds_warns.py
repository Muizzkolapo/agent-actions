"""A first action's guard on a `source` field no staged row holds is logged, not refused."""

from __future__ import annotations

import logging

import pytest

from agent_actions.input.preprocessing.staging.field_validation import (
    validate_staged_source_reads,
)

ROWS = [{"content": {"source": {"title": "a"}}, "source_guid": "g1"}]
LOGGER = "agent_actions.input.preprocessing.staging.field_validation"


def _check(clause: str, caplog: pytest.LogCaptureFixture) -> list[str]:
    configs = {
        "first": {"name": "first", "guard": {"clause": clause, "behavior": "filter"}},
    }

    def conclusive() -> bool:
        return True

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        validate_staged_source_reads(
            ROWS, "staging/a.json", "first", configs, conclusive=conclusive
        )
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize("clause", ["source.titel IS NULL", "source.titel == 'a'"])
def test_a_guard_on_a_field_no_row_holds_logs_one_warning(clause, caplog):
    assert _check(clause, caplog) == [
        "Action 'first' guards on source.titel, but no record staged from staging/a.json "
        "holds 'titel'. Records from that file will not have it."
    ]


def test_a_guard_on_a_field_the_rows_hold_logs_nothing(caplog):
    assert _check("source.title IS NULL", caplog) == []


def test_its_other_reads_are_left_to_the_first_record_render(caplog):
    configs = {
        "first": {
            "name": "first",
            "prompt": "{{ source.body }}",
            "context_scope": {"observe": ["source.body"], "passthrough": ["source.other"]},
        },
    }

    def never() -> bool:
        raise AssertionError("asked although the first action's own reads are not checked")

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        validate_staged_source_reads(ROWS, "staging/a.json", "first", configs, conclusive=never)
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
