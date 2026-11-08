"""The quarantined, action-level and expect report tables print whole at 80 columns.

Fitted to the terminal, Rich cut their cells with an ellipsis, so a record ID cut to
``a1b2…`` could not be copied into a retry and a rule id read ``never_matc…``.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.cli.expect import ExpectReportCommand
from agent_actions.expectations.report import ActionTally, RuleTally
from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize_page_content_for_the_reviewer"
RECORD_ID = "rec_3f9a1c2b7d4e8f60_a1b2c3d4e5f60718_9c8b7a6f5e4d3c2b"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _narrow() -> Console:
    return Console(file=StringIO(), width=80, no_color=True)


def _quarantined(backend) -> str:
    command = DispositionsCommand(agent="wf", action=None, quarantined=True)
    command.console = _narrow()
    command._show_quarantined(backend, [ACTION])
    return command.console.file.getvalue()


def test_a_quarantined_record_id_and_action_print_whole(backend):
    backend.set_disposition(
        action_name=ACTION,
        record_id=RECORD_ID,
        disposition=DISPOSITION_FAILED,
        reason="schema validation failed on field 'summary'",
    )

    output = _quarantined(backend)

    assert RECORD_ID in output
    assert ACTION in output
    assert "…" not in output


def test_an_action_level_row_prints_whole(backend):
    backend.set_disposition(
        action_name=ACTION,
        record_id=NODE_LEVEL_RECORD_ID,
        disposition=DISPOSITION_FAILED,
        reason="Retry exhausted for record 34d2c361 after 2 attempts (on_exhausted=raise)",
    )

    output = _quarantined(backend)

    assert ACTION in output
    assert "…" not in output


def test_an_expect_report_rule_id_and_type_print_whole():
    rules = (
        RuleTally(id="never_matches_warn_rule_id", type="match_like_pattern", severity="warn"),
        RuleTally(id="no_forbidden_phrases_in_body", type="no_forbidden_phrases", severity="error"),
    )
    tally = ActionTally(
        action="ql_honesty_probe",
        records=4,
        records_passed=4,
        rules=rules,
        records_total=4,
    )
    command = ExpectReportCommand(agent="w", action=None, as_json=False)
    command.console = _narrow()

    command._render([tally], ["ql_honesty_probe"])
    output = command.console.file.getvalue()

    for rule in rules:
        assert rule.id in output
        assert rule.type in output
    assert "…" not in output
