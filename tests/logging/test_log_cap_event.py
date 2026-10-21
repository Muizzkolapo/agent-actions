"""LogFileCapReachedEvent states the cap in units a reader can act on."""

from __future__ import annotations

import pytest

from agent_actions.logging.events import LogFileCapReachedEvent


@pytest.mark.parametrize(
    ("max_bytes", "shown"), [(52_428_800, "50.0 MB"), (20_000, "20,000 bytes")]
)
def test_the_message_states_the_cap_in_readable_units(max_bytes, shown):
    event = LogFileCapReachedEvent(file_name="events.json", max_bytes=max_bytes)

    assert event.message.startswith(f"events.json reached {shown};")
