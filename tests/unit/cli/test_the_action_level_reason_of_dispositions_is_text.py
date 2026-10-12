"""The action-level table of `agac dispositions` prints a stored reason as text.

A node-level failure stores the error that stopped the action, which can quote record
content or a provider reply, so its reason can hold a closing tag that matches no open one.
"""

import io

from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand


def _command() -> tuple[DispositionsCommand, io.StringIO]:
    stream = io.StringIO()
    command = DispositionsCommand("wf", None, False)
    command.console = Console(file=stream, width=200, color_system=None, force_terminal=False)
    return command, stream


def test_a_reason_holding_a_closing_tag_is_printed_as_written():
    command, stream = _command()

    command._show_action_level(
        [("flatten", {"disposition": "failed", "reason": "[/note] gamma breaks [fragile]"})]
    )

    assert "[/note] gamma breaks [fragile]" in stream.getvalue()


def test_the_halt_hint_is_still_shown_for_a_halted_action():
    """Control: the hint beneath the table is markup of the command's own."""
    command, stream = _command()

    command._show_action_level(
        [("flatten", {"disposition": "failed", "reason": "boom", "detail": "halted_on_exhausted"})]
    )

    assert "agac retry" in stream.getvalue()
