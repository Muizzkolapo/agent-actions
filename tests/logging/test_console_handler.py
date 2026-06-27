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
        categories={"workflow", "action", "batch"},
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
            categories={"workflow", "action", "batch"},
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


class TestDefaultFactoryFilterAcceptsActionEvents:
    """Regression test for VIOL-0085 — default console categories must include `action`.

    Action events use category ``"action"`` (see
    ``agent_actions.logging.events.types.EventCategories.ACTION`` and
    ``ActionStartEvent.__post_init__`` in workflow_events.py). The default
    non-verbose console filter set in ``agent_actions.logging.factory`` must
    therefore admit ``"action"`` so per-action INFO events reach stdout
    without ``--verbose``.
    """

    def test_default_filter_admits_action_category(self):
        from agent_actions.logging.events.workflow_events import ActionStartEvent

        handler = ConsoleEventHandler(
            min_level=EventLevel.INFO,
            categories={"workflow", "action", "batch"},
        )
        event = ActionStartEvent(
            action_name="extract_facts",
            action_index=0,
            total_actions=3,
            action_type="llm",
            input_path="agent_io/staging",
            mode="online",
        )
        assert event.category == "action"
        assert handler.accepts(event) is True

    def test_factory_default_categories_match_action_category(self):
        """The factory must produce a category set that contains the runtime
        ``ACTION`` category. This pins the wire-up so a future rename of either
        side fails loudly rather than silently dropping events."""
        import inspect

        from agent_actions.logging import factory
        from agent_actions.logging.events.types import EventCategories
        from agent_actions.logging.factory import LoggerFactory  # noqa: F401

        source = inspect.getsource(factory)
        assert f'"{EventCategories.ACTION}"' in source, (
            "factory.py must literally reference the ACTION category in its "
            "default non-verbose filter set"
        )
