"""Tests for ConsoleEventHandler category bypass for WARN/ERROR."""

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.handlers.console import ConsoleEventHandler


def _make_event(level: EventLevel, category: str = "system") -> BaseEvent:
    """Create a minimal BaseEvent for testing."""
    return BaseEvent(level=level, category=category, message="test")


@pytest.fixture
def handler_with_categories() -> ConsoleEventHandler:
    """Handler with default non-verbose category filter."""
    return ConsoleEventHandler(
        min_level=EventLevel.INFO,
        categories={"workflow", "agent", "batch"},
    )


class TestCategoryBypass:
    """WARN and ERROR events bypass category filtering."""

    def test_error_bypasses_category_filter(self, handler_with_categories):
        event = _make_event(EventLevel.ERROR, category="utils")
        assert handler_with_categories.accepts(event) is True

    def test_warn_bypasses_category_filter(self, handler_with_categories):
        event = _make_event(EventLevel.WARN, category="config")
        assert handler_with_categories.accepts(event) is True

    def test_info_filtered_by_category(self, handler_with_categories):
        event = _make_event(EventLevel.INFO, category="utils")
        assert handler_with_categories.accepts(event) is False

    def test_debug_filtered_by_category(self, handler_with_categories):
        handler = ConsoleEventHandler(
            min_level=EventLevel.DEBUG,
            categories={"workflow", "agent", "batch"},
        )
        event = _make_event(EventLevel.DEBUG, category="llm")
        assert handler.accepts(event) is False

    def test_info_accepted_in_matching_category(self, handler_with_categories):
        event = _make_event(EventLevel.INFO, category="workflow")
        assert handler_with_categories.accepts(event) is True

    def test_no_categories_passes_all(self):
        handler = ConsoleEventHandler(min_level=EventLevel.INFO, categories=None)
        event = _make_event(EventLevel.INFO, category="anything")
        assert handler.accepts(event) is True

    def test_level_below_min_still_rejected(self):
        handler = ConsoleEventHandler(
            min_level=EventLevel.ERROR,
            categories={"workflow"},
        )
        event = _make_event(EventLevel.WARN, category="workflow")
        assert handler.accepts(event) is False
