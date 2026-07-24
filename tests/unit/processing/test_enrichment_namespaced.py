"""Tests for enrichment pipeline with namespaced content.

Content is namespaced: {"action_a": {...}, "action_b": {...}}.
PassthroughEnricher must merge into content[action_name], not top-level.
Other enrichers must NOT modify content internals — they work at record level.
"""

import pytest

from agent_actions.processing.enrichment import (
    EnrichmentPipeline,
    LineageEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RecoveryEnricher,
    RequiredFieldsEnricher,
    VersionIdEnricher,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)


def _make_context(action_name="action_c", is_first_stage=False):
    return ProcessingContext(
        agent_config={"agent_type": action_name, "kind": "llm", "granularity": "record"},
        agent_name=action_name,
        is_first_stage=is_first_stage,
    )


def _namespaced_content():
    return {
        "action_a": {"field_a": "val_a"},
        "action_b": {"field_b": "val_b"},
    }


# ---------------------------------------------------------------------------
# PassthroughEnricher — namespaced content
# ---------------------------------------------------------------------------


class TestPassthroughEnricherNamespaced:
    """PassthroughEnricher places passthrough namespaces at content level."""

    def test_passthrough_namespace_lands_at_content_level(self):
        content = {**_namespaced_content(), "action_c": {"llm_field": "llm_output"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"upstream_hitl": {"hitl_status": "approved"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["upstream_hitl"] == {"hitl_status": "approved"}
        assert out["action_c"] == {"llm_field": "llm_output"}
        assert "upstream_hitl" not in out["action_c"]

    def test_action_namespace_never_overwritten(self):
        """A passthrough namespace matching the action name is skipped."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "llm_output"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"action_c": {"llm_field": "stale"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        assert enriched.data[0]["content"]["action_c"] == {"llm_field": "llm_output"}

    def test_existing_namespace_wins_per_field(self):
        """Content-level namespaces keep their values; passthrough fills gaps."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"action_a": {"field_a": "stale", "field_extra": "new"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["action_a"]["field_a"] == "val_a"
        assert out["action_a"]["field_extra"] == "new"

    def test_preserves_other_namespaces(self):
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"upstream_hitl": {"hitl_status": "approved"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["action_a"] == {"field_a": "val_a"}
        assert out["action_b"] == {"field_b": "val_b"}

    def test_no_passthrough_fields_is_noop(self):
        """Empty passthrough_fields returns result unchanged."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        data = [{"content": content}]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=data,
            passthrough_fields={},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        assert enriched.data[0]["content"] == content

    def test_idempotent_after_transform_time_merge(self):
        """Running the enricher on a record that already carries the namespace is a no-op."""
        content = {
            **_namespaced_content(),
            "upstream_hitl": {"hitl_status": "approved"},
            "action_c": {"llm_field": "val"},
        }
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"upstream_hitl": {"hitl_status": "approved"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["upstream_hitl"] == {"hitl_status": "approved"}
        assert "upstream_hitl" not in out["action_c"]

    def test_multiple_items(self):
        items = [
            {"content": {**_namespaced_content(), "action_c": {"idx": 0}}},
            {"content": {**_namespaced_content(), "action_c": {"idx": 1}}},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=items,
            passthrough_fields={"upstream_hitl": {"hitl_status": "approved"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        for i in range(2):
            out = enriched.data[i]["content"]
            assert out["upstream_hitl"] == {"hitl_status": "approved"}
            assert out["action_c"]["idx"] == i
            assert "upstream_hitl" not in out["action_c"]

    def test_item_without_content_key_skipped(self):
        """Items with no content dict are skipped without error."""
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"some_field": "val"}],
            passthrough_fields={"pt": "val"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        assert "content" not in enriched.data[0]
        assert "pt" not in enriched.data[0]

    def test_multiple_passthrough_namespaces(self):
        """Multiple passthrough namespaces all land at content level."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"ns_a": {"a": 1}, "ns_b": {"b": 2}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["ns_a"] == {"a": 1}
        assert out["ns_b"] == {"b": 2}
        assert out["action_c"] == {"llm_field": "val"}

    def test_flat_passthrough_entries_ignored(self):
        """Non-namespaced (non-dict) passthrough entries are not merged anywhere."""
        content = {**_namespaced_content(), "action_c": {"shared_key": "llm_value"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"shared_key": "passthrough_value"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["action_c"]["shared_key"] == "llm_value"
        assert out.get("shared_key") is None

    def test_shared_namespace_dict_not_mutated(self):
        """Filling gaps in an existing namespace must not mutate the shared dict in place."""
        shared_ns = {"llm_field": "original"}
        item_a = {"content": {"upstream": shared_ns, "action_c": {"out": 1}}}

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[item_a],
            passthrough_fields={"upstream": {"extra_field": "a_value"}},
        )
        context = _make_context("action_c")
        PassthroughEnricher().enrich(result, context)

        assert item_a["content"]["upstream"]["extra_field"] == "a_value"
        assert item_a["content"]["upstream"]["llm_field"] == "original"
        assert shared_ns == {"llm_field": "original"}

    def test_shared_namespace_multiple_records_in_same_result(self):
        """Inserted passthrough namespaces are independent copies per record."""
        items = [
            {"content": {"action_c": {"idx": 0}}},
            {"content": {"action_c": {"idx": 1}}},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=items,
            passthrough_fields={"upstream": {"base": "value"}},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        assert enriched.data[0]["content"]["upstream"] == {"base": "value"}
        assert enriched.data[1]["content"]["upstream"] == {"base": "value"}
        enriched.data[0]["content"]["upstream"]["extra"] = "only_in_0"
        assert "extra" not in enriched.data[1]["content"]["upstream"]


# ---------------------------------------------------------------------------
# Other enrichers — verify they don't touch content internals
# ---------------------------------------------------------------------------


_RECOVERY_META = RecoveryMetadata(
    retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout")
)


@pytest.mark.parametrize(
    "enricher_cls,extra_result_kwargs,extra_context_kwargs",
    [
        pytest.param(
            LineageEnricher,
            {"source_guid": "sg-1"},
            {"is_first_stage": True},
            id="lineage",
        ),
        pytest.param(
            MetadataEnricher,
            {"pre_extracted_metadata": {"model": "gpt-4", "tokens": 100}},
            {},
            id="metadata",
        ),
        pytest.param(VersionIdEnricher, {}, {}, id="version_id"),
        pytest.param(RequiredFieldsEnricher, {"source_guid": "sg-1"}, {}, id="required_fields"),
        pytest.param(RecoveryEnricher, {"recovery_metadata": _RECOVERY_META}, {}, id="recovery"),
    ],
)
def test_enricher_does_not_touch_content(enricher_cls, extra_result_kwargs, extra_context_kwargs):
    """Each non-passthrough enricher works at record level — content keys unchanged."""
    content = _namespaced_content()
    original_keys = set(content.keys())

    data_item = {"content": content}
    if "source_guid" in extra_result_kwargs:
        data_item["source_guid"] = extra_result_kwargs["source_guid"]

    result = ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[data_item],
        **extra_result_kwargs,
    )
    context = _make_context("action_c", **extra_context_kwargs)

    enriched = enricher_cls().enrich(result, context)

    assert set(enriched.data[0]["content"].keys()) == original_keys


# ---------------------------------------------------------------------------
# Full pipeline — all enrichers in sequence
# ---------------------------------------------------------------------------


class TestEnrichmentPipelineNamespaced:
    """Full enrichment pipeline with namespaced content."""

    def test_full_pipeline_passthrough_in_correct_namespace(self):
        """All enrichers run in sequence — passthrough at content level, others at record level."""
        content = {
            "action_a": {"field_a": "val_a"},
            "action_b": {"field_b": "val_b"},
            "action_c": {"llm_field": "llm_output"},
        }
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content, "source_guid": "sg-1"}],
            source_guid="sg-1",
            passthrough_fields={"upstream_hitl": {"hitl_status": "approved"}},
            pre_extracted_metadata={"model": "gpt-4"},
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout")
            ),
        )
        context = _make_context("action_c", is_first_stage=True)

        enriched = EnrichmentPipeline().enrich(result, context)

        item = enriched.data[0]

        # Passthrough namespace is a sibling of the action namespace
        assert item["content"]["upstream_hitl"] == {"hitl_status": "approved"}
        assert item["content"]["action_c"] == {"llm_field": "llm_output"}
        assert "upstream_hitl" not in item["content"]["action_c"]

        # Other namespaces preserved
        assert item["content"]["action_a"] == {"field_a": "val_a"}
        assert item["content"]["action_b"] == {"field_b": "val_b"}

        # Record-level enrichments present
        assert "lineage" in item
        assert "node_id" in item
        assert "metadata" in item
        assert "_recovery" in item
