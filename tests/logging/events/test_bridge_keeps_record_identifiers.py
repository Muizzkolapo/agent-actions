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


class TestStructuredValuesSurviveWhole:
    """Real call sites pass dicts and lists, not only scalars.

    A copy restricted to scalars passes every other test here while silently
    dropping guard context, upstream dirs and error details at live sites.
    """

    def test_a_dict_value_is_kept(self):
        data = _emit({"operation": "guard_evaluation", "error_details": {"field": "x", "n": 2}})

        assert data["error_details"] == {"field": "x", "n": 2}

    def test_a_list_value_is_kept(self):
        data = _emit({"operation": "x", "upstream_data_dirs": ["/a", "/b"]})

        assert data["upstream_data_dirs"] == ["/a", "/b"]


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

    @pytest.mark.parametrize(
        "field", ["batch_id", "item_id", "correlation_id", "action_index", "workflow_name"]
    )
    def test_a_secret_in_a_caller_named_field_is_redacted(self, field):
        """These names were on the filter's skip list.

        They are caller-controlled — exactly the fields that can carry a secret —
        and before this change they were persisted without ever being scanned.
        """
        data = _emit({"operation": "x", field: "sk-ant-" + "A" * 24}, redact=True)

        assert data[field] == "sk-ant-***", data

    def test_the_raw_secret_appears_nowhere_in_the_event(self):
        data = _emit({"operation": "x", "api_key": "sk-SECRET-123"}, redact=True)

        assert not any("sk-SECRET-123" in str(v) for v in data.values())


class TestAFormattedRecordDoesNotLeakItsRendering:
    """A Formatter permanently sets record.message/asctime.

    Not reachable in-tree today (the bridge is the only handler on
    agent_actions), but the union guarding those two names is otherwise
    unpinned, so a future child handler with its own formatter would start
    persisting the rendered message as data.
    """

    def test_message_and_asctime_are_not_copied(self):
        import logging as _logging

        capture = _Capture()
        EventManager.get().register(capture)
        handler = LoggingBridgeHandler()
        logger = _logging.getLogger("agent_actions.processing.formatted")
        logger.setLevel(_logging.DEBUG)
        logger.handlers = [handler]
        logger.propagate = False

        record = logger.makeRecord(
            logger.name, _logging.ERROR, "f", 1, "boom", (), None, extra={"custom_id": "c"}
        )
        _logging.Formatter("%(asctime)s %(message)s").format(record)
        handler.emit(record)

        data = capture.events[-1].data
        assert data["custom_id"] == "c"
        assert "message" not in data
        assert "asctime" not in data
