"""`agac preview` prints a record key that holds brackets as its column header.

The cell values were escaped and the headers, which are the record's own keys, were not:
a key with a closing tag raised MarkupError and a key such as `[note]` printed blank.
"""

import io

from rich.console import Console

from agent_actions.cli.preview import PreviewCommand


def _shown(records: list) -> str:
    stream = io.StringIO()
    command = PreviewCommand(workflow="wf", action="a")
    command.console = Console(file=stream, width=200, color_system=None, force_terminal=False)
    command._show_table(records)
    return stream.getvalue()


def test_a_key_holding_a_closing_tag_is_the_header():
    out = _shown([{"source_guid": "g1", "content": {"[/x]": "v1", "name": "n1"}}])

    assert "[/x]" in out
    assert "v1" in out


def test_a_key_that_reads_as_a_tag_is_not_blank():
    out = _shown([{"source_guid": "g1", "content": {"[note]": "v1"}}])

    assert "[note]" in out


def test_an_ordinary_key_is_unchanged():
    """Control."""
    out = _shown([{"source_guid": "g1", "content": {"name": "n1"}}])

    assert "name" in out
    assert "n1" in out
