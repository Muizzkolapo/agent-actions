import itertools

import pytest

from agent_actions.logging.core.events import LEVEL_SEVERITY, BaseEvent, EventLevel
from agent_actions.logging.core.handlers.console import ConsoleEventHandler
from agent_actions.logging.core.handlers.json_file import JSONFileHandler

PAIRS = list(itertools.product(EventLevel.ordered(), repeat=2))


def _at_least(level: EventLevel, floor: EventLevel) -> bool:
    order = EventLevel.ordered()
    return order.index(level) >= order.index(floor)


def test_every_level_has_its_rank_in_severity_order():
    assert sorted(LEVEL_SEVERITY, key=LEVEL_SEVERITY.__getitem__) == EventLevel.ordered()
    assert set(LEVEL_SEVERITY) == set(EventLevel)


@pytest.mark.parametrize(("level", "floor"), PAIRS)
def test_the_json_log_keeps_events_at_or_above_its_floor(tmp_path, level, floor):
    handler = JSONFileHandler(tmp_path / "events.json", min_level=floor)
    assert handler.accepts(BaseEvent(level=level, message="m")) is _at_least(level, floor)


@pytest.mark.parametrize(("level", "floor"), PAIRS)
def test_the_console_keeps_events_at_or_above_its_floor(level, floor):
    handler = ConsoleEventHandler(min_level=floor, categories={"none"})
    event = BaseEvent(level=level, message="m", category="other")
    # Outside its categories, only a warning or an error clears the floor.
    expected = _at_least(level, floor) and level in (EventLevel.WARN, EventLevel.ERROR)
    assert handler.accepts(event) is expected
