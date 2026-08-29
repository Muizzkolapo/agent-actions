"""Structured identifiers passed via ``extra=`` must reach the persisted event.

``LoggingBridgeHandler.emit`` copied exactly three keys — ``operation``,
``action_name``, ``workflow_name``. Every other ``extra`` field was dropped, so
a failure named the action but not the record. Real call sites pass
``custom_id`` (batch result handling), ``record_id`` (SQLite backend) and
``batch_id`` (batch submission) this way, and none of them survived: the
persisted entry showed ``"data": {"operation": "process_batch_item"}`` alone.

Naming the missing keys would leave the same trap for the next call site, so
the fix copies whatever ``extra`` supplied — which means these tests also have
to pin that logging's own internals do not come along.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.logging.core.events import BaseEvent
from agent_actions.logging.core.handlers.bridge import LoggingBridgeHandler
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.filters import RedactingFilter


@pytest.fixture(autouse=True)
def reset_event_manager():
    EventManager.reset()
    yield
    EventManager.reset()


class _Capture:
    def __init__(self):
        self.events: list[BaseEvent] = []

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def flush(self) -> None:
        pass


def _emit(extra: dict | None, *, redact: bool = False) -> dict:
    """Log through the real handler and return the persisted event's data."""
    capture = _Capture()
    EventManager.get().register(capture)
    handler = LoggingBridgeHandler()
    if redact:
        handler.addFilter(RedactingFilter())

    logger = logging.getLogger("agent_actions.processing.test_bridge")
    logger.setLevel(logging.DEBUG)
    logger.handlers = [handler]
    logger.propagate = False
    logger.error("something failed", extra=extra or {})

    assert capture.events, "no event reached the manager"
    return capture.events[-1].data


class TestIdentifiersSurvive:
    def test_a_custom_id_reaches_the_event(self):
        data = _emit({"operation": "process_batch_item", "custom_id": "req-42"})

        assert data["custom_id"] == "req-42"

    def test_a_record_id_reaches_the_event(self):
        data = _emit({"operation": "set_disposition", "record_id": "34d2c361"})

        assert data["record_id"] == "34d2c361"

    def test_a_batch_id_reaches_the_event(self):
        data = _emit({"operation": "submit_batch", "batch_id": "batch_abc"})

        assert data["batch_id"] == "batch_abc"

    def test_an_identifier_the_whitelist_never_knew_about_reaches_it(self):
        """The point of copying rather than naming: no list to keep updating."""
        data = _emit({"operation": "x", "shard_id": 7, "attempt": 2})

        assert data["shard_id"] == 7
        assert data["attempt"] == 2


class TestTheOriginalThreeStillWork:
    def test_operation_action_and_workflow_are_unchanged(self):
        data = _emit(
            {"operation": "run", "action_name": "author_stem", "workflow_name": "ql_mc_expect"}
        )

        assert data["operation"] == "run"
        assert data["action_name"] == "author_stem"
        assert data["workflow_name"] == "ql_mc_expect"


class TestLoggingInternalsDoNotLeak:
    """Copying `extra` must not mean copying the LogRecord."""

    @pytest.mark.parametrize(
        "attr", ["msg", "args", "levelname", "pathname", "lineno", "created", "name", "funcName"]
    )
    def test_a_standard_record_attribute_is_not_copied(self, attr):
        data = _emit({"operation": "x", "custom_id": "c"})

        assert attr not in data

    def test_a_call_with_no_extra_adds_nothing(self):
        data = _emit(None)

        assert data == {}


class TestWideningTheCopyDoesNotWidenExposure:
    """The one real risk in copying everything rather than naming three keys."""

    def test_a_secret_in_extra_is_still_redacted(self):
        data = _emit(
            {"operation": "x", "custom_id": "req-1", "api_key": "sk-SECRET-123"},
            redact=True,
        )

        assert data["custom_id"] == "req-1"
        assert data["api_key"] == "[REDACTED]"

    def test_the_raw_secret_appears_nowhere_in_the_event(self):
        data = _emit({"operation": "x", "api_key": "sk-SECRET-123"}, redact=True)

        assert not any("sk-SECRET-123" in str(v) for v in data.values())
