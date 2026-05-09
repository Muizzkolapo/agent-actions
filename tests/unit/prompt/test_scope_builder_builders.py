"""Safety-net tests for build_field_context_with_history builder concerns.

Tests each namespace concern (source, dependency, version, workflow) and
cross-cutting behaviors (event firing, assembler combinations) through the
public API. These tests lock in current behavior before the builder-class
refactor and must pass identically after.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_builder import build_field_context_with_history

_EVENT_PATH = "agent_actions.prompt.context.scope_builder.fire_event"


# ---------------------------------------------------------------------------
# Source namespace
# ---------------------------------------------------------------------------
class TestSourceNamespace:
    """Source namespace: wrapped content, flat content, None, empty."""

    def test_wrapped_content(self):
        """Wrapped format: {'content': {'field': value}} unwraps to source."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={"content": {"text": "hello", "lang": "en"}},
        )
        assert result["source"] == {"text": "hello", "lang": "en"}

    def test_flat_content(self):
        """Flat dict goes directly into source namespace."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={"text": "hello"},
        )
        assert result["source"] == {"text": "hello"}

    def test_none_input(self):
        """None source_content produces no 'source' key."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content=None,
        )
        assert "source" not in result

    def test_empty_dict(self):
        """Empty dict produces no 'source' key (falsy check)."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={},
        )
        assert "source" not in result

    def test_non_dict_content_field(self):
        """If 'content' key exists but is not a dict, treat as flat."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={"content": "just a string", "other": "val"},
        )
        assert result["source"] == {"content": "just a string", "other": "val"}


# ---------------------------------------------------------------------------
# Dependency namespace
# ---------------------------------------------------------------------------
class TestDependencyNamespace:
    """Dependency loading: metadata structure, absent namespaces, config errors."""

    def _make_current_item(self, content: dict) -> dict:
        return {
            "content": content,
            "lineage": ["node-1"],
            "source_guid": "sg-1",
        }

    def test_metadata_dict_structure(self):
        """_dependency_metadata has per-dep keys with stored/loaded field info."""
        current_item = self._make_current_item(
            {
                "extract": {"text": "hello", "lang": "en"},
            }
        )
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {"observe": ["extract.text"]},
        }

        result = build_field_context_with_history(
            agent_name="summarize",
            agent_config=agent_config,
            agent_indices={"extract": 0, "summarize": 1},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        meta = result.get("_dependency_metadata")
        assert meta is not None, "_dependency_metadata must be present when deps are loaded"
        assert "extract" in meta
        extract_meta = meta["extract"]
        # context_scope observes only extract.text, so 1 field loaded out of 2 stored
        assert sorted(extract_meta["stored_fields"]) == ["lang", "text"]
        assert extract_meta["loaded_fields"] == ["text"]
        assert extract_meta["stored_count"] == 2
        assert extract_meta["loaded_count"] == 1

    def test_metadata_absent_without_deps(self):
        """No _dependency_metadata when no dependencies are loaded."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config={"agent_type": "test"},
            source_content={"text": "hello"},
        )
        assert "_dependency_metadata" not in result

    def test_configuration_error_deps_without_agent_indices(self):
        """ConfigurationError raised when deps declared but agent_indices missing."""
        with pytest.raises(ConfigurationError, match="agent_indices"):
            build_field_context_with_history(
                agent_name="summarize",
                agent_config={"dependencies": ["extract"]},
                agent_indices=None,
            )

    def test_no_error_without_deps_and_without_indices(self):
        """No error when no dependencies and no agent_indices."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config={"agent_type": "test"},
            agent_indices=None,
        )
        assert result == {}

    def test_absent_namespace_marked_none(self):
        """Absent dependency namespace stored as None (guard-skipped)."""
        current_item = self._make_current_item(
            {
                "extract": {"text": "hello"},
                # "classify" absent
            }
        )
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {"observe": ["extract.text", "classify.topic"]},
        }

        result = build_field_context_with_history(
            agent_name="summarize",
            agent_config=agent_config,
            agent_indices={"extract": 0, "classify": 1, "summarize": 2},
            current_item=current_item,
            context_scope=agent_config["context_scope"],
        )

        assert result["classify"] is None

    def test_batch_mode_skipped_without_current_item(self):
        """Without current_item, batch mode is skipped — no dep namespaces loaded."""
        agent_config = {
            "dependencies": ["extract"],
            "context_scope": {"observe": ["extract.text"]},
        }

        result = build_field_context_with_history(
            agent_name="summarize",
            agent_config=agent_config,
            agent_indices={"extract": 0, "summarize": 1},
            current_item=None,
            context_scope=agent_config["context_scope"],
        )

        assert "extract" not in result
        assert "_dependency_metadata" not in result


# ---------------------------------------------------------------------------
# Version namespace
# ---------------------------------------------------------------------------
class TestVersionNamespace:
    """Version context: namespace structure, top-level promotion, reserved keys."""

    def test_version_namespace_populated(self):
        """Version context stored under 'version' key."""
        vc = {"i": 2, "idx": 1, "length": 3, "first": False, "last": False}
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=vc,
        )
        assert result["version"] == vc

    def test_top_level_i_idx_promotion(self):
        """i and idx promoted to top level for Jinja2 convenience."""
        vc = {"i": 2, "idx": 1, "length": 3, "first": False, "last": False}
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=vc,
        )
        assert result["i"] == 2
        assert result["idx"] == 1

    def test_custom_params_promoted(self):
        """Custom version params (non-reserved) promoted to top level."""
        vc = {
            "i": 1,
            "idx": 0,
            "length": 2,
            "first": True,
            "last": False,
            "classifier_id": 42,
            "model_name": "gpt-4",
        }
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=vc,
        )
        assert result["classifier_id"] == 42
        assert result["model_name"] == "gpt-4"

    def test_reserved_keys_not_double_promoted(self):
        """Reserved keys (length, first, last) are NOT promoted to top level via custom path."""
        vc = {"i": 1, "idx": 0, "length": 5, "first": True, "last": False}
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=vc,
        )
        # length, first, last live under version namespace only
        # (i and idx are promoted separately via explicit checks)
        assert result.get("length") is None
        assert result.get("first") is None
        assert result.get("last") is None

    def test_none_version_context(self):
        """No 'version' key when version_context is None."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=None,
        )
        assert "version" not in result


# ---------------------------------------------------------------------------
# Workflow namespace
# ---------------------------------------------------------------------------
class TestWorkflowNamespace:
    """Workflow metadata namespace."""

    def test_workflow_populated(self):
        """Workflow metadata stored under 'workflow' key."""
        wf = {"name": "my_workflow", "run_id": "abc123"}
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            workflow_metadata=wf,
        )
        assert result["workflow"] == wf

    def test_none_workflow(self):
        """No 'workflow' key when workflow_metadata is None."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            workflow_metadata=None,
        )
        assert "workflow" not in result


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------
class TestEventFiring:
    """ContextNamespaceLoadedEvent fires for source, version, workflow."""

    @staticmethod
    def _events_for_namespace(mock_fire, namespace: str) -> list:
        return [
            call.args[0]
            for call in mock_fire.call_args_list
            if hasattr(call.args[0], "namespace") and call.args[0].namespace == namespace
        ]

    @patch(_EVENT_PATH)
    def test_source_event(self, mock_fire):
        """Source namespace fires event with correct payload."""
        build_field_context_with_history(
            agent_name="test_action",
            agent_config=None,
            source_content={"text": "hello", "lang": "en"},
        )

        events = self._events_for_namespace(mock_fire, "source")
        assert len(events) == 1
        evt = events[0]
        assert evt.action_name == "test_action"
        assert evt.field_count == 2
        assert sorted(evt.fields) == ["lang", "text"]

    @patch(_EVENT_PATH)
    def test_version_event(self, mock_fire):
        """Version namespace fires event with correct payload."""
        vc = {"i": 1, "idx": 0, "length": 2, "first": True, "last": False}
        build_field_context_with_history(
            agent_name="test_action",
            agent_config=None,
            version_context=vc,
        )

        events = self._events_for_namespace(mock_fire, "version")
        assert len(events) == 1
        evt = events[0]
        assert evt.action_name == "test_action"
        assert evt.field_count == 5
        assert sorted(evt.fields) == ["first", "i", "idx", "last", "length"]

    @patch(_EVENT_PATH)
    def test_workflow_event(self, mock_fire):
        """Workflow namespace fires event with correct payload."""
        wf = {"name": "my_wf", "run_id": "r1"}
        build_field_context_with_history(
            agent_name="test_action",
            agent_config=None,
            workflow_metadata=wf,
        )

        events = self._events_for_namespace(mock_fire, "workflow")
        assert len(events) == 1
        evt = events[0]
        assert evt.action_name == "test_action"
        assert evt.field_count == 2
        assert sorted(evt.fields) == ["name", "run_id"]

    @patch(_EVENT_PATH)
    def test_no_events_for_empty_inputs(self, mock_fire):
        """No events fire when all inputs are None/empty."""
        build_field_context_with_history(
            agent_name="test",
            agent_config=None,
        )
        assert mock_fire.call_count == 0


# ---------------------------------------------------------------------------
# Assembler combinations
# ---------------------------------------------------------------------------
class TestAssemblerCombinations:
    """Test that the assembler handles all combinations of None/populated args."""

    def test_all_none_returns_empty(self):
        """All None inputs produce empty dict."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
        )
        assert result == {}

    def test_source_only(self):
        """Only source populated — only 'source' key present."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={"text": "hi"},
        )
        assert set(result.keys()) == {"source"}

    def test_version_only(self):
        """Only version populated — 'version' + promoted keys present."""
        vc = {"i": 1, "idx": 0, "length": 1, "first": True, "last": True}
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            version_context=vc,
        )
        assert "version" in result
        assert "i" in result
        assert "idx" in result

    def test_all_populated(self):
        """All non-dependency inputs populated — all namespaces present."""
        result = build_field_context_with_history(
            agent_name="test",
            agent_config=None,
            source_content={"text": "hi"},
            version_context={"i": 1, "idx": 0, "length": 1, "first": True, "last": True},
            workflow_metadata={"name": "wf"},
        )
        assert "source" in result
        assert "version" in result
        assert "workflow" in result
        assert result["source"] == {"text": "hi"}
        assert result["workflow"] == {"name": "wf"}
