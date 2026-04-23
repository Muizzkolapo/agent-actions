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
    """PassthroughEnricher merges passthrough fields into the action namespace."""

    def test_merges_into_existing_action_namespace(self):
        """Passthrough fields merge INTO content[action_name], not top-level."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "llm_output"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"pt_field": "preserved"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        # passthrough field is inside action_c namespace
        assert out["action_c"]["pt_field"] == "preserved"
        assert out["action_c"]["llm_field"] == "llm_output"
        # NOT at top level
        assert "pt_field" not in out

    def test_creates_namespace_when_absent(self):
        """If action namespace doesn't exist, passthrough fields create it."""
        content = _namespaced_content()  # no action_c
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"pt_field": "preserved"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        out = enriched.data[0]["content"]
        assert out["action_c"] == {"pt_field": "preserved"}
        assert "pt_field" not in out

    def test_preserves_other_namespaces(self):
        """Other action namespaces are not modified."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"pt_field": "preserved"},
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

    def test_multiple_items(self):
        """Passthrough fields merge into each item's action namespace."""
        items = [
            {"content": {**_namespaced_content(), "action_c": {"idx": 0}}},
            {"content": {**_namespaced_content(), "action_c": {"idx": 1}}},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=items,
            passthrough_fields={"pt": "val"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        for i in range(2):
            assert enriched.data[i]["content"]["action_c"]["pt"] == "val"
            assert enriched.data[i]["content"]["action_c"]["idx"] == i
            assert "pt" not in enriched.data[i]["content"]

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

    def test_multiple_passthrough_fields(self):
        """Multiple passthrough fields all merge into action namespace."""
        content = {**_namespaced_content(), "action_c": {"llm_field": "val"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"pt_a": "a", "pt_b": "b", "pt_c": "c"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        ns = enriched.data[0]["content"]["action_c"]
        assert ns["pt_a"] == "a"
        assert ns["pt_b"] == "b"
        assert ns["pt_c"] == "c"
        assert ns["llm_field"] == "val"

    def test_passthrough_field_overwrites_llm_field_with_same_key(self):
        """Passthrough field with same key as LLM output overwrites it."""
        content = {**_namespaced_content(), "action_c": {"shared_key": "llm_value"}}
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content}],
            passthrough_fields={"shared_key": "passthrough_value"},
        )
        context = _make_context("action_c")
        enriched = PassthroughEnricher().enrich(result, context)

        assert enriched.data[0]["content"]["action_c"]["shared_key"] == "passthrough_value"


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
        pytest.param(
            RequiredFieldsEnricher, {"source_guid": "sg-1"}, {}, id="required_fields"
        ),
        pytest.param(
            RecoveryEnricher, {"recovery_metadata": _RECOVERY_META}, {}, id="recovery"
        ),
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
        """All enrichers run in sequence — passthrough in action namespace, others at record level."""
        content = {
            "action_a": {"field_a": "val_a"},
            "action_b": {"field_b": "val_b"},
            "action_c": {"llm_field": "llm_output"},
        }
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": content, "source_guid": "sg-1"}],
            source_guid="sg-1",
            passthrough_fields={"pt_field": "preserved_value"},
            pre_extracted_metadata={"model": "gpt-4"},
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout")
            ),
        )
        context = _make_context("action_c", is_first_stage=True)

        enriched = EnrichmentPipeline().enrich(result, context)

        item = enriched.data[0]

        # Passthrough fields merged into action_c namespace
        assert item["content"]["action_c"]["pt_field"] == "preserved_value"
        assert item["content"]["action_c"]["llm_field"] == "llm_output"
        assert "pt_field" not in item["content"]

        # Other namespaces preserved
        assert item["content"]["action_a"] == {"field_a": "val_a"}
        assert item["content"]["action_b"] == {"field_b": "val_b"}

        # Record-level enrichments present
        assert "lineage" in item
        assert "node_id" in item
        assert "metadata" in item
        assert "_recovery" in item
