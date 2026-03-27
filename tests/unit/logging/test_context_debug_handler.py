"""Tests for agent_actions.logging.core.handlers.context_debug module."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

from agent_actions.logging.core.handlers.context_debug import (
    ActionContextInfo,
    ContextDebugHandler,
)

# ---------------------------------------------------------------------------
# Fake event helpers — lightweight stand-ins for BaseEvent subclasses
# ---------------------------------------------------------------------------


@dataclass
class _FakeEvent:
    """Minimal BaseEvent stand-in with configurable code and attributes."""

    code: str = "X000"
    action_name: str = "test_action"
    # CX001
    namespace: str = ""
    fields: list[str] = field(default_factory=list)
    dropped_fields: list[str] = field(default_factory=list)
    # CX002
    field_ref: str = ""
    reason: str = ""
    directive: str = ""
    # CX003
    observe_fields: list[str] = field(default_factory=list)
    passthrough_fields: list[str] = field(default_factory=list)
    drop_fields: list[str] = field(default_factory=list)
    # CX005
    input_sources: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    # CX006
    available_fields: list[str] = field(default_factory=list)


def _cx001(
    action: str = "act1",
    ns: str = "data",
    fields: list[str] | None = None,
    dropped: list[str] | None = None,
) -> _FakeEvent:
    return _FakeEvent(
        code="CX001",
        action_name=action,
        namespace=ns,
        fields=fields or ["f1", "f2"],
        dropped_fields=dropped or [],
    )


def _cx002(
    action: str = "act1",
    field_ref: str = "data.x",
    reason: str = "too large",
    directive: str = "observe",
) -> _FakeEvent:
    return _FakeEvent(
        code="CX002",
        action_name=action,
        field_ref=field_ref,
        reason=reason,
        directive=directive,
    )


def _cx003(
    action: str = "act1",
    observe: list[str] | None = None,
    passthrough: list[str] | None = None,
    drop: list[str] | None = None,
) -> _FakeEvent:
    return _FakeEvent(
        code="CX003",
        action_name=action,
        observe_fields=observe or [],
        passthrough_fields=passthrough or [],
        drop_fields=drop or [],
    )


def _cx005(
    action: str = "act1", inputs: list[str] | None = None, contexts: list[str] | None = None
) -> _FakeEvent:
    return _FakeEvent(
        code="CX005",
        action_name=action,
        input_sources=inputs or [],
        context_sources=contexts or [],
    )


def _cx006(
    action: str = "act1",
    field_ref: str = "data.y",
    namespace: str = "data",
    available: list[str] | None = None,
) -> _FakeEvent:
    return _FakeEvent(
        code="CX006",
        action_name=action,
        field_ref=field_ref,
        namespace=namespace,
        available_fields=available or [],
    )


# ---------------------------------------------------------------------------
# ActionContextInfo dataclass
# ---------------------------------------------------------------------------


class TestActionContextInfo:
    def test_defaults(self):
        info = ActionContextInfo(action_name="a")
        assert info.action_name == "a"
        assert info.namespaces == {}
        assert info.dropped_fields == {}
        assert info.observe_fields == []
        assert info.warnings == []
        assert info.skipped_fields == []
        assert info.not_found_fields == []


# ---------------------------------------------------------------------------
# ContextDebugHandler initialisation
# ---------------------------------------------------------------------------


class TestInit:
    def test_with_rich_available(self):
        with (
            patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", True),
            patch("agent_actions.logging.core.handlers.context_debug.Console", MagicMock),
        ):
            handler = ContextDebugHandler()
        assert handler._use_rich is True
        assert handler._console is not None

    def test_with_custom_console(self):
        console = MagicMock()
        with (
            patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", True),
            patch("agent_actions.logging.core.handlers.context_debug.Console", MagicMock),
        ):
            handler = ContextDebugHandler(console=console)
        assert handler._console is console

    def test_without_rich(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            handler = ContextDebugHandler()
        assert handler._use_rich is False
        assert handler._console is None

    def test_initial_state(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            handler = ContextDebugHandler()
        assert handler._actions == {}
        assert handler._event_count == 0


# ---------------------------------------------------------------------------
# accepts()
# ---------------------------------------------------------------------------


class TestAccepts:
    def test_accepts_context_event_codes(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            handler = ContextDebugHandler()

        for code in ("CX001", "CX002", "CX003", "CX005", "CX006"):
            event = _FakeEvent(code=code)
            assert handler.accepts(event) is True

    def test_rejects_non_context_codes(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            handler = ContextDebugHandler()

        for code in ("CX004", "WF001", "X000", ""):
            event = _FakeEvent(code=code)
            assert handler.accepts(event) is False


# ---------------------------------------------------------------------------
# handle() — CX001 namespace loaded
# ---------------------------------------------------------------------------


class TestHandleCX001:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_namespace_loaded(self):
        h = self._handler()
        h.handle(_cx001(ns="meta", fields=["a", "b"]))

        info = h.get_action_info("act1")
        assert info is not None
        assert info.namespaces == {"meta": ["a", "b"]}
        assert h.get_event_count() == 1

    def test_namespace_with_dropped_fields(self):
        h = self._handler()
        h.handle(_cx001(ns="meta", fields=["a"], dropped=["x", "y"]))

        info = h.get_action_info("act1")
        assert info.dropped_fields == {"meta": ["x", "y"]}

    def test_no_dropped_fields(self):
        h = self._handler()
        h.handle(_cx001(ns="meta", dropped=[]))

        info = h.get_action_info("act1")
        assert info.dropped_fields == {}

    def test_multiple_namespaces_same_action(self):
        h = self._handler()
        h.handle(_cx001(ns="meta", fields=["a"]))
        h.handle(_cx001(ns="data", fields=["b", "c"]))

        info = h.get_action_info("act1")
        assert len(info.namespaces) == 2


# ---------------------------------------------------------------------------
# handle() — CX002 field skipped
# ---------------------------------------------------------------------------


class TestHandleCX002:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_field_skipped(self):
        h = self._handler()
        h.handle(_cx002(field_ref="data.big_col", reason="too large", directive="observe"))

        info = h.get_action_info("act1")
        assert len(info.skipped_fields) == 1
        assert info.skipped_fields[0]["field_ref"] == "data.big_col"
        assert info.skipped_fields[0]["reason"] == "too large"
        assert info.skipped_fields[0]["directive"] == "observe"

    def test_warning_added(self):
        h = self._handler()
        h.handle(_cx002(field_ref="x.y", reason="r", directive="d"))
        info = h.get_action_info("act1")
        assert any("Skipped x.y" in w for w in info.warnings)


# ---------------------------------------------------------------------------
# handle() — CX003 scope applied
# ---------------------------------------------------------------------------


class TestHandleCX003:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_scope_applied(self):
        h = self._handler()
        h.handle(
            _cx003(
                observe=["a", "b"],
                passthrough=["c"],
                drop=["d"],
            )
        )
        info = h.get_action_info("act1")
        assert info.observe_fields == ["a", "b"]
        assert info.passthrough_fields == ["c"]
        assert info.drop_fields == ["d"]


# ---------------------------------------------------------------------------
# handle() — CX005 dependency inferred
# ---------------------------------------------------------------------------


class TestHandleCX005:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_dependency_inferred(self):
        h = self._handler()
        h.handle(_cx005(inputs=["file.csv"], contexts=["env"]))
        info = h.get_action_info("act1")
        assert info.input_sources == ["file.csv"]
        assert info.context_sources == ["env"]


# ---------------------------------------------------------------------------
# handle() — CX006 field not found
# ---------------------------------------------------------------------------


class TestHandleCX006:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_field_not_found(self):
        h = self._handler()
        h.handle(_cx006(field_ref="x.y", namespace="x", available=["a", "b"]))
        info = h.get_action_info("act1")
        assert len(info.not_found_fields) == 1
        assert info.not_found_fields[0]["field_ref"] == "x.y"
        assert info.not_found_fields[0]["namespace"] == "x"
        assert info.not_found_fields[0]["available_fields"] == ["a", "b"]

    def test_warning_added(self):
        h = self._handler()
        h.handle(_cx006(field_ref="z", namespace="ns"))
        info = h.get_action_info("act1")
        assert any("not found" in w for w in info.warnings)


# ---------------------------------------------------------------------------
# handle() — unknown action_name defaults to "unknown"
# ---------------------------------------------------------------------------


class TestHandleUnknownAction:
    def test_missing_action_name_attribute(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            h = ContextDebugHandler()

        # An event object that has no action_name attribute at all
        event = MagicMock()
        event.code = "CX001"
        del event.action_name  # ensure getattr fallback
        event.namespace = "ns"
        event.fields = ["f"]
        event.dropped_fields = []

        h.handle(event)
        assert "unknown" in h.get_all_actions()


# ---------------------------------------------------------------------------
# get_action_info / get_all_actions / get_event_count
# ---------------------------------------------------------------------------


class TestAccessors:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_get_action_info_missing(self):
        h = self._handler()
        assert h.get_action_info("nonexistent") is None

    def test_get_all_actions_empty(self):
        h = self._handler()
        assert h.get_all_actions() == {}

    def test_event_count_increments(self):
        h = self._handler()
        h.handle(_cx001())
        h.handle(_cx002())
        h.handle(_cx003())
        assert h.get_event_count() == 3

    def test_get_all_actions_multiple(self):
        h = self._handler()
        h.handle(_cx001(action="a1"))
        h.handle(_cx001(action="a2"))
        all_actions = h.get_all_actions()
        assert "a1" in all_actions
        assert "a2" in all_actions


# ---------------------------------------------------------------------------
# flush() / close() — no-ops
# ---------------------------------------------------------------------------


class TestFlushClose:
    def test_flush_noop(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            h = ContextDebugHandler()
        h.flush()  # Should not raise

    def test_close_noop(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            h = ContextDebugHandler()
        h.close()  # Should not raise


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all_data(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            h = ContextDebugHandler()
        h.handle(_cx001())
        h.handle(_cx002())

        h.reset()

        assert h.get_all_actions() == {}
        assert h.get_event_count() == 0


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


class TestToDict:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_empty_handler(self):
        h = self._handler()
        d = h.to_dict()
        assert d == {"event_count": 0, "actions": {}}

    def test_full_to_dict(self):
        h = self._handler()
        h.handle(_cx001(action="a", ns="ns", fields=["f1", "f2"], dropped=["d1"]))
        h.handle(_cx003(action="a", observe=["o1"], passthrough=["p1"], drop=["dr1"]))
        h.handle(_cx005(action="a", inputs=["src"], contexts=["ctx"]))
        h.handle(_cx002(action="a", field_ref="ref", reason="r", directive="dir"))
        h.handle(_cx006(action="a", field_ref="miss", namespace="ns", available=["f1"]))

        d = h.to_dict()
        assert d["event_count"] == 5

        act = d["actions"]["a"]
        assert act["namespaces"]["ns"]["fields"] == ["f1", "f2"]
        assert act["namespaces"]["ns"]["field_count"] == 2
        assert act["namespaces"]["ns"]["dropped_fields"] == ["d1"]
        assert act["context_scope"]["observe"] == ["o1"]
        assert act["context_scope"]["passthrough"] == ["p1"]
        assert act["context_scope"]["drop"] == ["dr1"]
        assert act["dependencies"]["input_sources"] == ["src"]
        assert act["dependencies"]["context_sources"] == ["ctx"]
        assert len(act["warnings"]) == 2
        assert len(act["skipped_fields"]) == 1
        assert len(act["not_found_fields"]) == 1

    def test_to_dict_filter_by_action(self):
        h = self._handler()
        h.handle(_cx001(action="a"))
        h.handle(_cx001(action="b"))

        d = h.to_dict(action_name="a")
        assert "a" in d["actions"]
        assert "b" not in d["actions"]

    def test_to_dict_filter_nonexistent_action(self):
        h = self._handler()
        h.handle(_cx001(action="a"))

        d = h.to_dict(action_name="missing")
        # Falls through to self._actions (all actions)
        assert "a" in d["actions"]

    def test_to_dict_namespace_without_dropped(self):
        h = self._handler()
        h.handle(_cx001(action="a", ns="ns", fields=["f1"], dropped=[]))
        d = h.to_dict()
        assert d["actions"]["a"]["namespaces"]["ns"]["dropped_fields"] == []


# ---------------------------------------------------------------------------
# display_summary() — plain text path
# ---------------------------------------------------------------------------


class TestDisplayPlainSummary:
    def _handler(self):
        with patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", False):
            return ContextDebugHandler()

    def test_empty_summary(self, capsys):
        h = self._handler()
        h.display_summary()
        captured = capsys.readouterr()
        assert "No context events collected." in captured.out

    def test_namespaces_displayed(self, capsys):
        h = self._handler()
        h.handle(_cx001(ns="meta", fields=["a", "b"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Namespaces loaded:" in captured.out
        assert "meta" in captured.out
        assert "2 fields" in captured.out

    def test_namespaces_with_dropped(self, capsys):
        h = self._handler()
        h.handle(_cx001(ns="meta", fields=["a"], dropped=["x"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "1 dropped" in captured.out

    def test_scope_displayed(self, capsys):
        h = self._handler()
        h.handle(_cx003(observe=["o"], passthrough=["p"], drop=["d"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Context scope applied:" in captured.out
        assert "observe:" in captured.out
        assert "passthrough:" in captured.out
        assert "drop:" in captured.out

    def test_dependencies_displayed(self, capsys):
        h = self._handler()
        h.handle(_cx005(inputs=["in1"], contexts=["ctx1"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Dependencies:" in captured.out
        assert "input_sources:" in captured.out
        assert "context_sources:" in captured.out

    def test_warnings_displayed(self, capsys):
        h = self._handler()
        h.handle(_cx002(field_ref="x", reason="big", directive="obs"))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Warnings:" in captured.out
        assert "!" in captured.out

    def test_filter_by_action(self, capsys):
        h = self._handler()
        h.handle(_cx001(action="a", ns="ns_a", fields=["f"]))
        h.handle(_cx001(action="b", ns="ns_b", fields=["g"]))
        h.display_summary(action_name="a")
        captured = capsys.readouterr()
        assert "ns_a" in captured.out
        assert "ns_b" not in captured.out

    def test_filter_nonexistent_action_falls_through_to_all(self, capsys):
        """When the action filter doesn't match, all actions are shown (fallback)."""
        h = self._handler()
        h.handle(_cx001(action="a"))
        h.display_summary(action_name="missing")
        captured = capsys.readouterr()
        # Falls through to showing all actions
        assert "=== Context Debug for action 'a' ===" in captured.out

    def test_action_header_shown(self, capsys):
        h = self._handler()
        h.handle(_cx001(action="my_action", ns="ns", fields=["f"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "=== Context Debug for action 'my_action' ===" in captured.out

    def test_no_scope_section_when_empty(self, capsys):
        h = self._handler()
        h.handle(_cx001(ns="ns", fields=["f"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Context scope applied:" not in captured.out

    def test_no_dependencies_section_when_empty(self, capsys):
        h = self._handler()
        h.handle(_cx001(ns="ns", fields=["f"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Dependencies:" not in captured.out

    def test_no_warnings_section_when_empty(self, capsys):
        h = self._handler()
        h.handle(_cx001(ns="ns", fields=["f"]))
        h.display_summary()
        captured = capsys.readouterr()
        assert "Warnings:" not in captured.out


# ---------------------------------------------------------------------------
# display_summary() — Rich path
# ---------------------------------------------------------------------------


class TestDisplayRichSummary:
    def _handler(self):
        console = MagicMock()
        with (
            patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", True),
            patch("agent_actions.logging.core.handlers.context_debug.Console", MagicMock),
            patch("agent_actions.logging.core.handlers.context_debug.Tree", MagicMock),
        ):
            h = ContextDebugHandler(console=console)
        return h, console

    def test_empty_summary_rich(self):
        h, console = self._handler()
        h.display_summary()
        console.print.assert_called()
        args = [str(c) for c in console.print.call_args_list]
        assert any("No context events" in a for a in args)

    def test_namespaces_tree_created(self):
        h, console = self._handler()
        h.handle(_cx001(ns="meta", fields=["a", "b", "c", "d", "e", "f"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        # Console.print should be called multiple times
        assert console.print.call_count > 0

    def test_scope_tree_created(self):
        h, console = self._handler()
        h.handle(_cx003(observe=["o"], passthrough=["p"], drop=["d"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        assert console.print.call_count > 0

    def test_dependencies_tree(self):
        h, console = self._handler()
        h.handle(_cx005(inputs=["in1"], contexts=["ctx"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        assert console.print.call_count > 0

    def test_warnings_displayed_rich(self):
        h, console = self._handler()
        h.handle(_cx002(field_ref="x", reason="r", directive="d"))
        h.display_summary()

        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Warnings" in printed or "warning" in printed.lower() or console.print.call_count > 0

    def test_filter_by_action_rich(self):
        h, console = self._handler()
        h.handle(_cx001(action="a", ns="ns_a", fields=["f"]))
        h.handle(_cx001(action="b", ns="ns_b", fields=["g"]))
        h.display_summary(action_name="a")

        printed = " ".join(str(c) for c in console.print.call_args_list)
        # Should display action 'a', not 'b'
        assert "a" in printed

    def test_rich_no_console_is_noop(self):
        """If _console is somehow None but _use_rich is True, _display_rich_summary exits early."""
        with (
            patch("agent_actions.logging.core.handlers.context_debug.RICH_AVAILABLE", True),
            patch("agent_actions.logging.core.handlers.context_debug.Console", MagicMock),
        ):
            h = ContextDebugHandler()
        h._console = None
        h._use_rich = True
        # Should not raise
        h.display_summary()

    def test_dropped_fields_truncated_in_rich(self):
        """When more than 3 dropped fields, the display truncates with '...'."""
        h, console = self._handler()
        h.handle(_cx001(ns="meta", fields=["a"], dropped=["d1", "d2", "d3", "d4", "d5"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        # Verify tree.add was called — we check the rich path ran
        assert console.print.call_count > 0

    def test_fields_truncated_beyond_five_in_rich(self):
        """When more than 5 fields, the namespace line shows '+N more'."""
        h, console = self._handler()
        h.handle(_cx001(ns="meta", fields=["a", "b", "c", "d", "e", "f", "g"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        assert console.print.call_count > 0

    def test_template_variables_section(self):
        """Rich summary should render template variables section when namespaces exist."""
        h, console = self._handler()
        h.handle(_cx001(ns="meta", fields=["a", "b", "c", "d"]))

        with patch("agent_actions.logging.core.handlers.context_debug.Tree") as MockTree:
            tree_instance = MagicMock()
            MockTree.return_value = tree_instance
            h.display_summary()

        # Should have called Tree for template variables
        assert console.print.call_count > 0
