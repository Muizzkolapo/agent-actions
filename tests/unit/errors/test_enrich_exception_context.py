"""Tests for enrich_exception_context helper."""

from agent_actions.errors import AgentActionsError, enrich_exception_context
from agent_actions.errors.base import enrich_exception_context as base_enrich


class TestEnrichAgentActionsError:
    def test_updates_empty_context(self):
        e = AgentActionsError("msg")
        enrich_exception_context(e, key="val")
        assert e.context["key"] == "val"

    def test_preserves_existing_context(self):
        e = AgentActionsError("msg", context={"existing": 1})
        enrich_exception_context(e, new="2")
        assert e.context == {"existing": 1, "new": "2"}

    def test_overwrites_duplicate_key(self):
        e = AgentActionsError("msg", context={"op": "old"})
        enrich_exception_context(e, op="new")
        assert e.context["op"] == "new"

    def test_multiple_kwargs(self):
        e = AgentActionsError("msg")
        enrich_exception_context(e, workflow="wf", operation="async")
        assert e.context == {"workflow": "wf", "operation": "async"}


class TestEnrichBareException:
    def test_bare_exception_gets_context_created(self):
        e = RuntimeError("msg")
        enrich_exception_context(e, key="val")
        assert e.context["key"] == "val"  # type: ignore[attr-defined]

    def test_string_context_gets_replaced(self):
        e = RuntimeError("msg")
        e.context = "I am a string"  # type: ignore[attr-defined]
        enrich_exception_context(e, key="val")
        assert isinstance(e.context, dict)  # type: ignore[attr-defined]
        assert e.context["key"] == "val"  # type: ignore[attr-defined]

    def test_existing_dict_context_gets_updated(self):
        e = RuntimeError("msg")
        e.context = {"old": 1}  # type: ignore[attr-defined]
        enrich_exception_context(e, new=2)
        assert e.context == {"old": 1, "new": 2}  # type: ignore[attr-defined]

    def test_none_context_gets_replaced(self):
        e = ValueError("msg")
        e.context = None  # type: ignore[attr-defined]
        enrich_exception_context(e, key="val")
        assert isinstance(e.context, dict)  # type: ignore[attr-defined]
        assert e.context["key"] == "val"  # type: ignore[attr-defined]

    def test_list_context_gets_replaced(self):
        e = KeyError("msg")
        e.context = [1, 2, 3]  # type: ignore[attr-defined]
        enrich_exception_context(e, key="val")
        assert isinstance(e.context, dict)  # type: ignore[attr-defined]
        assert e.context["key"] == "val"  # type: ignore[attr-defined]


class TestReExport:
    def test_importable_from_package(self):
        assert enrich_exception_context is base_enrich
