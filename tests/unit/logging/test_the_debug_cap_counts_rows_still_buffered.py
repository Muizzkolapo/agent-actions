"""The debug cap counts the rows still in the buffer as well as the rows on disk."""

from __future__ import annotations

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.handlers import JSONFileHandler

CAP = 3_000


@pytest.mark.parametrize("buffer_size", [1, 5, 1_000])
def test_debug_rows_stop_at_the_first_that_starts_past_the_cap(tmp_path, buffer_size):
    log = tmp_path / "events.json"
    handler = JSONFileHandler(file_path=log, buffer_size=buffer_size, max_debug_bytes=CAP)
    for i in range(60):
        handler.handle(BaseEvent(level=EventLevel.DEBUG, message=f"debug-{i}" + "x" * 200))
    handler.close()

    lines = log.read_text().splitlines(keepends=True)
    debug = [line for line in lines if '"level": "debug"' in line]
    assert 0 < len(debug) < 60
    assert sum(map(len, debug[:-1])) < CAP <= sum(map(len, debug))
    assert '"LogFileCapReachedEvent"' in lines[-1]


def test_a_row_is_written_as_it_was_when_handled(tmp_path):
    log = tmp_path / "events.json"
    handler = JSONFileHandler(file_path=log, buffer_size=10)
    event = BaseEvent(level=EventLevel.INFO, message="first")
    event.data["items"] = [1]
    handler.handle(event)
    event.data["items"].append(2)
    handler.close()

    assert '"items": [1]' in log.read_text()
