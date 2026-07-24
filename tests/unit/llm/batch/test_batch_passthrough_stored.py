"""Tests for stored passthrough merge at batch result processing.

Passthrough fields are pre-extracted during batch preparation and stored in
BatchContextMetadata as {namespace: {field: value}}. At result processing
time, each namespace is merged into the record content as a sibling of the
action namespace — never inside the action output.
"""

from typing import Any
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.utils.transformation.passthrough import merge_passthrough_namespaces

# ── Helpers ──────────────────────────────────────────────────────────


def _make_context_map_entry(**extra) -> dict[str, Any]:
    """Build a context_map entry (same shape as a data row with batch metadata)."""
    base = {
        "target_id": "rec_001",
        "source_guid": "src_001",
        "content": {"text": "row content"},
    }
    base.update(extra)
    return base


def _make_batch_result(custom_id: str, content: dict[str, Any]) -> BatchResult:
    result = MagicMock(spec=BatchResult)
    result.custom_id = custom_id
    result.content = content
    result.error = None
    result.success = True
    result.metadata = {}
    result.recovery_metadata = None
    return result


def _process(context_map: dict[str, Any], llm_content: dict[str, Any]) -> list:
    strategy = BatchResultStrategy()
    return strategy.process(
        batch_results=[_make_batch_result("rec_001", llm_content)],
        context_map=context_map,
        output_directory="/tmp/test",
        agent_config={"action_name": "summarize"},
    )


# ── Stored passthrough merges at content level ───────────────────────


class TestStoredPassthroughMerge:
    def test_single_namespace_lands_at_content_level(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})

        results = _process({"rec_001": entry}, {"summary": "AI overview"})

        content = results[0].data[0]["content"]
        assert content["summarize"]["summary"] == "AI overview"
        assert content["classify"] == {"category": "tech"}
        assert "classify" not in content["summarize"]

    def test_multiple_namespaces(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(
            entry,
            {
                "classify": {"category": "tech"},
                "extract": {"record_id": "abc"},
            },
        )

        results = _process({"rec_001": entry}, {"summary": "test"})

        content = results[0].data[0]["content"]
        assert content["classify"] == {"category": "tech"}
        assert content["extract"] == {"record_id": "abc"}
        assert content["summarize"]["summary"] == "test"

    def test_all_generated_items_receive_passthrough(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})

        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[_make_batch_result("rec_001", [{"item": 1}, {"item": 2}, {"item": 3}])],
            context_map={"rec_001": entry},
            output_directory="/tmp/test",
            agent_config={"action_name": "summarize"},
        )

        data = results[0].data
        assert len(data) == 3
        for record in data:
            assert record["content"]["classify"] == {"category": "tech"}

    def test_stored_passthrough_applies_without_context_scope_config(self):
        """Stored passthrough applies even when agent_config lacks context_scope."""
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"source_meta": {"id": "123"}})

        results = _process({"rec_001": entry}, {"output": "val"})

        content = results[0].data[0]["content"]
        assert content["source_meta"] == {"id": "123"}
        assert content["summarize"]["output"] == "val"


# ── merge_passthrough_namespaces edge cases ──────────────────────────


class TestMergePassthroughNamespaces:
    def test_empty_passthrough_leaves_content_unchanged(self):
        content = {"summarize": {"summary": "test"}}
        merge_passthrough_namespaces(content, {}, "summarize")
        assert content == {"summarize": {"summary": "test"}}

    def test_action_namespace_never_overwritten(self):
        content = {"summarize": {"summary": "LLM output"}}
        merge_passthrough_namespaces(content, {"summarize": {"summary": "stale"}}, "summarize")
        assert content["summarize"]["summary"] == "LLM output"

    def test_existing_namespace_wins_per_field(self):
        content = {"classify": {"category": "finance"}}
        merge_passthrough_namespaces(
            content, {"classify": {"category": "stale", "region": "US"}}, "summarize"
        )
        assert content["classify"] == {"category": "finance", "region": "US"}

    def test_non_dict_entries_ignored(self):
        content = {"summarize": {"summary": "test"}}
        merge_passthrough_namespaces(
            content, {"target_id": "rec_001", "flat": "value"}, "summarize"
        )
        assert "target_id" not in content
        assert "flat" not in content

    def test_null_namespace_in_content_left_intact(self):
        """A guard-skipped (None) namespace must not be replaced by the passthrough copy."""
        content = {"classify": None}
        merge_passthrough_namespaces(content, {"classify": {"category": "tech"}}, "summarize")
        assert content["classify"] is None


class TestReconcilerRoundTrip:
    def test_no_stored_passthrough_content_unchanged(self):
        entry = _make_context_map_entry()

        results = _process({"rec_001": entry}, {"summary": "test"})

        content = results[0].data[0]["content"]
        assert content["summarize"]["summary"] == "test"
        namespaces = set(content.keys()) - {"summarize"}
        assert not any(isinstance(content.get(ns), dict) and ns == "classify" for ns in namespaces)

    def test_reconciler_still_resolves_guid(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})
        reconciler = BatchResultReconciler({"rec_001": entry})
        assert reconciler.get_source_guid("rec_001") == "src_001"
