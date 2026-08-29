"""``agac dispositions`` must show the action-level rows, not only record ones.

Both of its views filter out ``__node__``, so an action halted by
``on_exhausted: raise`` is invisible — and if the halt is its only row, the
action is missing from the table entirely.  That is the command the halt's own
error message and the startup warning tell the user to reach for.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

HALTED = "summarize_page_content"
REASON = "Retry exhausted for record 34d2c361 after 2 attempts (on_exhausted=raise)"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _render(backend, actions: list[str]) -> str:
    command = DispositionsCommand(agent="wf", action=None, quarantined=False)
    buffer = StringIO()
    command.console = Console(file=buffer, width=200, no_color=True)
    command._show_summary(backend, actions)
    return buffer.getvalue()


def _halt(backend, action: str = HALTED) -> None:
    backend.set_disposition(
        action_name=action,
        record_id=NODE_LEVEL_RECORD_ID,
        disposition=DISPOSITION_FAILED,
        reason=REASON,
        detail=HALTED_ON_EXHAUSTED,
    )


class TestAHaltIsVisible:
    def test_the_halted_action_appears_even_with_no_record_rows(self, backend):
        _halt(backend)

        output = _render(backend, [HALTED])

        assert HALTED in output

    def test_the_halt_reason_is_shown(self, backend):
        _halt(backend)

        output = _render(backend, [HALTED])

        assert "Retry exhausted" in output

    def test_it_is_named_as_a_halt_with_the_way_out(self, backend):
        _halt(backend)

        output = _render(backend, [HALTED])

        assert "halted" in output.lower()
        assert "agac retry" in output or "--fresh" in output

    def test_a_halt_alongside_record_rows_is_still_shown(self, backend):
        backend.set_disposition(
            action_name=HALTED,
            record_id="rec-1",
            disposition=DISPOSITION_SUCCESS,
        )
        _halt(backend)

        output = _render(backend, [HALTED])

        assert "halted" in output.lower()


class TestOrdinaryActionsAreUnchanged:
    def test_a_clean_action_gains_no_halt_notice(self, backend):
        backend.set_disposition(
            action_name="author_stem",
            record_id="rec-1",
            disposition=DISPOSITION_SUCCESS,
        )

        output = _render(backend, ["author_stem"])

        assert "author_stem" in output
        assert "halted" not in output.lower()

    def test_an_ordinary_node_failure_is_not_called_a_halt(self, backend):
        backend.set_disposition(
            action_name="author_stem",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_FAILED,
            reason="provider timed out",
        )

        output = _render(backend, ["author_stem"])

        assert "provider timed out" in output
        assert "halted" not in output.lower()
